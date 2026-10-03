from decimal import Decimal
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('employees', '0007_employee_pay_point_bank_account'),
        ('accounts', '0010_company_address'),
        ('leave', '0003_leave_type_choices'),
    ]

    operations = [
        migrations.CreateModel(
            name='LeaveAccrualPolicy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('leave_type', models.CharField(choices=[('annual', 'Annual'), ('sick', 'Sick'), ('maternity', 'Maternity'), ('paternity', 'Paternity'), ('compassionate', 'Compassionate'), ('break_off_duty', 'Break-Off Duty'), ('unpaid', 'Unpaid'), ('other', 'Other')], default='annual', max_length=20)),
                ('days_per_year', models.DecimalField(decimal_places=2, default=21, max_digits=6)),
                ('accrue_monthly', models.BooleanField(default=True)),
                ('allow_encashment', models.BooleanField(default=True)),
                ('encashment_rate_percent', models.DecimalField(decimal_places=2, default=100, help_text='% of daily rate paid on encashment (100 = full day rate)', max_digits=5)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='leave_accrual_policies', to='accounts.company')),
            ],
            options={'unique_together': {('company', 'leave_type')}},
        ),
        migrations.CreateModel(
            name='LeaveBalance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('leave_type', models.CharField(choices=[('annual', 'Annual'), ('sick', 'Sick'), ('maternity', 'Maternity'), ('paternity', 'Paternity'), ('compassionate', 'Compassionate'), ('break_off_duty', 'Break-Off Duty'), ('unpaid', 'Unpaid'), ('other', 'Other')], default='annual', max_length=20)),
                ('balance_days', models.DecimalField(decimal_places=2, default=0, max_digits=8)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='leave_balances', to='employees.employee')),
            ],
            options={'unique_together': {('employee', 'leave_type')}},
        ),
        migrations.CreateModel(
            name='LeaveEncashment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('leave_type', models.CharField(choices=[('annual', 'Annual'), ('sick', 'Sick'), ('maternity', 'Maternity'), ('paternity', 'Paternity'), ('compassionate', 'Compassionate'), ('break_off_duty', 'Break-Off Duty'), ('unpaid', 'Unpaid'), ('other', 'Other')], default='annual', max_length=20)),
                ('days', models.DecimalField(decimal_places=2, max_digits=6)),
                ('amount', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('paid', 'Paid'), ('rejected', 'Rejected')], default='pending', max_length=20)),
                ('requested_at', models.DateTimeField(auto_now_add=True)),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='leave_encashments', to='employees.employee')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_encashments', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
