from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leave', '0002_breakrequest'),
    ]

    operations = [
        migrations.AlterField(
            model_name='leaverequest',
            name='leave_type',
            field=models.CharField(
                choices=[
                    ('annual', 'Annual'), ('sick', 'Sick'), ('maternity', 'Maternity'),
                    ('paternity', 'Paternity'), ('compassionate', 'Compassionate'),
                    ('break_off_duty', 'Break-Off Duty'), ('unpaid', 'Unpaid'), ('other', 'Other'),
                ],
                default='annual', max_length=20,
            ),
        ),
    ]
