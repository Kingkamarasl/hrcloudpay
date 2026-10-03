"""Payroll-linked statutory compliance pack orchestration."""
from datetime import date
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
from decimal import Decimal
import csv

from django.db import transaction
from django.utils import timezone

from .filings import due_date_for_rule, filing_status, aggregate_payroll_for_filing
from .models import CompanyCountryProfile, StatutoryFilingRule, StatutoryFiling, StatutoryCompliancePack
from .reports import COUNTRY_REPORTS, report_rows, columns


def effective_rules(country_code, period_end):
    from django.db.models import Q
    qs = StatutoryFilingRule.objects.filter(
        country_code=country_code, is_active=True, effective_from__lte=period_end
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=period_end)).order_by('code', '-effective_from')
    seen = set()
    result = []
    for rule in qs:
        if rule.code in seen:
            continue
        seen.add(rule.code)
        result.append(rule)
    return result


def create_compliance_pack(payroll_run, actor=None):
    """Create/update filings and a compliance-pack record for an approved/paid run."""
    company = payroll_run.company
    profile = CompanyCountryProfile.objects.filter(company=company).first()
    if not profile:
        return None
    rules = effective_rules(profile.country_code, payroll_run.period_end)
    reports = COUNTRY_REPORTS.get(profile.country_code, [])
    payroll_aggregate = {line['code']: line for line in aggregate_payroll_for_filing(payroll_run)}
    payroll_paye_total = sum((p.tax_amount for p in payroll_run.payslips.all()), Decimal('0'))
    with transaction.atomic():
        pack, _ = StatutoryCompliancePack.objects.select_for_update().get_or_create(
            company=company, payroll_run=payroll_run,
            defaults={
                'country_code': profile.country_code,
                'period_start': payroll_run.period_start,
                'period_end': payroll_run.period_end,
            },
        )
        for rule in rules:
            if rule.frequency == 'annual' and payroll_run.period_end.month != 12:
                continue
            due = due_date_for_rule(rule, payroll_run.period_end)
            if rule.code == 'paye':
                amount = payroll_paye_total
            else:
                amount = Decimal('0')
                line = payroll_aggregate.get(rule.code)
                if line:
                    amount = Decimal(line['employee_share']) + Decimal(line['employer_share'])
            filing, _ = StatutoryFiling.objects.get_or_create(
                company=company, rule=rule,
                period_start=payroll_run.period_start, period_end=payroll_run.period_end,
                defaults={
                    'payroll_run': payroll_run,
                    'due_date': due,
                    'amount': amount,
                    'status': filing_status(due),
                },
            )
            # A reviewed or later filing is a financial record. Regenerating a
            # compliance pack must not change its amount, deadline or state.
            if filing.status in ('open', 'ready', 'overdue') and (
                filing.payroll_run_id != payroll_run.id
                or filing.due_date != due
                or filing.amount != amount
            ):
                filing.payroll_run = payroll_run
                filing.due_date = due
                filing.amount = amount
                filing.save(update_fields=['payroll_run', 'due_date', 'amount', 'updated_at'])
        pack.filing_count = StatutoryFiling.objects.filter(payroll_run=payroll_run).count()
        pack.report_count = len(reports)
        pack.status = 'ready' if pack.filing_count or pack.report_count else 'draft'
        pack.save(update_fields=['country_code','period_start','period_end','filing_count','report_count','status','updated_at'])
    return pack


def build_compliance_pack_zip(pack):
    """Build a ZIP containing a manifest, filing register CSV, and country Excel reports."""
    from openpyxl import Workbook
    # Imported here, not at module scope: `regional` is the lower layer, and
    # `payroll` already depends on it.
    from payroll.services import collect_compliance_gaps
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as z:
        filings = list(StatutoryFiling.objects.filter(company=pack.company, payroll_run=pack.payroll_run).select_related('rule'))
        manifest = [
            ['HRCloudPay Compliance Pack'],
            ['Company', pack.company.name],
            ['Country', pack.country_code],
            ['Payroll period', f'{pack.period_start} to {pack.period_end}'],
            ['Payroll status', pack.payroll_run.status],
            ['Pack status', pack.status],
            ['Generated', timezone.now().isoformat()],
        ]
        # A pack is the artifact handed to an auditor or a revenue authority, so
        # a PAYE figure in it that HRCloudPay never verified against statute has
        # to say so here. Without this, an acknowledged-but-unverified run
        # produces a pack whose tax line reads as clean and statutory - which
        # is the same misrepresentation one layer up, in the one document where
        # it would be relied upon.
        gaps = collect_compliance_gaps(pack.payroll_run)
        if gaps:
            manifest.append(['Statutory verification', 'INCOMPLETE'])
            for gap in gaps:
                manifest.append(['Verification gap', f'{gap["code"]} ({gap["cause"]}): {gap["message"]}'])
        else:
            manifest.append(['Statutory verification', 'All applied rules verified for this period'])
        manifest += [
            [],
            ['Filing code','Authority','Due date','Amount','Status','Reference'],
        ]
        for f in filings:
            manifest.append([f.rule.code, f.rule.authority, str(f.due_date), str(f.amount), f.status, f.reference])
        import io
        text=io.StringIO(); cw=csv.writer(text)
        for row in manifest: cw.writerow(row)
        z.writestr('manifest.csv', text.getvalue())

        for report in COUNTRY_REPORTS.get(pack.country_code, []):
            wb=Workbook(); ws=wb.active; ws.title=report['code'][:31]
            cols=columns(report['code']); ws.append([label for _,label in cols])
            for row in report_rows(report['code'], pack.payroll_run): ws.append([row.get(key,'') for key,_ in cols])
            ws.freeze_panes='A2'
            stream=BytesIO(); wb.save(stream)
            z.writestr(f'reports/{report["code"]}-{pack.period_end}.xlsx', stream.getvalue())
    return output.getvalue()
