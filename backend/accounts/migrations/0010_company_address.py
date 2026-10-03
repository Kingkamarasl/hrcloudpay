from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0009_advanced_platform_admin'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='address',
            field=models.CharField(blank=True, help_text='Shown on payslips and printed HR forms', max_length=255),
        ),
    ]
