from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import Company
from payroll.models import PayrollRun
from regional.filings import due_date_for_rule, filing_status, aggregate_payroll_for_filing
from regional.models import CompanyCountryProfile, StatutoryFilingRule, StatutoryFiling


class Command(BaseCommand):
    help = 'Generate statutory filing obligations for the previous calendar month for configured companies.'

    def handle(self, *args, **options):
        today = timezone.localdate()
        year, month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        period_start = date(year, month, 1)
        period_end = date(year, month, monthrange(year, month)[1])
        total = 0

        for company in Company.objects.filter(is_active=True).select_related('country_profile'):
            profile = CompanyCountryProfile.objects.filter(company=company).first()
            if not profile:
                continue
            rules = StatutoryFilingRule.objects.filter(
                country_code=profile.country_code, is_active=True,
                effective_from__lte=period_end,
            ).filter(
                models_q_end(period_end)
            ).order_by('code', '-effective_from')
            seen = set()
            payroll_run = PayrollRun.objects.filter(company=company, period_start=period_start, period_end=period_end).first()
            with transaction.atomic():
                for rule in rules:
                    if rule.code in seen or (rule.frequency == 'annual' and period_end.month != 12):
                        continue
                    seen.add(rule.code)
                    if StatutoryFiling.objects.filter(company=company, rule=rule, period_start=period_start, period_end=period_end).exists():
                        continue
                    amount = Decimal('0')
                    if payroll_run:
                        if rule.code == 'paye':
                            amount = sum((p.tax_amount for p in payroll_run.payslips.all()), Decimal('0'))
                        else:
                            for line in aggregate_payroll_for_filing(payroll_run):
                                if line['code'] == rule.code:
                                    amount = Decimal(line['employee_share']) + Decimal(line['employer_share'])
                    due = due_date_for_rule(rule, period_end)
                    StatutoryFiling.objects.create(
                        company=company, rule=rule, payroll_run=payroll_run,
                        period_start=period_start, period_end=period_end, due_date=due,
                        amount=amount, status=filing_status(due),
                    )
                    total += 1
        self.stdout.write(self.style.SUCCESS(f'Generated {total} statutory filing obligations for {period_start} to {period_end}.'))


def models_q_end(day):
    from django.db.models import Q
    return Q(effective_to__isnull=True) | Q(effective_to__gte=day)
