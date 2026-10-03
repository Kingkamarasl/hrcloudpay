from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [
        ('payroll', '0005_public_holiday'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='payslip',
            constraint=models.UniqueConstraint(
                fields=['payroll_run', 'employee'],
                name='unique_payslip_per_run_employee',
            ),
        ),
        migrations.AlterField(
            model_name='overtimeentry',
            name='hours',
            field=models.DecimalField(
                decimal_places=2,
                max_digits=6,
                validators=[django.core.validators.MinValueValidator(0.01)],
            ),
        ),
        migrations.AlterField(
            model_name='salaryadvance',
            name='amount',
            field=models.DecimalField(
                decimal_places=2,
                max_digits=14,
                validators=[django.core.validators.MinValueValidator(0.01)],
            ),
        ),
        migrations.AlterField(
            model_name='salaryadvance',
            name='remaining',
            field=models.DecimalField(
                decimal_places=2,
                max_digits=14,
                validators=[django.core.validators.MinValueValidator(0)],
            ),
        ),
        migrations.AlterField(
            model_name='salaryadvance',
            name='installment_amount',
            field=models.DecimalField(
                decimal_places=2,
                help_text='Amount recovered automatically each payroll run',
                max_digits=14,
                validators=[django.core.validators.MinValueValidator(0.01)],
            ),
        ),
    ]
