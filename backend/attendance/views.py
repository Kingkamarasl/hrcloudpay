from rest_framework import viewsets

from accounts.permissions import CanManageHROrDepartment, IsCompanyActive, IsCompanyMember
from accounts.audit import audit, changed_fields, snapshot_fields
from employees.models import Employee

from .models import Attendance
from .serializers import AttendanceSerializer


class AttendanceViewSet(viewsets.ModelViewSet):
    serializer_class = AttendanceSerializer
    permission_classes = [IsCompanyMember, IsCompanyActive, CanManageHROrDepartment]

    def get_queryset(self):
        qs = Attendance.objects.filter(employee__company=self.request.user.company)
        user = self.request.user
        employee_id = self.request.query_params.get('employee')
        if employee_id:
            qs = qs.filter(employee_id=employee_id)
        # Row-level visibility by role
        if user.role == 'employee' and hasattr(user, 'employee_profile'):
            qs = qs.filter(employee=user.employee_profile)
        elif user.role == 'department_manager':
            qs = qs.filter(employee__department=user.managed_department)
        return qs

    def perform_create(self, serializer):
        employee=Employee.objects.get(id=serializer.validated_data['employee'].id, company=self.request.user.company)
        obj=serializer.save(employee=employee)
        audit(self.request.user, 'create', f'Recorded attendance for {employee.full_name}', employee.company, 'attendance', obj.id, {'date': str(obj.date), 'status': obj.status}, request=self.request)

    def perform_update(self, serializer):
        instance=self.get_object(); before=snapshot_fields(instance, ['date','check_in','check_out','status','notes']); obj=serializer.save(); changes=changed_fields(obj, ['date','check_in','check_out','status','notes'], before=before); audit(self.request.user, 'update', f'Updated attendance for {obj.employee.full_name}', obj.employee.company, 'attendance', obj.id, {'changes':changes}, request=self.request)
    def perform_destroy(self, instance):
        audit(self.request.user, 'delete', f'Deleted attendance for {instance.employee.full_name}', instance.employee.company, 'attendance', instance.id, {'date':str(instance.date)}, request=self.request); instance.delete()

