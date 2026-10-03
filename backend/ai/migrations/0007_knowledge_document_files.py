from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ai", "0006_aimessage_metadata")]
    operations = [
        migrations.AddField(model_name="knowledgedocument", name="source_file", field=models.FileField(blank=True, null=True, upload_to="ai_knowledge/%Y/%m/")),
        migrations.AddField(model_name="knowledgedocument", name="file_name", field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(model_name="knowledgedocument", name="file_size", field=models.PositiveBigIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="knowledgedocument", name="mime_type", field=models.CharField(blank=True, max_length=120)),
        migrations.AddField(model_name="knowledgedocument", name="extraction_status", field=models.CharField(choices=[("manual", "Manual content"), ("extracted", "Extracted"), ("failed", "Extraction failed")], default="manual", max_length=30)),
    ]
