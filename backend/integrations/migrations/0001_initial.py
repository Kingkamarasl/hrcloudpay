from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('accounts', '0009_advanced_platform_admin'),
    ]

    operations = [
        migrations.CreateModel(
            name='IntegrationConnection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(choices=[('quickbooks', 'QuickBooks Online'), ('microsoft365', 'Microsoft 365'), ('xero', 'Xero'), ('google_workspace', 'Google Workspace'), ('api', 'HRCloudPay API')], max_length=40)),
                ('status', models.CharField(choices=[('available', 'Available'), ('connected', 'Connected'), ('attention', 'Needs attention'), ('disconnected', 'Disconnected')], default='available', max_length=20)),
                ('display_name', models.CharField(blank=True, max_length=120)),
                ('external_account_id', models.CharField(blank=True, max_length=255)),
                ('last_synced_at', models.DateTimeField(blank=True, null=True)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='integration_connections', to='accounts.company')),
            ],
            options={'ordering': ['provider']},
        ),
        migrations.CreateModel(
            name='ImportJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_type', models.CharField(choices=[('csv', 'CSV'), ('xlsx', 'Excel workbook')], max_length=20)),
                ('filename', models.CharField(max_length=255)),
                ('uploaded_file', models.FileField(blank=True, null=True, upload_to='imports/%Y/%m/')),
                ('checksum', models.CharField(blank=True, max_length=64)),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('ready', 'Ready to import'), ('importing', 'Importing'), ('completed', 'Completed'), ('completed_with_warnings', 'Completed with warnings'), ('failed', 'Failed'), ('rolled_back', 'Rolled back')], default='draft', max_length=32)),
                ('entity_type', models.CharField(default='employee', max_length=50)),
                ('headers', models.JSONField(blank=True, default=list)),
                ('mapping', models.JSONField(blank=True, default=dict)),
                ('rows', models.JSONField(blank=True, default=list)),
                ('result', models.JSONField(blank=True, default=dict)),
                ('total_rows', models.PositiveIntegerField(default=0)),
                ('valid_rows', models.PositiveIntegerField(default=0)),
                ('warning_rows', models.PositiveIntegerField(default=0)),
                ('error_rows', models.PositiveIntegerField(default=0)),
                ('duplicate_rows', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('rolled_back_at', models.DateTimeField(blank=True, null=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='import_jobs', to='accounts.company')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_import_jobs', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddConstraint(
            model_name='integrationconnection',
            constraint=models.UniqueConstraint(fields=('company', 'provider'), name='unique_integration_provider_per_company'),
        ),
    ]
