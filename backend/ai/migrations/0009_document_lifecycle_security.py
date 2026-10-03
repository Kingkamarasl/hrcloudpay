from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ai", "0008_knowledge_chunk_locations")]
    operations = [
        migrations.AddField(model_name="knowledgedocument", name="lifecycle_status", field=models.CharField(choices=[("active", "Active"), ("processing", "Processing"), ("failed", "Failed"), ("archived", "Archived")], default="active", max_length=20)),
        migrations.AddField(model_name="knowledgedocument", name="version", field=models.PositiveIntegerField(default=1)),
        migrations.AddField(model_name="knowledgedocument", name="version_group", field=models.UUIDField(blank=True, db_index=True, null=True)),
        migrations.AddField(model_name="knowledgedocument", name="archived_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="knowledgedocument", name="processing_error", field=models.TextField(blank=True)),
        migrations.AddField(model_name="knowledgedocument", name="last_indexed_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="knowledgedocument", name="allowed_roles", field=models.JSONField(blank=True, default=list)),
    ]
