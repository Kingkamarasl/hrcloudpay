from django.db import migrations, models
class Migration(migrations.Migration):
    dependencies=[('integrations','0003_sync_marketplace')]
    operations=[migrations.AddIndex(model_name='syncevent',index=models.Index(fields=['connection','processed','created_at'],name='sync_event_queue_idx'))]
