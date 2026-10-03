from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('regional', '0004_statutory_filing_workflow'),
    ]

    operations = [
        migrations.AlterField(
            model_name='statutoryfiling',
            name='status',
            field=models.CharField(
                choices=[
                    ('open', 'Open'),
                    ('reviewed', 'Reviewed'),
                    ('approved', 'Approved'),
                    ('paid', 'Paid'),
                    ('submitted', 'Submitted'),
                    ('closed', 'Closed'),
                    ('overdue', 'Overdue'),
                    ('ready', 'Ready (legacy)'),
                    ('filed', 'Filed (legacy)'),
                ],
                default='open',
                max_length=20,
            ),
        ),
    ]
