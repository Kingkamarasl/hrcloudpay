from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('ai', '0003_knowledge')]
    operations = [
        migrations.AddField(model_name='knowledgechunk', name='embedding', field=models.JSONField(blank=True, null=True)),
        migrations.AddField(model_name='knowledgechunk', name='embedding_model', field=models.CharField(blank=True, max_length=150)),
        migrations.AddField(model_name='knowledgechunk', name='embedded_at', field=models.DateTimeField(blank=True, null=True)),
    ]
