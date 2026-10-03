from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0001_initial'),
        ('payroll', '0001_initial'),
        ('regional', '0002_statutory_filing_calendar'),
    ]

    operations = [
        migrations.CreateModel(
            name='StatutoryCompliancePack',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('country_code', models.CharField(choices=[('NG','Nigeria'),('GH','Ghana'),('SL','Sierra Leone'),('LR','Liberia'),('GM','The Gambia')], max_length=2)),
                ('period_start', models.DateField()),
                ('period_end', models.DateField()),
                ('status', models.CharField(choices=[('draft','Draft'),('ready','Ready for Filing'),('submitted','Submitted'),('closed','Closed')], default='draft', max_length=20)),
                ('filing_count', models.PositiveIntegerField(default=0)),
                ('report_count', models.PositiveIntegerField(default=0)),
                ('generated_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('submitted_at', models.DateTimeField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='statutory_compliance_packs', to='accounts.company')),
                ('payroll_run', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='statutory_compliance_pack', to='payroll.payrollrun')),
            ],
            options={'ordering': ['-period_end','-generated_at']},
        ),
        migrations.AddConstraint(
            model_name='statutorycompliancepack',
            constraint=models.UniqueConstraint(fields=('company','payroll_run'), name='unique_company_compliance_pack_run'),
        ),
    ]
