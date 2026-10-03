from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('employees','0009_employee_profile_photo')]
    operations = [migrations.CreateModel(
        name='EmployeeStatutoryProfile',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('identifiers', models.JSONField(blank=True, default=dict)),
            ('tax_region', models.CharField(blank=True, max_length=150)),
            ('social_security_region', models.CharField(blank=True, max_length=150)),
            ('bank_name', models.CharField(blank=True, max_length=150)),
            ('bank_branch', models.CharField(blank=True, max_length=150)),
            ('account_name', models.CharField(blank=True, max_length=200)),
            ('mobile_money_provider', models.CharField(blank=True, max_length=100)),
            ('mobile_money_number', models.CharField(blank=True, max_length=50)),
            ('notes', models.TextField(blank=True)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('employee', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='statutory_profile', to='employees.employee')),
        ],
    )]
