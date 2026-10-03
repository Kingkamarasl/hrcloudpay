import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def populate_departments(apps, schema_editor):
    Company = apps.get_model('accounts', 'Company')
    Employee = apps.get_model('employees', 'Employee')
    Department = apps.get_model('employees', 'Department')
    for company in Company.objects.all():
        names = set(Employee.objects.filter(company=company).exclude(department='').values_list('department', flat=True))
        for name in names:
            dept, _ = Department.objects.get_or_create(company=company, name=name)
            Employee.objects.filter(company=company, department=name).update(department_obj=dept)

class Migration(migrations.Migration):
    dependencies=[('employees','0001_initial'),('accounts','0002_user_roles_and_department_manager')]
    operations=[
        migrations.CreateModel(
            name='Department',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('name',models.CharField(max_length=150)),
                ('description',models.TextField(blank=True)),
                ('is_active',models.BooleanField(default=True)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('company',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='departments',to='accounts.company')),
            ],
            options={'ordering':['name']},
        ),
        migrations.AddField(model_name='employee',name='id_card_no',field=models.CharField(blank=True,help_text='National/employee identification number',max_length=80)),
        migrations.AddField(model_name='employee',name='department_obj',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='employees',to='employees.department')),
        migrations.AlterField(model_name='employee',name='employment_status',field=models.CharField(choices=[('active','Active'),('on_leave','On Leave'),('suspended','Suspended'),('terminated','Terminated'),('resigned','Resigned')],default='active',max_length=20)),
        migrations.AlterField(model_name='contract',name='contract_type',field=models.CharField(choices=[('full_time','Full-time'),('part_time','Part-time'),('contractor','Contractor'),('internship','Internship'),('temporary','Temporary')],default='full_time',max_length=20)),
        migrations.CreateModel(
            name='WarningLetter',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('warning_level',models.CharField(choices=[('verbal','Verbal Warning'),('first','First Written Warning'),('final','Final Written Warning'),('disciplinary','Disciplinary Action')],default='first',max_length=20)),
                ('subject',models.CharField(max_length=200)),
                ('incident_date',models.DateField(blank=True,null=True)),
                ('issued_date',models.DateField()),
                ('details',models.TextField()),
                ('employee_response',models.TextField(blank=True)),
                ('acknowledged',models.BooleanField(default=False)),
                ('document',models.FileField(blank=True,null=True,upload_to='warning_letters/')),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('employee',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='warning_letters',to='employees.employee')),
                ('issued_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering':['-issued_date','-created_at']},
        ),
        migrations.AddConstraint(model_name='department',constraint=models.UniqueConstraint(fields=('company','name'),name='unique_department_per_company')),
        migrations.RunPython(populate_departments,migrations.RunPython.noop),
    ]
