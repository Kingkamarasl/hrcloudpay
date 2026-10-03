from django.db import migrations, models


def reject_existing_duplicates(apps, schema_editor):
    PayrollRun = apps.get_model('payroll', 'PayrollRun')
    duplicates = (
        PayrollRun.objects
        .values('company_id', 'period_start', 'period_end')
        .annotate(row_count=models.Count('id'))
        .filter(row_count__gt=1)
    )
    if duplicates.exists():
        examples = list(duplicates[:5])
        raise RuntimeError(
            'Cannot add unique payroll-period constraint because duplicate payroll runs exist. '
            f'Clean up these company/period combinations first: {examples}'
        )


class Migration(migrations.Migration):
    dependencies = [
        ('payroll', '0002_payrollrun_approved_at_payrollrun_approved_by_and_more'),
    ]

    operations = [
        migrations.RunPython(reject_existing_duplicates, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='payrollrun',
            constraint=models.UniqueConstraint(
                fields=('company', 'period_start', 'period_end'),
                name='unique_company_payroll_period',
            ),
        ),
    ]
