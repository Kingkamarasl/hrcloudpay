from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('ai', '0007_knowledge_document_files')]

    operations = [
        migrations.AddField(
            model_name='knowledgechunk', name='page_number',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='knowledgechunk', name='section_label',
            field=models.CharField(blank=True, max_length=300),
        ),
    ]
