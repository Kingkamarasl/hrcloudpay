from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('owner', 'Owner'),
                    ('admin', 'Admin'),
                    ('hr', 'HR Manager'),
                    ('finance', 'Finance Manager'),
                    ('department_manager', 'Department Manager'),
                    ('employee', 'Employee'),
                ],
                default='owner',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='managed_department',
            field=models.CharField(blank=True, max_length=150),
        ),
    ]
