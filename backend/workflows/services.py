from datetime import timedelta
from django.db import IntegrityError
from django.utils import timezone
from accounts.audit import audit
from accounts.models import User, Company
from employees.models import Employee, Contract, RequiredDocumentRule
from .models import HRNotification, WorkflowTask, WorkflowRule

HR_ROLES=('owner','admin','hr')

def hr_recipients(company):
    return list(User.objects.filter(company=company,is_active=True,role__in=HR_ROLES))

def notify(company,title,message,notification_type='system',level='info',employee=None,action_url='',due_date=None,dedupe_key=''):
    created=[]
    defaults=dict(company=company,title=title,message=message,notification_type=notification_type,level=level,employee=employee,action_url=action_url,due_date=due_date)
    for user in hr_recipients(company):
        try:
            if dedupe_key:
                obj, was_created = HRNotification.objects.get_or_create(
                    recipient=user, dedupe_key=dedupe_key, defaults=defaults
                )
            else:
                obj = HRNotification.objects.create(recipient=user, dedupe_key='', **defaults)
                was_created = True
            if was_created:
                created.append(obj)
        except IntegrityError:
            pass
    return created

def task(company,title,description='',task_type='hr',priority='normal',employee=None,due_date=None,source_type='',source_id=''):
    assignee=next(iter(hr_recipients(company)),None)
    obj=WorkflowTask.objects.create(company=company,employee=employee,assigned_to=assignee,title=title,description=description,task_type=task_type,priority=priority,due_date=due_date,source_type=source_type,source_id=str(source_id or ''))
    return obj

def onboard_employee(employee):
    rules=WorkflowRule.objects.filter(company=employee.company,event_type='employee_created',enabled=True)
    active_rules=list(rules) or [None]
    for rule in active_rules:
        title=f'Complete onboarding for {employee.full_name}'
        description='Review required documents, contract, HR details and employee setup.'
        if not rule or rule.create_task: task(employee.company,title,description,task_type='onboarding',priority=(rule.priority if rule else 'normal'),employee=employee,due_date=(employee.hire_date or timezone.localdate())+timedelta(days=(rule.days_before if rule else 7)),source_type='employee',source_id=employee.id)
        if not rule or rule.send_notification: notify(employee.company,'New employee onboarding',f'{employee.full_name} needs onboarding setup.', 'onboarding','info',employee,f'/employees/{employee.id}',employee.hire_date,dedupe_key=f'onboard:{employee.id}')

def run_due_automations(company=None):
    today=timezone.localdate(); qs=Company.objects.all() if company is None else Company.objects.filter(pk=company.pk)
    counts={'contracts':0,'compliance':0,'leave':0,'tasks':0,'notifications':0}
    for c in qs:
        # Contract deadlines
        contract_rule=WorkflowRule.objects.filter(company=c,event_type='contract_expiring',enabled=True).order_by('id').first()
        default_days=contract_rule.days_before if contract_rule else 30
        for con in Contract.objects.filter(employee__company=c,end_date__isnull=False,end_date__gte=today,end_date__lte=today+timedelta(days=default_days)).select_related('employee'):
            emp=con.employee; key=f'contract:{con.id}:{con.end_date}'
            if not contract_rule or contract_rule.send_notification:
                counts['notifications'] += len(notify(c,'Contract renewal needed',f'{emp.full_name} has a {con.get_contract_type_display()} contract ending on {con.end_date}.','contract','warning',emp,f'/employees/{emp.id}',con.end_date,key))
            if (not contract_rule or contract_rule.create_task) and not WorkflowTask.objects.filter(company=c,source_type='contract',source_id=str(con.id)).exists():
                task(c,f'Review contract renewal — {emp.full_name}',f'Contract ends {con.end_date}. Review renewal or end-of-contract action.','contract',contract_rule.priority if contract_rule else 'high',emp,con.end_date,'contract',con.id); counts['tasks']+=1
            counts['contracts']+=1
        # Compliance alerts: reuse existing dashboard logic through model rules.
        for rule in RequiredDocumentRule.objects.filter(company=c,is_active=True):
            emps=Employee.objects.filter(company=c,employment_status__in=('active','on_leave'))
            if rule.employee_id: emps=emps.filter(id=rule.employee_id)
            if rule.contract_type:
                emps=emps.filter(contracts__contract_type=rule.contract_type,contracts__start_date__lte=today).filter(contracts__end_date__isnull=True)|emps.filter(contracts__contract_type=rule.contract_type,contracts__start_date__lte=today,contracts__end_date__gte=today)
            for emp in emps.distinct():
                doc=emp.documents.filter(document_type=rule.document_type).order_by('-created_at').first()
                missing=not doc
                expired=bool(doc and doc.expiry_date and doc.expiry_date<today)
                expiring=bool(doc and doc.expiry_date and today<=doc.expiry_date<=today+timedelta(days=rule.warning_days))
                if missing or expired or expiring:
                    status='missing' if missing else ('expired' if expired else 'expiring')
                    level='danger' if status in ('missing','expired') else 'warning'
                    due=doc.expiry_date if doc and doc.expiry_date else today
                    key=f'compliance:{rule.id}:{emp.id}:{status}:{due}'
                    compliance_rule=WorkflowRule.objects.filter(company=c,event_type='compliance_alert',enabled=True).order_by('id').first()
                    if not compliance_rule or compliance_rule.send_notification:
                        counts['notifications'] += len(notify(c,f'{status.title()} document: {rule.name}',f'{emp.full_name} — {rule.name} is {status}.','compliance',level,emp,f'/employees/{emp.id}',due,key))
                    if (not compliance_rule or compliance_rule.create_task) and not WorkflowTask.objects.filter(company=c,source_type='compliance',source_id=key).exists():
                        task(c,f'Resolve {status} document — {emp.full_name}',f'Requirement: {rule.name}. Review the employee record and upload/replace the document.','compliance',compliance_rule.priority if compliance_rule else ('urgent' if status in ('missing','expired') else 'high'),emp,due,'compliance',key); counts['tasks']+=1
                    counts['compliance']+=1
        # Pending leave requests
        from leave.models import LeaveRequest
        for leave in LeaveRequest.objects.filter(employee__company=c,status='pending').select_related('employee')[:100]:
            key=f'leave:{leave.id}:pending'
            leave_rule=WorkflowRule.objects.filter(company=c,event_type='leave_submitted',enabled=True).order_by('id').first()
            if not leave_rule or leave_rule.send_notification:
                counts['notifications'] += len(notify(c,'Leave request awaiting review',f'{leave.employee.full_name} requested {leave.days_requested} day(s) of {leave.get_leave_type_display()} leave.','leave','info',leave.employee,'/leave',leave.start_date,key))
            if (not leave_rule or leave_rule.create_task) and not WorkflowTask.objects.filter(company=c,source_type='leave',source_id=str(leave.id)).exists():
                task(c,f'Review leave request — {leave.employee.full_name}',f'Leave request starts {leave.start_date}. Review and approve or reject the request.','leave',leave_rule.priority if leave_rule else 'normal',leave.employee,leave.start_date,'leave',leave.id); counts['tasks']+=1
            counts['leave']+=1
    return counts
