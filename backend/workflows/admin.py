from django.contrib import admin
from .models import HRNotification, WorkflowTask, WorkflowRule
@admin.register(HRNotification)
class HRNotificationAdmin(admin.ModelAdmin):
    list_display=('title','recipient','employee','notification_type','level','due_date','read_at','created_at')
    list_filter=('notification_type','level','read_at')
    search_fields=('title','message','recipient__username','employee__first_name','employee__last_name')
    readonly_fields=('created_at','read_at')
@admin.register(WorkflowTask)
class WorkflowTaskAdmin(admin.ModelAdmin):
    list_display=('title','employee','assigned_to','task_type','priority','status','due_date')
    list_filter=('task_type','priority','status')
    search_fields=('title','employee__first_name','employee__last_name','assigned_to__username')
    readonly_fields=('created_at','completed_at')
@admin.register(WorkflowRule)
class WorkflowRuleAdmin(admin.ModelAdmin):
    list_display=('name','company','event_type','enabled','create_task','send_notification','days_before')
    list_filter=('event_type','enabled','create_task','send_notification')
    search_fields=('name','company__name')
