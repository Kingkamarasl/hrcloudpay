from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('employees','0003_core_hr_employee_details'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(name='EmployeeDocument', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('document_type', models.CharField(choices=[('identity','Identity Document'),('contract','Contract'),('certificate','Certificate'),('qualification','Qualification'),('policy','Policy / Acknowledgement'),('medical','Medical / Fitness'),('disciplinary','Disciplinary'),('other','Other')], default='other', max_length=30)),
        ('title', models.CharField(max_length=200)), ('document', models.FileField(upload_to='employee_documents/')),
        ('issue_date', models.DateField(blank=True, null=True)), ('expiry_date', models.DateField(blank=True, null=True)), ('notes', models.TextField(blank=True)), ('created_at', models.DateTimeField(auto_now_add=True)),
        ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='documents', to='employees.employee')),
        ('uploaded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='uploaded_employee_documents', to=settings.AUTH_USER_MODEL)),
    ], options={'ordering':['-created_at']})]
