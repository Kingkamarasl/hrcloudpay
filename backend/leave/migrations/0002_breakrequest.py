import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies=[('leave','0001_initial'),('employees','0002_department_employee_fields_warningletter'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[migrations.CreateModel(
        name='BreakRequest',
        fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('break_type',models.CharField(choices=[('short','Short Break'),('lunch','Lunch Break'),('personal','Personal Break'),('other','Other')],default='personal',max_length=20)),
            ('date',models.DateField()),('start_time',models.TimeField()),('end_time',models.TimeField(blank=True,null=True)),('reason',models.TextField(blank=True)),
            ('status',models.CharField(choices=[('pending','Pending'),('approved','Approved'),('rejected','Rejected')],default='pending',max_length=20)),
            ('applied_at',models.DateTimeField(auto_now_add=True)),
            ('employee',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='break_requests',to='employees.employee')),
            ('reviewed_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='reviewed_break_requests',to=settings.AUTH_USER_MODEL)),
        ], options={'ordering':['-date','-applied_at']}
    )]
