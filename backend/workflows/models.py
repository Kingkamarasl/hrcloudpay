from django.conf import settings
from django.db import models
from django.utils import timezone
from accounts.models import Company

class HRNotification(models.Model):
    LEVELS=[('info','Info'),('success','Success'),('warning','Warning'),('danger','Urgent')]
    TYPES=[('compliance','Compliance'),('contract','Contract'),('onboarding','Onboarding'),('leave','Leave'),('employee','Employee'),('payroll','Payroll'),('system','System')]
    company=models.ForeignKey(Company,on_delete=models.CASCADE,related_name='hr_notifications')
    recipient=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name='hr_notifications')
    employee=models.ForeignKey('employees.Employee',null=True,blank=True,on_delete=models.CASCADE,related_name='hr_notifications')
    notification_type=models.CharField(max_length=20,choices=TYPES,default='system')
    level=models.CharField(max_length=10,choices=LEVELS,default='info')
    title=models.CharField(max_length=200)
    message=models.TextField()
    action_url=models.CharField(max_length=300,blank=True)
    due_date=models.DateField(null=True,blank=True)
    dedupe_key=models.CharField(max_length=255,blank=True)
    read_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-created_at']
        indexes=[models.Index(fields=['recipient','read_at']),models.Index(fields=['company','notification_type','due_date'])]
        constraints=[models.UniqueConstraint(fields=['recipient','dedupe_key'],condition=~models.Q(dedupe_key=''),name='unique_notification_dedupe')]
    @property
    def is_read(self): return self.read_at is not None

class WorkflowTask(models.Model):
    STATUS=[('open','Open'),('in_progress','In progress'),('completed','Completed'),('cancelled','Cancelled')]
    PRIORITIES=[('low','Low'),('normal','Normal'),('high','High'),('urgent','Urgent')]
    TYPES=[('onboarding','Onboarding'),('offboarding','Offboarding'),('compliance','Compliance'),('contract','Contract renewal'),('leave','Leave'),('hr','HR task')]
    company=models.ForeignKey(Company,on_delete=models.CASCADE,related_name='workflow_tasks')
    employee=models.ForeignKey('employees.Employee',null=True,blank=True,on_delete=models.CASCADE,related_name='workflow_tasks')
    assigned_to=models.ForeignKey(settings.AUTH_USER_MODEL,null=True,blank=True,on_delete=models.SET_NULL,related_name='assigned_hr_tasks')
    task_type=models.CharField(max_length=20,choices=TYPES,default='hr')
    title=models.CharField(max_length=200)
    description=models.TextField(blank=True)
    priority=models.CharField(max_length=10,choices=PRIORITIES,default='normal')
    status=models.CharField(max_length=20,choices=STATUS,default='open')
    due_date=models.DateField(null=True,blank=True)
    source_type=models.CharField(max_length=60,blank=True)
    source_id=models.CharField(max_length=60,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    completed_at=models.DateTimeField(null=True,blank=True)
    class Meta:
        ordering=['status','due_date','-created_at']
        indexes=[models.Index(fields=['company','status','due_date'])]

class WorkflowRule(models.Model):
    EVENT_TYPES=[('employee_created','Employee created'),('contract_expiring','Contract expiring'),('compliance_alert','Compliance alert'),('leave_submitted','Leave submitted')]
    company=models.ForeignKey(Company,on_delete=models.CASCADE,related_name='workflow_rules')
    event_type=models.CharField(max_length=30,choices=EVENT_TYPES)
    name=models.CharField(max_length=180)
    enabled=models.BooleanField(default=True)
    create_task=models.BooleanField(default=True)
    send_notification=models.BooleanField(default=True)
    task_type=models.CharField(max_length=20,choices=WorkflowTask.TYPES,default='hr')
    priority=models.CharField(max_length=10,choices=WorkflowTask.PRIORITIES,default='normal')
    days_before=models.PositiveIntegerField(default=30)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['name']
        constraints=[models.UniqueConstraint(fields=['company','event_type','name'],name='unique_workflow_rule_name')]
