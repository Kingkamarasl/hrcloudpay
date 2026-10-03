from django.db.models import Q

from rest_framework import serializers, viewsets

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