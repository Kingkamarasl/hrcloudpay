"""
Move provider rows off NVIDIA models that have reached end of life.

Both models this app originally shipped with were retired by NVIDIA on
2026-07-20 and now answer HTTP 410 "Gone":

    qwen/qwen3.5-122b-a10b
    nvidia/llama-3.2-nemoretriever-300m-embed-v2

The field-default change in 0011 only helps rows created from now on, so an
already-provisioned workspace keeps calling a dead model. This rewrites *only*
those exact retired ids - an operator who deliberately chose some other model
keeps it, because guessing at or overriding a custom choice would be worse than
leaving it alone.

Verify the replacements before relying on them; the current values were confirmed
against the live NVIDIA catalog, including a real tool-calling request and a real
embeddings request.
"""
from django.db import migrations

RETIRED_CHAT_MODELS = {
    'qwen/qwen3.5-122b-a10b': 'nvidia/nemotron-3-super-120b-a12b',
}
RETIRED_EMBEDDING_MODELS = {
    'nvidia/llama-3.2-nemoretriever-300m-embed-v2': 'nvidia/nemotron-3-embed-1b',
}


def move_to_live_models(apps, schema_editor):
    config = apps.get_model('ai', 'AIProviderConfig')
    for old, new in RETIRED_CHAT_MODELS.items():
        config.objects.filter(chat_model=old).update(chat_model=new)
    for old, new in RETIRED_EMBEDDING_MODELS.items():
        config.objects.filter(embedding_model=old).update(embedding_model=new)


def noop(apps, schema_editor):
    """Reversible: the retired ids are not restored, because they no longer work."""


class Migration(migrations.Migration):

    dependencies = [
        ('ai', '0011_alter_aiproviderconfig_chat_model_and_more'),
    ]

    operations = [
        migrations.RunPython(move_to_live_models, noop),
    ]
