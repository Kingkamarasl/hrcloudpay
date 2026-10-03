from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [('accounts', '0010_company_address')]

    operations = [
        migrations.CreateModel(
            name='CompanyCountryProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('country_code', models.CharField(choices=[('NG', 'Nigeria'), ('GH', 'Ghana'), ('SL', 'Sierra Leone'), ('LR', 'Liberia'), ('GM', 'The Gambia')], max_length=2)),
                ('currency_code', models.CharField(max_length=3)),
                ('payroll_frequency', models.CharField(default='monthly', max_length=30)),
                ('timezone', models.CharField(blank=True, max_length=64)),
                ('onboarding_completed', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('company', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='country_profile', to='accounts.company')),
            ],
        ),
        migrations.CreateModel(
            name='StatutoryRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('country_code', models.CharField(choices=[('NG', 'Nigeria'), ('GH', 'Ghana'), ('SL', 'Sierra Leone'), ('LR', 'Liberia'), ('GM', 'The Gambia')], max_length=2)),
                ('code', models.CharField(max_length=80)),
                ('name', models.CharField(max_length=160)),
                ('rule_type', models.CharField(max_length=40)),
                ('calculation_method', models.CharField(default='percentage', max_length=60)),
                ('value', models.DecimalField(blank=True, decimal_places=6, max_digits=18, null=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('effective_from', models.DateField()),
                ('effective_to', models.DateField(blank=True, null=True)),
                ('source_reference', models.URLField(blank=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['country_code', 'code', '-effective_from']},
        ),
        migrations.AddIndex(model_name='statutoryrule', index=models.Index(fields=['country_code', 'code', 'effective_from'], name='regional_st_country_8e5b22_idx')),
        migrations.AddIndex(model_name='statutoryrule', index=models.Index(fields=['country_code', 'effective_from', 'effective_to'], name='regional_st_country_3f4b9c_idx')),
    ]
