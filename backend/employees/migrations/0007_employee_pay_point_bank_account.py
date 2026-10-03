from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('employees', '0006_required_document_rule_constraints'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='pay_point',
            field=models.CharField(blank=True, help_text='Work site/duty station shown on payslips and leave forms', max_length=150),
        ),
        migrations.AddField(
            model_name='employee',
            name='bank_account_number',
            field=models.CharField(blank=True, help_text='Shown on payslips - account number only, never full banking credentials', max_length=50),
        ),
    ]
