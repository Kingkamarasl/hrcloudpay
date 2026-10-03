from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0010_company_address'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='logo',
            field=models.ImageField(
                blank=True,
                help_text='Company logo shown on payslips and break request forms.',
                max_length=500,
                null=True,
                upload_to='company_logos/%Y/%m/',
            ),
        ),
    ]
