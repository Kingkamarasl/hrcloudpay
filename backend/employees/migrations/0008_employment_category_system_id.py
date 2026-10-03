
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('employees', '0007_employee_pay_point_bank_account'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='employment_category',
            field=models.CharField(
                choices=[('casual', 'Casual'), ('short_time', 'Short time'), ('long_time', 'Long time')],
                default='long_time',
                help_text='Determines system employee ID prefix: CA (casual), ST (short time), LT (long time).',
                max_length=20,
            ),
        ),
    ]
