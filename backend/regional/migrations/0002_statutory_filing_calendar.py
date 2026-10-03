from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('regional', '0001_initial')]

    operations = [
        migrations.CreateModel(
            name='StatutoryFilingRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('country_code', models.CharField(choices=[('NG', 'Nigeria'), ('GH', 'Ghana'), ('SL', 'Sierra Leone'), ('LR', 'Liberia'), ('GM', 'The Gambia')], max_length=2)),
                ('code', models.CharField(max_length=80)),
                ('name', models.CharField(max_length=160)),
                ('authority', models.CharField(max_length=160)),
                ('filing_type', models.CharField(default='statutory', max_length=60)),
                ('frequency', models.CharField(choices=[('monthly', 'Monthly'), ('annual', 'Annual')], default='monthly', max_length=20)),
                ('due_day', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('due_month', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('source_reference', models.URLField(blank=True)),
                ('notes', models.TextField(blank=True)),
                ('effective_from', models.DateField()),
                ('effective_to', models.DateField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['country_code', 'code', '-effective_from']},
        ),
        migrations.CreateModel(
            name='StatutoryFiling',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('period_start', models.DateField()),
                ('period_end', models.DateField()),
                ('due_date', models.DateField()),
                ('status', models.CharField(choices=[('open', 'Open'), ('ready', 'Ready'), ('filed', 'Filed'), ('overdue', 'Overdue')], default='open', max_length=20)),
                ('amount', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('reference', models.CharField(blank=True, max_length=120)),
                ('notes', models.TextField(blank=True)),
                ('filed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='statutory_filings', to='accounts.company')),
                ('payroll_run', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='statutory_filings', to='payroll.payrollrun')),
                ('rule', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='filings', to='regional.statutoryfilingrule')),
            ],
            options={'ordering': ['due_date', 'rule__code']},
        ),
        migrations.AddConstraint(
            model_name='statutoryfilingrule',
            constraint=models.UniqueConstraint(fields=('country_code','code','effective_from'), name='unique_country_filing_rule_effective'),
        ),
        migrations.AddConstraint(
            model_name='statutoryfiling',
            constraint=models.UniqueConstraint(fields=('company','rule','period_start','period_end'), name='unique_company_statutory_filing_period'),
        ),
        migrations.AddIndex(
            model_name='statutoryfilingrule',
            index=models.Index(fields=('country_code','code','effective_from'), name='regional_statu_country_7e65a1_idx'),
        ),
        migrations.AddIndex(
            model_name='statutoryfiling',
            index=models.Index(fields=('company','due_date','status'), name='regional_statu_company_6d7f90_idx'),
        ),
    ]
