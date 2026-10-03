from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('ai', '0004_chunk_embeddings')]
    operations = [
        migrations.CreateModel(
            name='AIProviderConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(default='nvidia_nim', editable=False, max_length=40)),
                ('display_name', models.CharField(default='NVIDIA NIM', max_length=100)),
                ('api_key_encrypted', models.TextField(blank=True)),
                ('chat_api_url', models.URLField(default='https://integrate.api.nvidia.com/v1/chat/completions')),
                ('embeddings_api_url', models.URLField(default='https://integrate.api.nvidia.com/v1/embeddings')),
                ('chat_model', models.CharField(default='qwen/qwen3.5-122b-a10b', max_length=200)),
                ('embedding_model', models.CharField(default='nvidia/llama-3.2-nemoretriever-300m-embed-v2', max_length=200)),
                ('temperature', models.FloatField(default=0.3)),
                ('max_tokens', models.PositiveIntegerField(default=1200)),
                ('request_timeout_seconds', models.PositiveIntegerField(default=90)),
                ('is_active', models.BooleanField(default=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'verbose_name': 'AI provider configuration', 'verbose_name_plural': 'AI provider configuration'},
        ),
    ]
