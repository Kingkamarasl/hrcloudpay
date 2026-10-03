from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('accounts','0003_platform_control_center')]
    operations = [
        migrations.AlterField(
            model_name='auditlog', name='action',
            field=models.CharField(max_length=30, choices=[
                ('create','Create'),('update','Update'),('delete','Delete'),('activate','Activate'),('suspend','Suspend'),
                ('login','Login'),('logout','Logout'),('login_failed','Login failed'),('invite','Invite'),('permission_change','Permission change'),
                ('salary_change','Salary change'),('termination','Termination'),('contract_change','Contract change'),
                ('payroll_process','Payroll process'),('payroll_approve','Payroll approval'),('payroll_payment','Payroll payment'),('system','System')
            ], default='system')
        )
    ]
