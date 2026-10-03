from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('employees', '0007_employee_pay_point_bank_account'),
        ('payroll', '0003_unique_payroll_period'),
        ('accounts', '0010_company_address'),
    ]

    operations = [
        migrations.CreateModel(
            name='OvertimeRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('weekday_multiplier', models.DecimalField(decimal_places=2, default=1.5, max_digits=5)),
                ('weekend_multiplier', models.DecimalField(decimal_places=2, default=2.0, max_digits=5)),
                ('holiday_multiplier', models.DecimalField(decimal_places=2, default=2.0, max_digits=5)),
                ('standard_hours_per_month', models.DecimalField(decimal_places=2, default=173, max_digits=6)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('company', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='overtime_rule', to='accounts.company')),
            ],
        ),
        migrations.CreateModel(
            name='OvertimeEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('work_date', models.DateField()),
                ('hours', models.DecimalField(decimal_places=2, max_digits=6)),
                ('day_type', models.CharField(choices=[('weekday', 'Weekday'), ('weekend', 'Weekend'), ('holiday', 'Public holiday')], default='weekday', max_length=20)),
                ('amount', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('notes', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='overtime_entries', to='accounts.company')),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='overtime_entries', to='employees.employee')),
                ('payroll_run', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='overtime_entries', to='payroll.payrollrun')),
            ],
            options={'ordering': ['-work_date']},
        ),
        migrations.CreateModel(
            name='SalaryAdvance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=14)),
                ('remaining', models.DecimalField(decimal_places=2, max_digits=14)),
                ('installment_amount', models.DecimalField(decimal_places=2, help_text='Amount recovered automatically each payroll run', max_digits=14)),
                ('reason', models.CharField(blank=True, max_length=255)),
                ('status', models.CharField(choices=[('open', 'Open'), ('partial', 'Partially recovered'), ('cleared', 'Cleared'), ('cancelled', 'Cancelled')], default='open', max_length=20)),
                ('granted_on', models.DateField(auto_now_add=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='salary_advances', to='accounts.company')),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='salary_advances', to='employees.employee')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='AdvanceRecovery',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=14)),
                ('recovered_at', models.DateTimeField(auto_now_add=True)),
                ('advance', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='recoveries', to='payroll.salaryadvance')),
                ('payslip', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='advance_recoveries', to='payroll.payslip')),
            ],
        ),
    ]
