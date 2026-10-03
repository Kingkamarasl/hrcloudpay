from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import LeaveRequest, BreakRequest


@admin.register(LeaveRequest)
class LeaveRequestAdmin(ModelAdmin):
    list_display = ['employee', 'leave_type', 'start_date', 'end_date', 'status', 'applied_at']
    list_filter = ['leave_type', 'status', 'start_date']
    search_fields = ['employee__first_name', 'employee__last_name', 'employee__employee_code']
    list_select_related = ['employee']


@admin.register(BreakRequest)
class BreakRequestAdmin(ModelAdmin):
    list_display = ['employee', 'date', 'start_time', 'end_time', 'status', 'applied_at']
    list_filter = ['status', 'start_time']
    search_fields = ['employee__first_name', 'employee__last_name', 'employee__employee_code']
    list_select_related = ['employee']
