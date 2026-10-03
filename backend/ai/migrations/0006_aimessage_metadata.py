from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('ai', '0005_aiproviderconfig')]
    operations = [
        migrations.AddField(
            model_name='aimessage',
            name='metadata',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
