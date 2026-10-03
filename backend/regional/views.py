import csv
from datetime import date
from decimal import Decimal

from django.db import connection, transaction
from django.db.models import Sum, Count
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.audit import audit
from accounts.permissions import IsCompanyMember, IsCompanyActive, CanManageStatutory

from django.db.models import Q

from .countries.registry import COUNTRY_PACKS
from .engine import calculate_statutory_contributions
from .filings import due_date_for_rule, filing_status, aggregate_payroll_for_filing
from .compliance import create_compliance_pack, build_compliance_pack_zip
from .reports import COUNTRY_REPORTS, report_rows, columns
from .models import CompanyCountryProfile, StatutoryFilingRule, StatutoryFiling, StatutoryCompliancePack, StatutoryFilingPayment
from .serializers import (
    CountryOptionSerializer, CompanyCountryProfileSerializer,
    StatutoryFilingRuleSerializer, StatutoryFilingSerializer, StatutoryCompliancePackSerializer, StatutoryFilingPaymentSerializer,
)


TERMINAL_FILING_STATUSES = ('submitted', 'closed', 'filed')


def models_q_end(today):
    """Active effective-dated rule filter shared by calendar and generation."""
    return Q(effective_to__isnull=True) | Q(effective_to__gte=today)


def get_effective_rules(queryset):
    """Deduplicate an ordered (code, -effective_from) queryset to latest per code."""
    seen = set()
    effective = []
    for rule in queryset:
        if rule.code in seen:
            continue
        seen.add(rule.code)
        effective.append(rule)
    return effective


class CountryOptionsView(APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        rows = [CountryOptionSerializer({
            'code': p.code, 'name': p.name, 'currency': p.currency,
            'timezone': p.timezone, 'payroll_frequencies': list(p.payroll_frequencies),
            'employee_identifiers': list(p.employee_identifiers),
            'compliance_domains': list(p.compliance_domains),
            'integration_tags': list(p.integration_tags),
            'employee_fields': [{'key': k, 'label': label, 'required': required} for k,label,required in p.employee_fields],
            'official_languages': list(p.official_languages),
            'localized_name': p.localized_name,
        }).data for p in COUNTRY_PACKS.values()]
        return Response(rows)


class CompanyCountryExperienceView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]

    def get(self, request):
        profile = CompanyCountryProfile.objects.filter(company=request.user.company).first()
        if not profile:
            return Response({'configured': False, 'country': request.user.company.country})
        return Response({'configured': True, 'profile': CompanyCountryProfileSerializer(profile).data})

    def patch(self, request):
        company = request.user.company
        profile = CompanyCountryProfile.objects.filter(company=company).first()
        if not profile:
            return Response({'detail': 'Company country profile has not been initialized.'}, status=404)
        serializer = CompanyCountryProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()
        return Response(CompanyCountryProfileSerializer(profile).data)


class CompanyOnboardingView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]

    def get(self, request):
        company = request.user.company
        profile = CompanyCountryProfile.objects.filter(company=company).first()
        if not profile:
            return Response({'configured': False}, status=200)
        pack = COUNTRY_PACKS[profile.country_code]
        employee_count = company.employees.count()
        return Response({
            'configured': True,
            'company': {'id': company.id, 'name': company.name, 'country_code': profile.country_code, 'country_name': pack.name, 'currency': profile.currency_code, 'timezone': profile.timezone, 'payroll_frequency': profile.payroll_frequency},
            'employee_setup': {'count': employee_count, 'required_fields': [{'key': k, 'label': label, 'required': required} for k,label,required in pack.employee_fields]},
            'compliance_domains': list(pack.compliance_domains),
            'integrations': list(pack.integration_tags),
            'steps': [
                {'key':'company','label':'Company profile','complete':bool(company.name and company.email)},
                {'key':'country','label':f'{pack.name} configuration','complete':bool(profile.country_code and profile.currency_code)},
                {'key':'payroll','label':'Payroll setup','complete':bool(company.payroll_configured)},
                {'key':'employees','label':'Add employees','complete':employee_count > 0},
                {'key':'compliance','label':'Compliance rules','complete':False},
            ],
        })


class StatutoryPreviewView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]

    def get(self, request):
        profile = CompanyCountryProfile.objects.filter(company=request.user.company).first()
        if not profile:
            return Response({'detail': 'Company country profile is not configured.'}, status=404)
        try:
            gross = Decimal(str(request.query_params.get('gross', '0')))
            basic = Decimal(str(request.query_params.get('basic', gross)))
            as_of = date.fromisoformat(request.query_params.get('as_of')) if request.query_params.get('as_of') else timezone.localdate()
            contributions = calculate_statutory_contributions(profile.country_code, gross, basic, as_of)
        except (TypeError, ValueError, ArithmeticError):
            return Response({'detail': 'gross/basic must be numbers and as_of must be YYYY-MM-DD.'}, status=400)
        return Response({'country': profile.country_code, 'as_of': as_of, 'gross': str(gross), 'basic': str(basic), 'contributions': contributions})



class StatutoryReportCatalogView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]

    def get(self, request):
        profile = CompanyCountryProfile.objects.filter(company=request.user.company).first()
        if not profile:
            return Response({'configured': False, 'reports': []})
        return Response({'configured': True, 'country': profile.country_code, 'reports': COUNTRY_REPORTS.get(profile.country_code, [])})


class StatutoryReportExportView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]

    def get(self, request, report_code):
        profile = CompanyCountryProfile.objects.filter(company=request.user.company).first()
        if not profile:
            return Response({'detail': 'Company country profile is not configured.'}, status=400)
        report = next((x for x in COUNTRY_REPORTS.get(profile.country_code, []) if x['code'] == report_code), None)
        if not report:
            return Response({'detail': 'Statutory report is not available for this country.'}, status=404)
        try:
            period_start = date.fromisoformat(str(request.query_params.get('period_start')))
            period_end = date.fromisoformat(str(request.query_params.get('period_end')))
        except (TypeError, ValueError):
            return Response({'detail': 'period_start and period_end are required as YYYY-MM-DD.'}, status=400)
        payroll_run = request.user.company.payroll_runs.filter(period_start=period_start, period_end=period_end).first()
        if not payroll_run:
            return Response({'detail': 'No payroll run exists for the requested period.'}, status=404)
        rows = report_rows(report_code, payroll_run)
        cols = columns(report_code)
        from openpyxl import Workbook
        from openpyxl.styles import Font
        wb = Workbook()
        ws = wb.active
        ws.title = report_code[:31]
        ws.append([label for _, label in cols])
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for row in rows:
            ws.append([row.get(key, '') for key, _ in cols])
        ws.freeze_panes = 'A2'
        for col in ws.columns:
            max_len = max(len(str(c.value or '')) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 2, 12), 35)
        from io import BytesIO
        stream = BytesIO()
        wb.save(stream)
        response = HttpResponse(stream.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="{report_code}-{period_end}.xlsx"'
        return response


class ComplianceDashboardView(APIView):
    """Single tenant view of statutory exposure, deadlines and reconciliation."""
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]

    def get(self, request):
        company = request.user.company
        profile = CompanyCountryProfile.objects.filter(company=company).first()
        if not profile:
            return Response({'configured': False, 'country': None, 'summary': {}, 'filings': [], 'packs': []})
        today = timezone.localdate()
        qs = StatutoryFiling.objects.filter(company=company).select_related('rule', 'payroll_run')
        try:
            window = min(max(int(request.query_params.get('days', 30)), 1), 366)
        except (TypeError, ValueError):
            window = 30
        cutoff = today.fromordinal(today.toordinal() + window)
        outstanding = qs.exclude(status__in=TERMINAL_FILING_STATUSES)
        upcoming = outstanding.filter(due_date__lte=cutoff).order_by('due_date', 'rule__code')
        filed = qs.filter(status__in=TERMINAL_FILING_STATUSES)
        overdue = outstanding.filter(due_date__lt=today)
        open_qs = outstanding.filter(due_date__gte=today)
        totals = qs.aggregate(total_open=Sum('amount', filter=Q(status__in=('open', 'reviewed', 'approved', 'paid', 'overdue'))))
        total_open = totals['total_open'] or Decimal('0')
        total_overdue = overdue.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        next_due = open_qs.filter(due_date__lte=cutoff).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        reconciliation = []
        tolerance = Decimal('0.01')
        filings_with_runs = list(qs.filter(payroll_run__isnull=False).order_by('-period_end', 'rule__code').prefetch_related('payroll_run__payslips')[:100])
        aggregate_cache = {}
        for f in filings_with_runs:
            if f.payroll_run_id not in aggregate_cache:
                aggregate_cache[f.payroll_run_id] = {line['code']: line for line in aggregate_payroll_for_filing(f.payroll_run)}
            expected = Decimal('0')
            if f.rule.code == 'paye':
                expected = sum((p.tax_amount for p in f.payroll_run.payslips.all()), Decimal('0'))
            else:
                line = aggregate_cache[f.payroll_run_id].get(f.rule.code)
                if line:
                    expected = Decimal(line['employee_share']) + Decimal(line['employer_share'])
            variance = (Decimal(f.amount) - expected).quantize(Decimal('0.01'))
            reconciliation.append({
                'filing_id': f.id, 'code': f.rule.code, 'name': f.rule.name,
                'period_start': f.period_start, 'period_end': f.period_end,
                'payroll_run': f.payroll_run_id, 'recorded_amount': f.amount,
                'expected_amount': expected.quantize(Decimal('0.01')), 'variance': variance,
                'status': 'matched' if abs(variance) <= tolerance else 'mismatch',
            })
        packs = StatutoryCompliancePack.objects.filter(company=company).order_by('-period_end')[:12]
        return Response({
            'configured': True, 'country': profile.country_code, 'today': today, 'window_days': window,
            'summary': {
                'total_filings': qs.count(), 'open_filings': open_qs.count(),
                'overdue_filings': overdue.count(), 'filed_filings': filed.count(),
                'open_amount': total_open.quantize(Decimal('0.01')),
                'overdue_amount': total_overdue.quantize(Decimal('0.01')),
                'next_window_amount': next_due.quantize(Decimal('0.01')),
                'reconciled': sum(1 for x in reconciliation if x['status']=='matched'),
                'mismatches': sum(1 for x in reconciliation if x['status']=='mismatch'),
            },
            'upcoming': StatutoryFilingSerializer(upcoming[:50], many=True).data,
            'reconciliation': reconciliation[:100],
            'packs': StatutoryCompliancePackSerializer(packs, many=True).data,
        })


def filing_calendar_availability(country_code):
    """Why the filing calendar is empty, if it is - and whether a remedy exists.

    An empty calendar is the same shape as a paid-off one, so the frontend used
    to say "run the filing-rule seed command", which is only true for a country
    whose rules exist but were never seeded. For a country HRCloudPay has no
    verified filing deadlines for, running that command changes nothing, and
    telling the user to run it every week is how a missing compliance calendar
    becomes a permanent background condition nobody reads.

    Distinguishing the two cases is the difference between "your setup is
    incomplete" and "we do not know your country's deadlines yet". They need
    different words and only one of them is fixable by the operator.

    `calendar_status` values:
      ``unconfigured`` - no country profile set
      ``unverified``   - a supported country, but no filing rule has been
                         verified for it. Not the operator's to fix.
      ``none_due``     - rules exist, none fall in the requested window
    """
    from .countries.registry import COUNTRY_PACKS
    code = (country_code or '').upper()
    if code not in COUNTRY_PACKS:
        # Not a country we claim to cover, so the absence is not a gap we own.
        return 'unverified'
    if StatutoryFilingRule.objects.filter(country_code=code).exists():
        return 'none_due'
    return 'unverified'


class FilingCalendarView(APIView):
    """Country-aware upcoming statutory deadlines for the signed-in company."""
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]

    def get(self, request):
        company = request.user.company
        profile = CompanyCountryProfile.objects.filter(company=company).first()
        if not profile:
            return Response({'configured': False, 'filings': []})
        today = timezone.localdate()
        try:
            days = min(max(int(request.query_params.get('days', 90)), 1), 366)
        except (TypeError, ValueError):
            days = 90
        cutoff = today.fromordinal(today.toordinal() + days)
        rows = []
        rules = StatutoryFilingRule.objects.filter(country_code=profile.country_code, is_active=True, effective_from__lte=today).filter(
            models_q_end(today)
        ).order_by('code', '-effective_from')
        for rule in get_effective_rules(rules):
            due = due_date_for_rule(rule, today)
            if due <= cutoff:
                rows.append({
                    'rule_code': rule.code, 'name': rule.name, 'authority': rule.authority,
                    'filing_type': rule.filing_type, 'frequency': rule.frequency,
                    'due_date': due, 'source_reference': rule.source_reference,
                    'notes': rule.notes,
                })
        rows.sort(key=lambda x: x['due_date'])
        from .countries.registry import COUNTRY_PACKS
        pack = COUNTRY_PACKS.get(profile.country_code)
        return Response({
            'configured': True, 'country': profile.country_code, 'today': today,
            # Name and window come from the backend so the frontend renders the
            # country's own name rather than a second copy of the country list,
            # and so the message can quote the window actually queried.
            'country_name': pack.name if pack else profile.country_code,
            # The language facts, so the compliance view can state that this
            # country's filings are not in English instead of leaving a
            # French- or Arabic-speaking employer to assume they are. Sourced
            # from the pack rather than hardcoded per country in the frontend.
            'official_languages': list(pack.official_languages) if pack else [],
            'localized_name': pack.localized_name if pack else '',
            'days': days,
            'filings': rows,
            'calendar_status': 'none_due' if rows else filing_calendar_availability(
                profile.country_code),
        })


class FilingGenerateView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive, CanManageStatutory]

    def post(self, request):
        user = request.user
        company = user.company
        profile = CompanyCountryProfile.objects.filter(company=company).first()
        if not profile:
            return Response({'detail': 'Company country profile is not configured.'}, status=400)
        try:
            period_end = date.fromisoformat(str(request.data.get('period_end')))
            period_start = date.fromisoformat(str(request.data.get('period_start')))
        except (TypeError, ValueError):
            return Response({'detail': 'period_start and period_end are required as YYYY-MM-DD.'}, status=400)
        if period_start > period_end:
            return Response({'detail': 'period_start cannot be after period_end.'}, status=400)
        rules = StatutoryFilingRule.objects.filter(country_code=profile.country_code, is_active=True, effective_from__lte=period_end).filter(models_q_end(period_end)).order_by('code', '-effective_from')
        effective_rules = get_effective_rules(rules)
        payroll_run = company.payroll_runs.filter(period_start=period_start, period_end=period_end).prefetch_related('payslips').first()
        payroll_aggregate = {}
        payroll_paye_total = Decimal('0')
        if payroll_run:
            payroll_aggregate = {line['code']: line for line in aggregate_payroll_for_filing(payroll_run)}
            payroll_paye_total = sum((p.tax_amount for p in payroll_run.payslips.all()), Decimal('0'))
        created = []
        with transaction.atomic():
            for rule in effective_rules:
                if rule.frequency == 'annual' and period_end.month != 12:
                    continue
                if StatutoryFiling.objects.filter(company=company, rule=rule, period_start=period_start, period_end=period_end).exists():
                    continue
                due = due_date_for_rule(rule, period_end)
                amount = Decimal('0')
                if payroll_run:
                    if rule.code == 'paye':
                        amount = payroll_paye_total
                    else:
                        line = payroll_aggregate.get(rule.code)
                        if line:
                            amount = Decimal(line['employee_share']) + Decimal(line['employer_share'])
                obj = StatutoryFiling.objects.create(
                    company=company, rule=rule, payroll_run=payroll_run,
                    period_start=period_start, period_end=period_end, due_date=due,
                    amount=amount, status=filing_status(due),
                )
                created.append(obj)
        for obj in created:
            audit(user, 'create', f'Generated statutory filing {obj.rule.code}', company, 'statutory_filing', obj.id, {'period_end': str(obj.period_end), 'due_date': str(obj.due_date)}, request=request)
        return Response(StatutoryFilingSerializer(created, many=True).data, status=status.HTTP_201_CREATED)


class FilingListView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]

    def get(self, request):
        qs = StatutoryFiling.objects.filter(company=request.user.company).select_related('rule', 'payroll_run').prefetch_related('payroll_run__payslips').order_by('due_date', 'rule__code')[:200]
        return Response(StatutoryFilingSerializer(qs, many=True).data)


class FilingBulkReviewView(APIView):
    """Review multiple open filings atomically (AI-assisted triage)."""
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive, CanManageStatutory]

    def post(self, request):
        ids = request.data.get('ids') or []
        if not isinstance(ids, list) or not ids:
            return Response({'detail': 'Provide a non-empty ids list.'}, status=400)
        try:
            ids = [int(x) for x in ids[:100]]
        except (TypeError, ValueError):
            return Response({'detail': 'ids must be integers.'}, status=400)
        notes = str(request.data.get('notes', 'Bulk review from AI insights'))
        reviewed, skipped = 0, []
        with transaction.atomic():
            rows = list(
                StatutoryFiling.objects.select_for_update()
                .filter(id__in=ids, company=request.user.company)
                .select_related('company')
            )
            found = {r.id for r in rows}
            for fid in ids:
                if fid not in found:
                    skipped.append({'id': fid, 'reason': 'not found'})
            for filing in rows:
                if filing.status in TERMINAL_FILING_STATUSES or filing.approved_at:
                    skipped.append({'id': filing.id, 'reason': f'status {filing.status}'})
                    continue
                if filing.status == 'reviewed':
                    skipped.append({'id': filing.id, 'reason': 'already reviewed'})
                    continue
                filing.status = 'reviewed'
                filing.reviewed_at = timezone.now()
                filing.reviewed_by = request.user
                if notes:
                    filing.notes = notes
                filing.save(update_fields=['status', 'reviewed_at', 'reviewed_by', 'notes', 'updated_at'])
                reviewed += 1
        if reviewed:
            audit(request.user, 'update', f'Bulk reviewed {reviewed} statutory filings', request.user.company, 'statutory_filing', '', {'reviewed': reviewed}, request=request)
        return Response({'reviewed': reviewed, 'skipped': skipped})


class FilingMarkFiledView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]

    def post(self, request, pk):
        # Kept temporarily so old clients get an actionable error rather than
        # silently bypassing the review, approval, payment and submission flow.
        return Response(
            {'detail': 'This endpoint is retired. Use review, approve, payment and submit in order.'},
            status=status.HTTP_410_GONE,
        )


class FilingExportView(APIView):
    """Generic reviewable CSV export; exact authority upload formats remain country-specific work."""
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]

    def get(self, request, pk):
        filing = StatutoryFiling.objects.filter(pk=pk, company=request.user.company).select_related('rule', 'payroll_run').first()
        if not filing:
            return Response({'detail': 'Filing not found.'}, status=404)
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filing.rule.code}-{filing.period_end}.csv"'
        writer = csv.writer(response)
        writer.writerow(['country','authority','filing_code','period_start','period_end','due_date','employee_code','employee_name','tax_id','gross_salary','paye','employee_contribution','employer_contribution'])
        if filing.payroll_run_id:
            for payslip in filing.payroll_run.payslips.select_related('employee', 'employee__statutory_profile').all():
                employee = payslip.employee
                identifiers = getattr(getattr(employee, 'statutory_profile', None), 'identifiers', {}) or {}
                tax_id = identifiers.get('tin') or identifiers.get('tax_id') or ''
                employee_contribution = Decimal('0')
                employer_contribution = Decimal('0')
                for line in (payslip.breakdown or {}).get('statutory_contributions', []):
                    if (line.get('code') or line.get('name')) == filing.rule.code:
                        employee_contribution = Decimal(str(line.get('employee_share', '0')))
                        employer_contribution = Decimal(str(line.get('employer_share', '0')))
                paye = payslip.tax_amount if filing.rule.code == 'paye' else Decimal('0')
                writer.writerow([
                    filing.rule.country_code, filing.rule.authority, filing.rule.code,
                    filing.period_start, filing.period_end, filing.due_date,
                    employee.employee_code, employee.full_name, tax_id,
                    payslip.gross_salary, paye, employee_contribution, employer_contribution,
                ])
        return response


class CompliancePackListView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]

    def get(self, request):
        qs = StatutoryCompliancePack.objects.filter(company=request.user.company).select_related('payroll_run').order_by('-period_end')
        return Response(StatutoryCompliancePackSerializer(qs, many=True).data)


class CompliancePackGenerateView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive, CanManageStatutory]

    def post(self, request, run_id):
        run = request.user.company.payroll_runs.filter(id=run_id).first()
        if not run:
            return Response({'detail': 'Payroll run not found.'}, status=404)
        if run.status not in ('approved', 'paid'):
            return Response({'detail': 'Compliance packs can only be prepared for approved or paid payroll runs.'}, status=400)
        pack = create_compliance_pack(run, request.user)
        if not pack:
            return Response({'detail': 'Configure the company country experience first.'}, status=400)
        audit(request.user, 'create', f'Prepared statutory compliance pack for payroll {run.period_start} to {run.period_end}', run.company, 'statutory_compliance_pack', pack.id, {'filing_count': pack.filing_count, 'report_count': pack.report_count}, request=request)
        return Response(StatutoryCompliancePackSerializer(pack).data, status=201)


class CompliancePackExportView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]

    def get(self, request, pk):
        pack = StatutoryCompliancePack.objects.filter(pk=pk, company=request.user.company).select_related('payroll_run').first()
        if not pack:
            return Response({'detail': 'Compliance pack not found.'}, status=404)
        data = build_compliance_pack_zip(pack)
        response = HttpResponse(data, content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="hrcloudpay-compliance-pack-{pack.country_code}-{pack.period_end}.zip"'
        return response


class CompliancePackSubmitView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive, CanManageStatutory]

    def post(self, request, pk):
        with transaction.atomic():
            pack = StatutoryCompliancePack.objects.select_for_update().filter(pk=pk, company=request.user.company).first()
            if not pack:
                return Response({'detail': 'Compliance pack not found.'}, status=404)
            if pack.status not in ('ready', 'submitted'):
                return Response({'detail': 'Only a ready compliance pack can be submitted.'}, status=400)
            pack.status = 'submitted'
            pack.submitted_at = timezone.now()
            pack.notes = str(request.data.get('notes', pack.notes or ''))
            pack.save(update_fields=['status', 'submitted_at', 'notes', 'updated_at'])
        audit(request.user, 'update', f'Marked statutory compliance pack {pack.id} as submitted', pack.company, 'statutory_compliance_pack', pack.id, {'notes': pack.notes}, request=request)
        return Response(StatutoryCompliancePackSerializer(pack).data)


class FilingWorkflowBaseView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive, CanManageStatutory]

    def get_filing_locked(self, request, pk):
        """Fetch the filing under a row lock, so two reviewers cannot both win.

        ``of=('self',)`` names the one table to lock. Without it Django emits a
        bare ``FOR UPDATE``, which spans every table the query joins - and
        ``payroll_run`` is nullable, so ``select_related`` makes it a LEFT OUTER
        JOIN. Postgres refuses exactly that:

            FOR UPDATE cannot be applied to the nullable side of an outer join

        which made every filing transition (review, approve, pay, submit, close)
        a 500 on Postgres while passing on SQLite, where FOR UPDATE does not
        exist. Locking only the filing row keeps the join - and the eager load
        that avoids an N+1 - and drops the lock on tables nothing here mutates.

        SQLite has no FOR UPDATE and Django rejects ``of=`` on backends without
        it, so the clause is omitted rather than raising on a zero-config local
        run.
        """
        queryset = StatutoryFiling.objects.select_related('company', 'rule', 'payroll_run')
        if connection.features.has_select_for_update_of:
            queryset = queryset.select_for_update(of=('self',))
        return queryset.filter(pk=pk, company=request.user.company).first()

    def get_filing(self, request, pk):
        return StatutoryFiling.objects.select_related('company', 'rule', 'payroll_run').filter(pk=pk, company=request.user.company).first()


class FilingReviewView(FilingWorkflowBaseView):
    def post(self, request, pk):
        with transaction.atomic():
            filing = self.get_filing_locked(request, pk)
            if not filing:
                return Response({'detail': 'Filing not found.'}, status=404)
            if filing.status in TERMINAL_FILING_STATUSES or filing.approved_at:
                return Response({'detail': 'A filing cannot be reviewed after approval or submission.'}, status=400)
            filing.status = 'reviewed'
            filing.reviewed_at = timezone.now()
            filing.reviewed_by = request.user
            filing.notes = str(request.data.get('notes', filing.notes or ''))
            filing.save(update_fields=['status', 'reviewed_at', 'reviewed_by', 'notes', 'updated_at'])
        audit(request.user, 'update', f'Reviewed statutory filing {filing.id}', filing.company, 'statutory_filing', filing.id, {'status': 'reviewed', 'notes': filing.notes}, request=request)
        return Response(StatutoryFilingSerializer(filing).data)


class FilingApproveView(FilingWorkflowBaseView):
    def post(self, request, pk):
        with transaction.atomic():
            filing = self.get_filing_locked(request, pk)
            if not filing:
                return Response({'detail': 'Filing not found.'}, status=404)
            if filing.status != 'reviewed' or not filing.reviewed_at:
                return Response({'detail': 'Review the filing before approval.'}, status=400)
            if filing.approved_at:
                return Response({'detail': 'This filing has already been approved.'}, status=400)
            filing.status = 'approved'
            filing.approved_at = timezone.now()
            filing.approved_by = request.user
            filing.save(update_fields=['status', 'approved_at', 'approved_by', 'updated_at'])
        audit(request.user, 'update', f'Approved statutory filing {filing.id}', filing.company, 'statutory_filing', filing.id, {'amount': str(filing.amount)}, request=request)
        return Response(StatutoryFilingSerializer(filing).data)


class FilingPaymentView(FilingWorkflowBaseView):
    def post(self, request, pk):
        try:
            amount = Decimal(str(request.data.get('amount', '')))
        except (TypeError, ValueError, ArithmeticError):
            return Response({'detail': 'Invalid payment amount.'}, status=400)
        if amount <= 0:
            return Response({'detail': 'Payment amount must be greater than zero.'}, status=400)
        method = str(request.data.get('method', '')).strip()
        transaction_reference = str(request.data.get('transaction_reference', '')).strip()
        if not method or not transaction_reference:
            return Response({'detail': 'Payment method and transaction reference are required.'}, status=400)
        payment_date = request.data.get('payment_date') or timezone.localdate()
        if isinstance(payment_date, str):
            try:
                payment_date = date.fromisoformat(payment_date)
            except ValueError:
                return Response({'detail': 'payment_date must be YYYY-MM-DD.'}, status=400)
        with transaction.atomic():
            filing = self.get_filing_locked(request, pk)
            if not filing:
                return Response({'detail': 'Filing not found.'}, status=404)
            if filing.status != 'approved' or not filing.approved_at:
                return Response({'detail': 'Approve the filing before recording payment.'}, status=400)
            if amount != filing.amount:
                return Response({'detail': 'Payment amount must match the statutory obligation amount.'}, status=400)
            if StatutoryFilingPayment.objects.filter(filing=filing, status='paid').exists():
                return Response({'detail': 'A successful payment record already exists and cannot be overwritten.'}, status=400)
            payment = StatutoryFilingPayment.objects.create(
                filing=filing,
                amount=amount,
                payment_date=payment_date,
                method=method,
                transaction_reference=transaction_reference,
                status='paid',
                receipt_reference=str(request.data.get('receipt_reference', '')).strip(),
                notes=str(request.data.get('notes', '')),
                recorded_by=request.user,
            )
            filing.status = 'paid'
            filing.save(update_fields=['status', 'updated_at'])
        audit(request.user, 'update', f'Recorded payment for statutory filing {filing.id}', filing.company, 'statutory_filing', filing.id, {'amount': str(amount), 'transaction_reference': payment.transaction_reference}, request=request)
        return Response(StatutoryFilingPaymentSerializer(payment).data)


class FilingSubmitView(FilingWorkflowBaseView):
    def post(self, request, pk):
        reference = str(request.data.get('submission_reference', '')).strip()
        if not reference:
            return Response({'detail': 'Submission reference is required.'}, status=400)
        with transaction.atomic():
            filing = self.get_filing_locked(request, pk)
            if not filing:
                return Response({'detail': 'Filing not found.'}, status=404)
            if filing.status != 'paid' or not filing.approved_at:
                return Response({'detail': 'Approve and pay the filing before submission.'}, status=400)
            payment = StatutoryFilingPayment.objects.filter(filing=filing, status='paid').first()
            if not payment:
                return Response({'detail': 'Record a successful payment before submission.'}, status=400)
            filing.status = 'submitted'
            filing.submitted_at = timezone.now()
            filing.submitted_by = request.user
            filing.submission_reference = reference
            filing.reference = reference
            filing.filed_at = filing.submitted_at
            filing.save(update_fields=['status', 'submitted_at', 'submitted_by', 'submission_reference', 'reference', 'filed_at', 'updated_at'])
        audit(request.user, 'update', f'Submitted statutory filing {filing.id}', filing.company, 'statutory_filing', filing.id, {'submission_reference': reference}, request=request)
        return Response(StatutoryFilingSerializer(filing).data)


class FilingCloseView(FilingWorkflowBaseView):
    def post(self, request, pk):
        with transaction.atomic():
            filing = self.get_filing_locked(request, pk)
            if not filing:
                return Response({'detail': 'Filing not found.'}, status=404)
            if filing.status not in ('submitted', 'filed') or not filing.filed_at:
                return Response({'detail': 'Only submitted filings can be closed.'}, status=400)
            filing.status = 'closed'
            filing.closed_at = timezone.now()
            note = str(request.data.get('notes', '')).strip()
            if note:
                filing.notes = f'{filing.notes}\nClosed: {note}'.strip()
            filing.save(update_fields=['status', 'closed_at', 'notes', 'updated_at'])
        audit(request.user, 'update', f'Closed statutory filing {filing.id}', filing.company, 'statutory_filing', filing.id, {'closed': True}, request=request)
        return Response(StatutoryFilingSerializer(filing).data)
