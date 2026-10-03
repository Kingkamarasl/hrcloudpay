from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [("integrations", "0001_initial"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name="integrationconnection", name="access_token", field=models.TextField(blank=True)),
        migrations.AddField(model_name="integrationconnection", name="refresh_token", field=models.TextField(blank=True)),
        migrations.AddField(model_name="integrationconnection", name="token_expires_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.CreateModel(name="OAuthState", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("provider", models.CharField(choices=[("quickbooks","QuickBooks Online"),("microsoft365","Microsoft 365"),("xero","Xero"),("google_workspace","Google Workspace"),("api","HRCloudPay API")], max_length=40)),
            ("state_hash", models.CharField(max_length=64, unique=True)), ("expires_at", models.DateTimeField()), ("used_at", models.DateTimeField(blank=True, null=True)), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("company", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="integration_oauth_states", to="accounts.company")),
            ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.CreateModel(name="ExternalRecord", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("entity_type", models.CharField(max_length=80)), ("external_id", models.CharField(max_length=255)), ("local_object_type", models.CharField(blank=True, max_length=100)), ("local_object_id", models.PositiveBigIntegerField(blank=True, null=True)), ("last_synced_at", models.DateTimeField(blank=True, null=True)), ("metadata", models.JSONField(blank=True, default=dict)), ("connection", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="external_records", to="integrations.integrationconnection")),
        ], options={"constraints":[models.UniqueConstraint(fields=("connection","entity_type","external_id"), name="unique_external_record")],"indexes":[models.Index(fields=["connection","entity_type","local_object_id"], name="integrations_connection_idx")] }),
        migrations.CreateModel(name="SyncJob", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("direction", models.CharField(default="import", max_length=30)), ("entity_type", models.CharField(default="employee", max_length=80)), ("status", models.CharField(choices=[("queued","Queued"),("running","Running"),("completed","Completed"),("completed_with_warnings","Completed with warnings"),("failed","Failed")], default="queued", max_length=40)), ("result", models.JSONField(blank=True, default=dict)), ("error_message", models.TextField(blank=True)), ("started_at", models.DateTimeField(blank=True, null=True)), ("completed_at", models.DateTimeField(blank=True, null=True)), ("created_at", models.DateTimeField(auto_now_add=True)), ("connection", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sync_jobs", to="integrations.integrationconnection")), ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
        ], options={"ordering":["-created_at"]}),
    ]
