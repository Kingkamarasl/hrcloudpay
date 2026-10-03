import csv
from decimal import Decimal

from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework import serializers
from rest_framework.views import APIView

from accounts.permissions import CanManagePayroll, IsCompanyActive, IsCompanyMember
from accounts.audit import audit
from security.step_up import RequiresFreshMfa
from employees.models import Employee

from .models import PayrollConfig, PayrollRun, Payslip
from .serializers import PayrollConfigSerializer, PayrollRunSerializer, PayslipSerializer
from .services import calculate_payslip, collect_compliance_gaps
from .pdf import build_payslip_pdf


def _acknowledges_gaps(data):
    """True when the caller explicitly signed off on the compliance gaps.

    Deliberately strict. An acknowledgement is a record that a human accepted
    an unverified tax result, so it must be spelled out rather than inferred
    from a body that merely happens to be present - a stray `true` somewhere
    should not buy permission to approve a payroll that under-withheld tax.
    """
    if not data or not hasattr(data, 'get'):
        return False
    value = data.get('acknowledge_compliance_gaps')
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(value)


class PayrollConfigView(APIView):
    """
    GET returns the company's current payroll config (or 404 if the
    onboarding form hasn't been submitted yet). POST/PUT submits the
    onboarding form (currency, pay frequency, tax brackets, contributions).
    Only requires the company to be active, not payroll_configured yet,
    since this IS the endpoint that sets payroll_configured=True.
    """
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManagePayroll]

    def get(self, request):
        config = PayrollConfig.objects.filter(company=request.user.company).first()
        if not config:
            return Response({'detail': 'Payroll not configured yet.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(PayrollConfigSerializer(config).data)

    def post(self, request):
        serializer = PayrollConfigSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        config = serializer.save()
        audit(request.user, 'update', 'Updated payroll configuration', request.user.company, 'payroll_config', config.id, {'currency': config.currency, 'pay_frequency': config.pay_frequency}, request=request)
        return Response(PayrollConfigSerializer(config).data, status=status.HTTP_201_CREATED)

    def put(self, request):
        return self.post(request)


class PayrollRunViewSet(viewsets.ModelViewSet):
    serializer_class = PayrollRunSerializer
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManagePayroll]

    def get_queryset(self):
        return PayrollRun.objects.filter(company=self.request.user.company)

    def perform_create(self, serializer):
        try:
            run = serializer.save(company=self.request.user.company)
            audit(self.request.user, 'create', f'Created payroll run {run.period_start} to {run.period_end}', run.company, 'payroll_run', run.id, request=self.request)
        except IntegrityError:
            # The database constraint is the final protection against a
            # duplicate period when concurrent requests race each other.
            raise serializers.ValidationError(
                {'detail': 'A payroll run already exists for this exact period.'}
            )


class ProcessPayrollRunView(APIView):
    """
    Runs the payroll calculation engine for every active employee in
    the company and generates a Payslip per employee for this run.
    Requires the company to have completed payroll onboarding first.
    """
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManagePayroll]

    def post(self, request, run_id):
        company = request.user.company
        with transaction.atomic():
            payroll_run = get_object_or_404(
                PayrollRun.objects.select_for_update(), id=run_id, company=company
            )

            config = PayrollConfig.objects.filter(company=company).first()
            if not config:
                return Response(
                    {'detail': 'Complete payroll setup before running payroll.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if payroll_run.status != 'draft':
                return Response({'detail': 'This payroll run has already been processed.'}, status=400)

            employees = Employee.objects.filter(company=company, employment_status='active')
            from .models import OvertimeEntry, SalaryAdvance, AdvanceRecovery
            for employee in employees:
                result = calculate_payslip(employee, config, payroll_run=payroll_run)
                breakdown = result.get('breakdown') or {}
                advance_plan = breakdown.pop('_advance_plan', [])
                ot_ids = breakdown.pop('_overtime_entry_ids', [])
                encash_ids = breakdown.pop('_encashment_ids', [])
                result['breakdown'] = breakdown
                payslip = Payslip.objects.create(payroll_run=payroll_run, employee=employee, **result)
                for adv_id, take in advance_plan:
                    adv = SalaryAdvance.objects.select_for_update().get(id=adv_id, employee=employee)
                    adv.remaining = adv.remaining - take
                    if adv.remaining <= 0:
                        adv.remaining = 0
                        adv.status = 'cleared'
                    else:
                        adv.status = 'partial'
                    adv.save(update_fields=['remaining', 'status'])
                    AdvanceRecovery.objects.create(advance=adv, payslip=payslip, amount=take)
                if ot_ids:
                    OvertimeEntry.objects.filter(id__in=ot_ids, employee=employee).update(payroll_run=payroll_run)
                if encash_ids:
                    from leave.models import LeaveEncashment
                    LeaveEncashment.objects.filter(id__in=encash_ids, employee=employee).update(status='paid')

            payroll_run.status = 'processed'
            payroll_run.save(update_fields=['status'])

        audit(request.user, 'payroll_process', f'Processed payroll {payroll_run.period_start} to {payroll_run.period_end}', company, 'payroll_run', payroll_run.id, {'employee_count': employees.count()}, request=request)
        return Response(PayrollRunSerializer(payroll_run).data)


class ApprovePayrollRunView(APIView):
    # Approving a run commits real money, so a live session alone is not
    # enough: require MFA re-confirmed within the step-up window.
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManagePayroll, RequiresFreshMfa]

    def post(self, request, run_id):
        with transaction.atomic():
            run = get_object_or_404(PayrollRun.objects.select_for_update(), id=run_id, company=request.user.company)
            if run.status != 'processed':
                return Response({'detail': 'Only processed payroll runs can be approved.'}, status=400)
            # Approving is the point of no return, so it is where an unverified
            # country tax result has to stop. The run is still calculable - a
            # payroll that refuses to produce numbers helps nobody - but a
            # human has to sign off on the fact that statutory tax could not be
            # applied, and that signature is what lands in the audit log.
            gaps = collect_compliance_gaps(run)
            acknowledged = _acknowledges_gaps(request.data)
            if gaps and not acknowledged:
                return Response({
                    'detail': (
                        'This payroll contains statutory compliance gaps that must be '
                        'acknowledged before approval. Resend with '
                        'acknowledge_compliance_gaps=true to proceed.'
                    ),
                    'code': 'compliance_gaps_unacknowledged',
                    'compliance_gaps': gaps,
                }, status=409)
            run.status = 'approved'
            run.approved_at = timezone.now()
            run.approved_by = request.user
            run.save(update_fields=['status', 'approved_at', 'approved_by'])
            try:
                from regional.compliance import create_compliance_pack
                create_compliance_pack(run, request.user)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning('Compliance pack creation failed for payroll run %s: %s', run.id, e)
        audit(
            request.user, 'payroll_approve',
            f'Approved payroll {run.period_start} to {run.period_end}',
            run.company, 'payroll_run', run.id,
            {'compliance_gaps_acknowledged': gaps} if acknowledged else None,
            request=request,
        )
        return Response(PayrollRunSerializer(run).data)


class PayPayrollRunView(APIView):
    # Recording payment is irreversible from the app's point of view.
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManagePayroll, RequiresFreshMfa]

    def post(self, request, run_id):
        with transaction.atomic():
            run = get_object_or_404(PayrollRun.objects.select_for_update(), id=run_id, company=request.user.company)
            if run.status != 'approved':
                return Response({'detail': 'Approve the payroll run before recording payment.'}, status=400)
            method = request.data.get('payment_method', '').strip()
            reference = request.data.get('payment_reference', '').strip()
            if not method or not reference:
                return Response({'detail': 'Payment method and reference are required.'}, status=400)
            run.status = 'paid'
            run.save(update_fields=['status'])
            run.payslips.update(payment_method=method, payment_reference=reference, paid_at=timezone.now())
            try:
                from regional.compliance import create_compliance_pack
                create_compliance_pack(run, request.user)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning('Compliance pack refresh after payroll payment failed for run %s: %s', run.id, exc)
        audit(request.user, 'payroll_payment', f'Recorded payment for payroll {run.period_start} to {run.period_end}', run.company, 'payroll_run', run.id, {'payment_method': method, 'payment_reference': reference}, request=request)
        return Response(PayrollRunSerializer(run).data)


class PayrollExportView(APIView):
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManagePayroll]

    def get(self, request):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="hrcloudpay-payroll.csv"'
        writer = csv.writer(response)
        writer.writerow(['Period start', 'Period end', 'Status', 'Employee', 'Gross', 'Tax', 'Contributions', 'Deductions', 'Net', 'Payment reference'])
        runs = PayrollRun.objects.filter(company=request.user.company).prefetch_related('payslips__employee')
        for run in runs:
            for payslip in run.payslips.all():
                writer.writerow([run.period_start, run.period_end, run.status, payslip.employee.full_name, payslip.gross_salary, payslip.tax_amount, payslip.total_contributions, payslip.total_other_deductions, payslip.net_salary, payslip.payment_reference])
        return response


class PayrollSummaryView(APIView):
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManagePayroll]

    def get(self, request):
        payslips = Payslip.objects.filter(payroll_run__company=request.user.company)
        totals = payslips.aggregate(
            gross=Sum('gross_salary'),
            tax=Sum('tax_amount'),
            contributions=Sum('total_contributions'),
            deductions=Sum('total_other_deductions'),
            net=Sum('net_salary'),
        )
        return Response({key: f"{(value or Decimal('0.00')):.2f}" for key, value in totals.items()})


class PayrollDashboardView(APIView):
    """
    Aggregated payroll data shaped for the visual dashboard: amount by
    employee, amount by pay date, gross wages trend, pay statement
    breakdown by department, payroll funding (employer cost) by run,
    and a table of recent payroll runs.
    """
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManagePayroll]

    def get(self, request):
        company = request.user.company
        runs = list(
            PayrollRun.objects.filter(company=company)
            .exclude(status='draft')
            .order_by('period_end')
            .prefetch_related('payslips__employee')
        )
        latest_run = runs[-1] if runs else None

        amount_by_employee = []
        pay_statement_by_department = {}
        if latest_run:
            for slip in latest_run.payslips.all():
                amount_by_employee.append({
                    'employee': slip.employee.full_name,
                    'amount': float(slip.net_salary),
                })
                dept = slip.employee.department or 'Unassigned'
                pay_statement_by_department[dept] = (
                    pay_statement_by_department.get(dept, 0) + float(slip.gross_salary)
                )

        amount_by_pay_date = []
        gross_wages_by_pay_date = []
        payroll_funding = []
        for run in runs:
            slips = list(run.payslips.all())
            total_net = sum(float(s.net_salary) for s in slips)
            total_gross = sum(float(s.gross_salary) for s in slips)
            employer_cost = total_gross
            for slip in slips:
                for item in slip.breakdown.get('statutory_contributions', []):
                    employer_cost += float(item.get('employer_share', 0))

            label = run.period_end.isoformat()
            amount_by_pay_date.append({'pay_date': label, 'amount': total_net})
            gross_wages_by_pay_date.append({'pay_date': label, 'amount': total_gross})
            payroll_funding.append({'pay_date': label, 'amount': employer_cost})

        recent_runs = [
            {
                'id': run.id,
                'period_start': run.period_start,
                'period_end': run.period_end,
                'status': run.status,
                'employee_count': run.payslips.count(),
                'total_net': sum(float(s.net_salary) for s in run.payslips.all()),
            }
            for run in reversed(runs[-5:])
        ]

        return Response({
            'amount_by_employee': amount_by_employee,
            'amount_by_pay_date': amount_by_pay_date,
            'gross_wages_by_pay_date': gross_wages_by_pay_date,
            'pay_statement_by_department': [
                {'department': k, 'amount': v} for k, v in pay_statement_by_department.items()
            ],
            'payroll_funding': payroll_funding,
            'recent_runs': recent_runs,
        })


class PayslipViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PayslipSerializer
    permission_classes = [IsCompanyMember, IsCompanyActive]

    def get_queryset(self):
        qs = Payslip.objects.filter(payroll_run__company=self.request.user.company)
        # Employee-role users (self-service portal) only ever see their own payslips
        if self.request.user.role == 'employee' and hasattr(self.request.user, 'employee_profile'):
            qs = qs.filter(employee=self.request.user.employee_profile)
        return qs

    def retrieve(self, request, *args, **kwargs):
        payslip = self.get_object()
        if request.query_params.get('download') == 'pdf':
            copy = (request.query_params.get('copy') or 'employee').lower()
            label = 'COMPANY COPY' if copy == 'company' else 'EMPLOYEE COPY'
            response = HttpResponse(
                build_payslip_pdf(payslip, copy_label=label),
                content_type='application/pdf',
            )
            response['Content-Disposition'] = f'attachment; filename="payslip-{payslip.id}-{copy}.pdf"'
            return response
        return super().retrieve(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# Extended payroll features: email, bank file, compare, OT, advances
# ---------------------------------------------------------------------------

def _feature_or_403(key, company=None):
    from accounts.features import require_feature
    return require_feature(key, company=company)

from django.core.mail import EmailMessage
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from .models import OvertimeRule, OvertimeEntry, SalaryAdvance
from .pdf import build_payslip_pdf
from .serializers import PayslipSerializer
from decimal import Decimal


class EmailPayslipsView(APIView):
    """Email payslip PDFs to employees for a payroll run."""
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManagePayroll]

    def post(self, request, run_id):
        ok, resp = _feature_or_403('payroll_email_payslips', request.user.company)
        if not ok:
            return resp
        run = get_object_or_404(PayrollRun, id=run_id, company=request.user.company)
        if run.status not in ('processed', 'approved', 'paid'):
            return Response({'detail': 'Process the run before emailing payslips.'}, status=400)
        sent, failed = 0, []
        for slip in run.payslips.select_related('employee').all():
            email = (slip.employee.email or '').strip()
            if not email:
                failed.append({'employee': slip.employee.full_name, 'reason': 'No email'})
                continue
            try:
                pdf = build_payslip_pdf(slip, copy_label='EMPLOYEE COPY')
                msg = EmailMessage(
                    subject=f'Payslip {run.period_start} â€“ {run.period_end} Â· {request.user.company.name}',
                    body=(
                        f'Dear {slip.employee.full_name},\n\n'
                        f'Please find attached your payslip for {run.period_start} to {run.period_end}.\n\n'
                        f'Net pay: {slip.net_salary}\n\n'
                        f'â€” {request.user.company.name} via HRCloudPay'
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[email],
                )
                msg.attach(f'payslip-{slip.id}.pdf', pdf, 'application/pdf')
                msg.send(fail_silently=False)
                sent += 1
            except Exception as e:
                failed.append({'employee': slip.employee.full_name, 'reason': str(e)})
        audit(request.user, 'payslip_email', f'Emailed payslips for run {run_id}', request.user.company, 'payroll_run', run_id, {'sent': sent}, request=request)
        return Response({'sent': sent, 'failed': failed})


class BankFileExportView(APIView):
    """CSV bank transfer file: employee, account, net pay."""
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManagePayroll]

    def get(self, request, run_id):
        ok, resp = _feature_or_403('payroll_bank_file', request.user.company)
        if not ok:
            return resp
        import csv
        from io import StringIO
        run = get_object_or_404(PayrollRun, id=run_id, company=request.user.company)
        buf = StringIO()
        w = csv.writer(buf)
        w.writerow(['employee_code', 'employee_name', 'bank_account_number', 'amount', 'currency', 'reference', 'period_start', 'period_end'])
        currency = ''
        try:
            currency = run.company.payroll_config.currency
        except Exception:
            currency = 'USD'
        for slip in run.payslips.select_related('employee').all():
            e = slip.employee
            w.writerow([
                e.employee_code, e.full_name, e.bank_account_number or '',
                f'{slip.net_salary:.2f}', currency,
                f'PAY-{run.id}-{e.employee_code}', run.period_start, run.period_end,
            ])
        resp = HttpResponse(buf.getvalue(), content_type='text/csv')
        resp['Content-Disposition'] = f'attachment; filename="bank-transfer-run-{run.id}.csv"'
        return resp


class ComparePayrollRunsView(APIView):
    """Compare two payroll runs: totals and per-employee deltas."""
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManagePayroll]

    def get(self, request):
        ok, resp = _feature_or_403('payroll_compare_runs', request.user.company)
        if not ok:
            return resp
        a_id = request.query_params.get('run_a')
        b_id = request.query_params.get('run_b')
        # previous=1 with run_b (or run_a): compare to the prior run for this company
        if request.query_params.get('previous') and (a_id or b_id):
            try:
                current_id = int(b_id or a_id)
            except (TypeError, ValueError):
                return Response({'detail': 'Run id must be an integer.'}, status=400)
            current = get_object_or_404(PayrollRun, id=current_id, company=request.user.company)
            prev = (
                PayrollRun.objects.filter(company=request.user.company, period_end__lt=current.period_start)
                .order_by('-period_end')
                .first()
            )
            if not prev:
                return Response({'detail': 'No previous payroll run to compare against.'}, status=404)
            a_id, b_id = str(prev.id), str(current.id)
        if not a_id or not b_id:
            return Response({'detail': 'Provide run_a and run_b query params (or previous=1 with a run id).'}, status=400)
        company = request.user.company
        run_a = get_object_or_404(PayrollRun, id=a_id, company=company)
        run_b = get_object_or_404(PayrollRun, id=b_id, company=company)

        def totals(run):
            slips = list(run.payslips.all())
            return {
                'run_id': run.id,
                'period_start': str(run.period_start),
                'period_end': str(run.period_end),
                'status': run.status,
                'employee_count': len(slips),
                'gross': float(sum(s.gross_salary for s in slips)),
                'tax': float(sum(s.tax_amount for s in slips)),
                'net': float(sum(s.net_salary for s in slips)),
            }

        map_a = {s.employee_id: s for s in run_a.payslips.select_related('employee')}
        map_b = {s.employee_id: s for s in run_b.payslips.select_related('employee')}
        all_ids = set(map_a) | set(map_b)
        rows = []
        for eid in all_ids:
            sa, sb = map_a.get(eid), map_b.get(eid)
            name = (sa or sb).employee.full_name
            net_a = float(sa.net_salary) if sa else 0
            net_b = float(sb.net_salary) if sb else 0
            rows.append({
                'employee': name,
                'net_a': net_a,
                'net_b': net_b,
                'delta': round(net_b - net_a, 2),
            })
        rows.sort(key=lambda r: abs(r['delta']), reverse=True)
        return Response({'run_a': totals(run_a), 'run_b': totals(run_b), 'employees': rows})


class OvertimeRuleView(APIView):
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManagePayroll]

    def get(self, request):
        ok, resp = _feature_or_403('payroll_overtime', request.user.company)
        if not ok:
            return resp
        rule, _ = OvertimeRule.objects.get_or_create(company=request.user.company)
        return Response({
            'weekday_multiplier': str(rule.weekday_multiplier),
            'weekend_multiplier': str(rule.weekend_multiplier),
            'holiday_multiplier': str(rule.holiday_multiplier),
            'standard_hours_per_month': str(rule.standard_hours_per_month),
        })

    def put(self, request):
        ok, resp = _feature_or_403('payroll_overtime', request.user.company)
        if not ok:
            return resp
        rule, _ = OvertimeRule.objects.get_or_create(company=request.user.company)
        for field in ('weekday_multiplier', 'weekend_multiplier', 'holiday_multiplier', 'standard_hours_per_month'):
            if field in request.data:
                setattr(rule, field, Decimal(str(request.data[field])))
        rule.save()
        return self.get(request)


class OvertimeEntryListCreateView(APIView):
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManagePayroll]

    def get(self, request):
        ok, resp = _feature_or_403('payroll_overtime', request.user.company)
        if not ok:
            return resp
        qs = OvertimeEntry.objects.filter(company=request.user.company).select_related('employee')[:200]
        return Response([{
            'id': e.id, 'employee_id': e.employee_id, 'employee': e.employee.full_name,
            'work_date': str(e.work_date), 'hours': str(e.hours), 'day_type': e.day_type,
            'amount': str(e.amount), 'payroll_run_id': e.payroll_run_id, 'notes': e.notes,
        } for e in qs])

    def post(self, request):
        ok, resp = _feature_or_403('payroll_overtime', request.user.company)
        if not ok:
            return resp
        from employees.models import Employee
        company = request.user.company
        emp = get_object_or_404(Employee, id=request.data.get('employee_id'), company=company)
        rule, _ = OvertimeRule.objects.get_or_create(company=company)
        hours = Decimal(str(request.data.get('hours', 0)))
        if hours <= 0:
            return Response({'detail': 'Overtime hours must be greater than zero.'}, status=400)
        work_date = request.data.get('work_date')
        day_type = request.data.get('day_type') or ''
        if not day_type and work_date:
            from datetime import date as date_cls
            from .models import PublicHoliday
            try:
                d = work_date if hasattr(work_date, 'weekday') else date_cls.fromisoformat(str(work_date))
            except ValueError:
                return Response({'detail': 'work_date must be YYYY-MM-DD.'}, status=400)
            if PublicHoliday.objects.filter(company=company, date=d).exists():
                day_type = 'holiday'
            elif d.weekday() >= 5:
                day_type = 'weekend'
            else:
                day_type = 'weekday'
        day_type = day_type or 'weekday'
        mult = {
            'weekday': rule.weekday_multiplier,
            'weekend': rule.weekend_multiplier,
            'holiday': rule.holiday_multiplier,
        }.get(day_type, rule.weekday_multiplier)
        hourly = (emp.base_salary / rule.standard_hours_per_month) if rule.standard_hours_per_month else Decimal('0')
        amount = (hourly * hours * mult).quantize(Decimal('0.01'))
        entry = OvertimeEntry.objects.create(
            company=company, employee=emp,
            work_date=work_date,
            hours=hours, day_type=day_type, amount=amount,
            notes=request.data.get('notes', ''),
        )
        return Response({'id': entry.id, 'amount': str(entry.amount)}, status=201)


class SalaryAdvanceListCreateView(APIView):
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManagePayroll]

    def get(self, request):
        ok, resp = _feature_or_403('payroll_salary_advances', request.user.company)
        if not ok:
            return resp
        qs = SalaryAdvance.objects.filter(company=request.user.company).select_related('employee')[:200]
        return Response([{
            'id': a.id, 'employee': a.employee.full_name, 'employee_id': a.employee_id,
            'amount': str(a.amount), 'remaining': str(a.remaining),
            'installment_amount': str(a.installment_amount), 'status': a.status,
            'reason': a.reason, 'granted_on': str(a.granted_on),
        } for a in qs])

    def post(self, request):
        ok, resp = _feature_or_403('payroll_salary_advances', request.user.company)
        if not ok:
            return resp
        from employees.models import Employee
        company = request.user.company
        emp = get_object_or_404(Employee, id=request.data.get('employee_id'), company=company)
        amount = Decimal(str(request.data.get('amount', 0)))
        installment = Decimal(str(request.data.get('installment_amount') or amount))
        if amount <= 0 or installment <= 0:
            return Response({'detail': 'Advance amount and installment must be greater than zero.'}, status=400)
        adv = SalaryAdvance.objects.create(
            company=company, employee=emp, amount=amount, remaining=amount,
            installment_amount=installment, reason=request.data.get('reason', ''),
        )
        return Response({'id': adv.id, 'remaining': str(adv.remaining)}, status=201)


class PublicHolidayListCreateView(APIView):
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManagePayroll]

    def get(self, request):
        from .models import PublicHoliday
        qs = PublicHoliday.objects.filter(company=request.user.company).order_by('date')
        return Response([{'id': h.id, 'date': str(h.date), 'name': h.name} for h in qs])

    def post(self, request):
        ok, resp = _feature_or_403('payroll_overtime', request.user.company)
        if not ok:
            return resp
        from .models import PublicHoliday
        h = PublicHoliday.objects.create(
            company=request.user.company,
            date=request.data.get('date'),
            name=request.data.get('name', 'Public holiday'),
        )
        return Response({'id': h.id, 'date': str(h.date), 'name': h.name}, status=201)

    def delete(self, request):
        ok, resp = _feature_or_403('payroll_overtime', request.user.company)
        if not ok:
            return resp
        from .models import PublicHoliday
        hid = request.data.get('id') or request.query_params.get('id')
        PublicHoliday.objects.filter(id=hid, company=request.user.company).delete()
        return Response(status=204)
