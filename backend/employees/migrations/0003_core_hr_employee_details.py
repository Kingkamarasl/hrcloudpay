from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('employees', '0002_department_employee_fields_warningletter'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EmployeePersonalDetails',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date_of_birth', models.DateField(blank=True, null=True)),
                ('gender', models.CharField(blank=True, choices=[('female', 'Female'), ('male', 'Male'), ('non_binary', 'Non-binary'), ('prefer_not_to_say', 'Prefer not to say')], max_length=30)),
                ('marital_status', models.CharField(blank=True, choices=[('single', 'Single'), ('married', 'Married'), ('divorced', 'Divorced'), ('widowed', 'Widowed'), ('other', 'Other'), ('prefer_not_to_say', 'Prefer not to say')], max_length=30)),
                ('nationality', models.CharField(blank=True, max_length=100)),
                ('address_line_1', models.CharField(blank=True, max_length=255)),
                ('address_line_2', models.CharField(blank=True, max_length=255)),
                ('city', models.CharField(blank=True, max_length=100)),
                ('state_region', models.CharField(blank=True, max_length=100)),
                ('postal_code', models.CharField(blank=True, max_length=30)),
                ('country', models.CharField(blank=True, max_length=100)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('employee', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='personal_details', to='employees.employee')),
            ],
        ),
        migrations.CreateModel(
            name='EmergencyContact',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=150)),
                ('relationship', models.CharField(max_length=100)),
                ('phone', models.CharField(max_length=50)),
                ('email', models.EmailField(blank=True, max_length=254)),
                ('address', models.CharField(blank=True, max_length=255)),
                ('is_primary', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='emergency_contacts', to='employees.employee')),
            ],
            options={'ordering': ['-is_primary', 'name']},
        ),
        migrations.AddConstraint(
            model_name='emergencycontact',
            constraint=models.UniqueConstraint(condition=Q(is_primary=True), fields=('employee',), name='unique_primary_emergency_contact_per_employee'),
        ),
        migrations.CreateModel(
            name='EmploymentEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(choices=[('hired', 'Hired'), ('status_change', 'Status Change'), ('promotion', 'Promotion'), ('transfer', 'Department Transfer'), ('job_change', 'Job/Position Change'), ('salary_change', 'Salary Change'), ('contract_change', 'Contract Change'), ('rehired', 'Rehired'), ('resigned', 'Resigned'), ('terminated', 'Terminated'), ('note', 'HR Note')], max_length=30)),
                ('effective_date', models.DateField(default=timezone.localdate)),
                ('title', models.CharField(blank=True, max_length=200)),
                ('description', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_employment_events', to=settings.AUTH_USER_MODEL)),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='employment_events', to='employees.employee')),
            ],
            options={'ordering': ['-effective_date', '-created_at']},
        ),
    ]
