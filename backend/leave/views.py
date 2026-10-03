from decimal import Decimal
from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from django.shortcuts import get_object_or_404
from accounts.permissions import CanApproveForDepartment, CanManageHR, CanManageHROrDepartment, IsCompanyActive, IsCompanyMember
from accounts.audit import audit
from employees.models import Employee
from .models import LeaveRequest, BreakRequest
from .serializers import LeaveRequestSerializer, BreakRequestSerializer
from .pdf import build_break_request_pdf, build_leave_request_pdf


class BaseRequestViewSet(viewsets.ModelViewSet):
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManageHROrDepartment]

    def scoped(self, qs):
        u = self.request.user
        if u.role == 'employee' and hasattr(u, 'employee_profile'):
            return qs.filter(employee=u.employee_profile)
        if u.role == 'department_manager':
            return qs.filter(employee__department=u.managed_department)
        return qs

    @staticmethod
    def _restore_leave_balance(obj):
        """Credit back the days previously deducted for an approved request."""
        from .models import LeaveBalance
        days = Decimal(str(obj.days_requested))
        bal, _ = LeaveBalance.objects.get_or_create(
            employee=obj.employee, leave_type=obj.leave_type, defaults={'balance_days': 0},
        )
        bal.balance_days = bal.balance_days + days
        bal.save(update_fields=['balance_days', 'updated_at'])

    @staticmethod
    def _conflict(obj, action, allowed_from):
        """Return a 409 Response unless obj.status is in allowed_from, else None."""
        from rest_framework import status as http_status
        if obj.status not in allowed_from:
            return Response(
                {
                    'detail': (
                        f'This request is already {obj.status} and cannot be {action}.'
                    ),
                    'code': 'invalid_status_transition',
                    'status': obj.status,
                },
                status=http_status.HTTP_409_CONFLICT,
            )
        return None

    @action(detail=True, methods=['post'], permission_classes=[IsCompanyMember, IsCompanyActive, CanApproveForDepartment])
    def approve(self, request, pk=None):
        obj = self.get_object()
        # Guard the transition: without this, approve is not idempotent and every
        # extra call deducts days_requested from the balance again.
        conflict = self._conflict(obj, 'approved', allowed_from=('pending',))
        if conflict:
            return conflict
        obj.status = 'approved'
        obj.reviewed_by = request.user
        obj.save(update_fields=['status', 'reviewed_by'])
        # Deduct from leave balance when approving LeaveRequest
        if isinstance(obj, LeaveRequest):
            from .models import LeaveBalance
            days = Decimal(str(obj.days_requested))
            if days <= 0:
                # LeaveRequestSerializer now rejects inverted date ranges, but rows
                # created before that fix can still compute a negative duration.
                # Deducting a negative amount would *credit* the balance.
                raise ValidationError({
                    'detail': f'Cannot approve: computed leave duration is {days} day(s).',
                })
            bal, _ = LeaveBalance.objects.get_or_create(
                employee=obj.employee, leave_type=obj.leave_type, defaults={'balance_days': 0},
            )
            bal.balance_days = bal.balance_days - days
            bal.save(update_fields=['balance_days', 'updated_at'])
        audit(
            request.user, 'leave_approve',
            f'Approved {obj.__class__.__name__} for {obj.employee.full_name}',
            obj.employee.company, obj.__class__.__name__.lower(), obj.id,
            {'status': 'approved'}, request=request,
        )
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=['post'], permission_classes=[IsCompanyMember, IsCompanyActive, CanApproveForDepartment])
    def reject(self, request, pk=None):
        obj = self.get_object()
        # Rejecting is allowed from 'pending' (no balance impact) and from
        # 'approved' (the days get credited back below).
        conflict = self._conflict(obj, 'rejected', allowed_from=('pending', 'approved'))
        if conflict:
            return conflict
        was_approved = obj.status == 'approved'
        obj.status = 'rejected'
        obj.reviewed_by = request.user
        obj.save(update_fields=['status', 'reviewed_by'])
        if was_approved and isinstance(obj, LeaveRequest):
            # Without this, approve -> reject leaves the days deducted forever.
            self._restore_leave_balance(obj)
        audit(
            request.user, 'leave_reject',
            f'Rejected {obj.__class__.__name__} for {obj.employee.full_name}',
            obj.employee.company, obj.__class__.__name__.lower(), obj.id,
            {'status': 'rejected'}, request=request,
        )
        return Response(self.get_serializer(obj).data)


class LeaveRequestViewSet(BaseRequestViewSet):
    serializer_class = LeaveRequestSerializer

    def get_queryset(self):
        return self.scoped(LeaveRequest.objects.filter(employee__company=self.request.user.company))

    def perform_create(self, serializer):
        from decimal import Decimal
        from .models import LeaveBalance, LeaveAccrualPolicy
        e = Employee.objects.get(id=serializer.validated_data['employee'].id, company=self.request.user.company)
        leave_type = serializer.validated_data.get('leave_type', 'annual')
        start = serializer.validated_data['start_date']
        end = serializer.validated_data['end_date']
        days = Decimal(str((end - start).days + 1))
        # Only enforce balance when accrual policy exists for this type
        if LeaveAccrualPolicy.objects.filter(company=e.company, leave_type=leave_type).exists():
            bal = LeaveBalance.objects.filter(employee=e, leave_type=leave_type).first()
            available = bal.balance_days if bal else Decimal('0')
            if available < days:
                raise ValidationError({
                    'detail': f'Insufficient {leave_type} leave balance ({available} days available, {days} requested).',
                    'code': 'insufficient_leave_balance',
                })
        obj = serializer.save(employee=e)
        audit(
            self.request.user, 'create',
            f'Created {obj.__class__.__name__} for {e.full_name}',
            e.company, obj.__class__.__name__.lower(), obj.id, request=self.request,
        )

    @action(detail=True, methods=['get'], url_path='pdf')
    def pdf(self, request, pk=None):
        obj = self.get_object()
        copy = (request.query_params.get('copy') or 'employee').lower()
        label = 'COMPANY COPY' if copy == 'company' else 'EMPLOYEE COPY'
        pdf_bytes = build_leave_request_pdf(obj, copy_label=label)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="leave-request-{obj.id}-{copy}.pdf"'
        return response


class BreakRequestViewSet(BaseRequestViewSet):
    serializer_class = BreakRequestSerializer

    def get_queryset(self):
        return self.scoped(BreakRequest.objects.filter(employee__company=self.request.user.company))

    def perform_create(self, serializer):
        e = Employee.objects.get(id=serializer.validated_data['employee'].id, company=self.request.user.company)
        obj = serializer.save(employee=e)
        audit(
            self.request.user, 'create',
            f'Created {obj.__class__.__name__} for {e.full_name}',
            e.company, obj.__class__.__name__.lower(), obj.id, request=self.request,
        )

    @action(detail=True, methods=['get'], url_path='pdf')
    def pdf(self, request, pk=None):
        obj = self.get_object()
        copy = (request.query_params.get('copy') or 'employee').lower()
        label = 'COMPANY COPY' if copy == 'company' else 'EMPLOYEE COPY'
        pdf_bytes = build_break_request_pdf(obj, copy_label=label)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="break-request-{obj.id}-{copy}.pdf"'
        return response


# --- Accruals & encashment ---
def _feature_or_403(key, company=None):
    from accounts.features import require_feature
    return require_feature(key, company=company)

from decimal import Decimal
from rest_framework.views import APIView
from .models import LeaveAccrualPolicy, LeaveBalance, LeaveEncashment, LeaveRequest


class LeaveAccrualPolicyView(APIView):
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManageHR]

    def get(self, request):
        ok, resp = _feature_or_403('leave_accruals', request.user.company)
        if not ok:
            return resp
        qs = LeaveAccrualPolicy.objects.filter(company=request.user.company)
        return Response([{
            'id': p.id, 'leave_type': p.leave_type, 'days_per_year': str(p.days_per_year),
            'accrue_monthly': p.accrue_monthly, 'allow_encashment': p.allow_encashment,
            'encashment_rate_percent': str(p.encashment_rate_percent),
            'monthly_accrual': str(p.monthly_accrual),
        } for p in qs])

    def post(self, request):
        ok, resp = _feature_or_403('leave_accruals', request.user.company)
        if not ok:
            return resp
        company = request.user.company
        lt = request.data.get('leave_type', 'annual')
        p, _ = LeaveAccrualPolicy.objects.update_or_create(
            company=company, leave_type=lt,
            defaults={
                'days_per_year': Decimal(str(request.data.get('days_per_year', 21))),
                'accrue_monthly': bool(request.data.get('accrue_monthly', True)),
                'allow_encashment': bool(request.data.get('allow_encashment', True)),
                'encashment_rate_percent': Decimal(str(request.data.get('encashment_rate_percent', 100))),
            },
        )
        return Response({'id': p.id, 'leave_type': p.leave_type}, status=201)


class RunLeaveAccrualView(APIView):
    """Accrue one month of leave for all active employees per policy."""
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManageHR]

    def post(self, request):
        ok, resp = _feature_or_403('leave_accruals', request.user.company)
        if not ok:
            return resp
        from employees.models import Employee
        company = request.user.company
        policies = list(LeaveAccrualPolicy.objects.filter(company=company, accrue_monthly=True))
        if not policies:
            return Response({'detail': 'Define accrual policies first.'}, status=400)
        count = 0
        for emp in Employee.objects.filter(company=company, employment_status='active'):
            for pol in policies:
                bal, _ = LeaveBalance.objects.get_or_create(
                    employee=emp, leave_type=pol.leave_type, defaults={'balance_days': 0},
                )
                bal.balance_days = bal.balance_days + pol.monthly_accrual
                bal.save(update_fields=['balance_days', 'updated_at'])
                count += 1
        return Response({'updated_balances': count})


class LeaveBalanceListView(APIView):
    permission_classes = [IsCompanyMember, IsCompanyActive]

    def get(self, request):
        ok, resp = _feature_or_403('leave_accruals', request.user.company)
        if not ok:
            return resp
        qs = LeaveBalance.objects.filter(employee__company=request.user.company).select_related('employee')
        if request.user.role == 'employee' and hasattr(request.user, 'employee_profile'):
            qs = qs.filter(employee=request.user.employee_profile)
        return Response([{
            'employee': b.employee.full_name, 'employee_id': b.employee_id,
            'leave_type': b.leave_type, 'balance_days': str(b.balance_days),
        } for b in qs])


class LeaveEncashmentView(APIView):
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManageHR]

    def get(self, request):
        ok, resp = _feature_or_403('leave_encashment', request.user.company)
        if not ok:
            return resp
        qs = LeaveEncashment.objects.filter(employee__company=request.user.company).select_related('employee')[:100]
        return Response([{
            'id': e.id, 'employee': e.employee.full_name, 'leave_type': e.leave_type,
            'days': str(e.days), 'amount': str(e.amount), 'status': e.status,
        } for e in qs])

    def post(self, request):
        ok, resp = _feature_or_403('leave_encashment', request.user.company)
        if not ok:
            return resp
        from employees.models import Employee
        emp = get_object_or_404(Employee, id=request.data.get('employee_id'), company=request.user.company)
        days = Decimal(str(request.data.get('days', 0)))
        leave_type = request.data.get('leave_type', 'annual')
        bal = LeaveBalance.objects.filter(employee=emp, leave_type=leave_type).first()
        if not bal or bal.balance_days < days:
            return Response({'detail': 'Insufficient leave balance.'}, status=400)
        pol = LeaveAccrualPolicy.objects.filter(company=request.user.company, leave_type=leave_type).first()
        if pol and not pol.allow_encashment:
            return Response({'detail': 'Encashment not allowed for this leave type.'}, status=400)
        daily = (emp.base_salary / Decimal('30')) if emp.base_salary else Decimal('0')
        rate = (pol.encashment_rate_percent / Decimal('100')) if pol else Decimal('1')
        amount = (daily * days * rate).quantize(Decimal('0.01'))
        bal.balance_days -= days
        bal.save(update_fields=['balance_days', 'updated_at'])
        enc = LeaveEncashment.objects.create(
            employee=emp, leave_type=leave_type, days=days, amount=amount, status='approved',
            reviewed_by=request.user,
        )
        return Response({'id': enc.id, 'amount': str(amount), 'balance_days': str(bal.balance_days)}, status=201)
