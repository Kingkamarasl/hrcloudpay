from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0027_legal_pages'),
        ('payroll', '0008_payrollconfig_deduct_unpaid_absence'),
    ]

    operations = [
        migrations.CreateModel(
            name='PayrollConfigVersion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('version', models.PositiveIntegerField()),
                ('effective_from', models.DateField()),
                ('snapshot', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='accounts.user')),
                ('payroll_config', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='versions', to='payroll.payrollconfig')),
            ],
            options={'ordering': ['-effective_from', '-version']},
        ),
        migrations.AddField(
            model_name='payrollrun', name='config_version',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='payroll_runs', to='payroll.payrollconfigversion'),
        ),
        migrations.AddField(
            model_name='payrollrun', name='configuration_snapshot',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='payrollrun', name='preview_summary',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='payrollrun', name='previewed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name='payrollconfigversion',
            constraint=models.UniqueConstraint(fields=('payroll_config', 'version'), name='unique_payroll_config_version'),
        ),
    ]
