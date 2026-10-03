from django.db.models import Q
from django.utils import timezone

from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import CanManageHROrDepartment, IsCompanyActive, IsCompanyMember
from accounts.audit import audit, changed_fields, snapshot_fields

from .models import Attendance
from .serializers import AttendanceSerializer

TRACKED = ['date', 'check_in', 'check_out', 'crossed_midnight', 'status', 'notes']


class AttendanceViewSet(viewsets.ModelViewSet):
    serializer_class = AttendanceSerializer
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManageHROrDepartment]

    def get_queryset(self):
        """Company-scoped always, then narrowed by role. Deny by default.

        The employee branch used to be guarded by `hasattr(user,
        'employee_profile')`, which is False for an account with no linked
        Employee row. That made the whole branch - including its queryset
        filter - disappear, so such an account fell through to the unfiltered
        company queryset and saw every attendance record in the tenant. Writes
        were still blocked by CanManageHROrDepartment, which is why this was a
        read leak and not a write one.

        Now an employee with no profile matches nothing. An unlinked account is
        a provisioning mistake, and the safe reading of it is "no records",
        never "all records".
        """
        user = self.request.user
        qs = Attendance.objects.filter(employee__company=user.company)

        if user.role == 'employee':
            profile_id = user.employee_id
            return qs.filter(employee_id=profile_id) if profile_id else qs.none()

        if user.role == 'department_manager':
            if not user.managed_department:
                return qs.none()
            return qs.filter(employee__department=user.managed_department)

        employee_id = self.request.query_params.get('employee')
        if employee_id:
            qs = qs.filter(employee_id=employee_id)

        start = self.request.query_params.get('start')
        end = self.request.query_params.get('end')
        if start:
            qs = qs.filter(date__gte=start)
        if end:
            qs = qs.filter(date__lte=end)

        return qs

    def perform_create(self, serializer):
        # The employee is validated against the caller's company in the
        # serializer, so there is nothing left to look up here. The previous
        # unguarded Employee.objects.get() was what turned a cross-tenant id
        # into a 500.
        obj = serializer.save()
        audit(
            self.request.user, 'create',
            f'Recorded attendance for {obj.employee.full_name}',
            obj.employee.company, 'attendance', obj.id,
            {'date': str(obj.date), 'status': obj.status},
            request=self.request,
        )

    def perform_update(self, serializer):
        before = snapshot_fields(serializer.instance, TRACKED)
        obj = serializer.save()
        changes = changed_fields(obj, TRACKED, before=before)
        audit(
            self.request.user, 'update',
            f'Updated attendance for {obj.employee.full_name}',
            obj.employee.company, 'attendance', obj.id,
            {'changes': changes},
            request=self.request,
        )

    def perform_destroy(self, instance):
        audit(
            self.request.user, 'delete',
            f'Deleted attendance for {instance.employee.full_name}',
            instance.employee.company, 'attendance', instance.id,
            {'date': str(instance.date)},
            request=self.request,
        )
        instance.delete()


class ClockView(APIView):
    """Clock in and clock out, for yourself or on someone's behalf.

    Two design points that are not obvious:

    **Clock-out finds the open record, not today's.** Someone who clocks in at
    22:00 clocks out at 06:00 the next morning, and that shift belongs to the
    day they started. Looking up "today" would refuse the clock-out and leave
    the shift permanently open, so the record is found by "has a check-in and no
    check-out" instead.

    **A second clock-in is refused rather than silently replacing the first.**
    Re-clocking in over a forgotten open record would destroy real hours and
    leave no trace, which is the kind of quiet data loss that only surfaces at
    payroll.

    Scope reuses `CanManageHROrDepartment.employee_in_scope` rather than
    re-deciding who may mark whom: an employee can only clock themselves, and
    the roles that manage attendance keep the reach they already had.
    """

    permission_classes = [IsCompanyMember, IsCompanyActive]

    def _target_employee(self, request):
        from accounts.permissions import CanManageHROrDepartment
        from employees.models import Employee

        user = request.user
        if user.role == 'employee':
            profile_id = user.employee_id
            if not profile_id:
                raise ValidationError({
                    'detail': 'This account is not linked to an employee record, '
                              'so there is nothing to clock in for.',
                })
            employee = Employee.objects.filter(id=profile_id).first()
            if employee is None:
                raise ValidationError({
                    'detail': 'This account is not linked to an employee record.',
                })
            # Refuse rather than quietly clock in the caller instead. Silently
            # ignoring the id would return 201 and record the wrong person,
            # which is how a client's bug becomes a payroll correction.
            supplied = request.data.get('employee')
            if supplied not in (None, '', employee.id, str(employee.id)):
                raise ValidationError({
                    'employee': 'You can only clock in for yourself.',
                })
            return employee

        employee_id = request.data.get('employee')
        if not employee_id:
            raise ValidationError({
                'employee': 'Required when clocking on behalf of someone else.',
            })
        employee = Employee.objects.filter(
            id=employee_id, company=user.company).first()
        if employee is None:
            raise ValidationError({'employee': 'Unknown employee.'})
        if not CanManageHROrDepartment().employee_in_scope(request, employee):
            raise PermissionDenied('You cannot record attendance for this employee.')
        return employee

    def post(self, request):
        action = request.data.get('action')
        if action not in ('clock_in', 'clock_out'):
            raise ValidationError({
                'action': 'Must be clock_in or clock_out.',
            })
        employee = self._target_employee(request)
        now = timezone.localtime() if timezone.is_aware(timezone.now()) else timezone.now()
        today = now.date()
        current_time = now.time().replace(tzinfo=None)

        if action == 'clock_in':
            already_today = Attendance.objects.filter(
                employee=employee, date=today).first()
            if already_today is not None:
                raise ValidationError({
                    'detail': f'{employee.full_name} already has a record for '
                              f'{today}. Edit it rather than clocking in again.',
                })
            record = Attendance.objects.create(
                employee=employee, date=today, status='present',
                check_in=current_time,
                notes='Clocked in',
            )
            audit(
                request.user, 'create',
                f'Clocked in {employee.full_name}',
                employee.company, 'attendance', record.id,
                {'date': str(record.date), 'check_in': str(current_time)},
                request=request,
            )
            return Response(AttendanceSerializer(record).data, status=201)

        # clock_out: the open record, which may not be today's.
        open_record = Attendance.objects.filter(
            employee=employee, check_in__isnull=False, check_out__isnull=True,
        ).order_by('-date').first()
        if open_record is None:
            raise ValidationError({
                'detail': f'{employee.full_name} has no open shift to clock out of.',
            })
        # Earlier than the check-in means the shift ended the next day. Without
        # this the serializer would reject it, because a bare 22:00 -> 06:00 is
        # indistinguishable from a typo until somebody says which it is.
        crossed = current_time < open_record.check_in
        open_record.check_out = current_time
        open_record.crossed_midnight = crossed
        open_record.save(update_fields=['check_out', 'crossed_midnight'])
        audit(
            request.user, 'update',
            f'Clocked out {employee.full_name}',
            employee.company, 'attendance', open_record.id,
            {
                'date': str(open_record.date),
                'check_out': str(current_time),
                'crossed_midnight': crossed,
            },
            request=request,
        )
        return Response(AttendanceSerializer(open_record).data, status=200)