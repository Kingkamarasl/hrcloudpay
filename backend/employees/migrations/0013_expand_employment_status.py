from django.db import migrations, models


class Migration(migrations.Migration):
    """Allow the five employment states the interface has always offered.

    The model had been narrowed to active/terminated while the employee form,
    department roster and contracts still used on_leave, suspended and
    resigned. Selecting one of those in the UI therefore failed validation with
    "is not a valid choice". ``employees.services`` and the workflow code
    already assumed the wider set, so the model was the part out of step.
    """

    dependencies = [
        ('employees', '0012_unique_employee_email_per_company'),
    ]

    operations = [
        migrations.AlterField(
            model_name='employee',
            name='employment_status',
            field=models.CharField(
                choices=[
                    ('active', 'Active'),
                    ('on_leave', 'On leave'),
                    ('suspended', 'Suspended'),
                    ('terminated', 'Terminated'),
                    ('resigned', 'Resigned'),
                ],
                default='active',
                max_length=20,
            ),
        ),
    ]
