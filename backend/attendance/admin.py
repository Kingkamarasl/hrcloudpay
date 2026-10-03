from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import Attendance


@admin.register(Attendance)
class AttendanceAdmin(ModelAdmin):
    list_display = ['employee', 'date', 'check_in', 'check_out', 'status']
    list_filter = ['status', 'date']
    search_fields = ['employee__first_name', 'employee__last_name', 'employee__employee_code']
    list_select_related = ['employee']
