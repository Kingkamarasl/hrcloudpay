from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

from .models import AIProviderConfig


class AIConfigurationError(Exception):
    pass


def _fernet():
    secret = getattr(settings, 'SECRET_KEY', '')
    if not secret:
        raise AIConfigurationError('Django SECRET_KEY is required to protect AI credentials.')
    # Derive a stable Fernet key from the Django secret without storing another secret.
    import base64
    import hashlib
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode('utf-8')).digest())
    return Fernet(key)


def get_active_config():
    config = AIProviderConfig.objects.filter(is_active=True).first()
    if not config:
        raise AIConfigurationError('AI provider is not configured. A site administrator must configure it in the admin panel.')
    if not config.api_key_encrypted:
        raise AIConfigurationError('AI provider API key is missing. A site administrator must configure it in the admin panel.')
    return config


def get_embeddings_config():
    """A configuration that can actually produce embeddings.

    Deliberately not ``get_active_config()``. OpenRouter publishes chat
    completions and no embedding model at all, so an installation that points
    chat at it has - by doing the right thing - lost its embedding provider. If
    this simply reused the active configuration, the first knowledge-base index
    would fail with an HTTP 404 from a URL that never existed, which reads as a
    provider outage rather than as a missing capability.

    So the active configuration is used when it can embed, and otherwise the most
    recently updated configuration that can is. An admin who wants Claude for
    chat keeps an NVIDIA row configured and this keeps returning it.

    Raises rather than returning None: the callers all need a usable config, and
    a message naming the fix is more use than a NoneType traceback.
    """
    active = AIProviderConfig.objects.filter(is_active=True).first()
    if active is not None and active.provides_embeddings:
        if active.api_key_encrypted:
            return active
    fallback = (
        AIProviderConfig.objects
        .filter(provides_embeddings=True)
        .exclude(api_key_encrypted='')
        .order_by('-updated_at')
        .first()
    )
    if fallback is not None:
        return fallback
    raise AIConfigurationError(
        'No AI provider that can produce embeddings is configured. OpenRouter '
        'serves chat only, so an installation using it for chat still needs an '
        'embedding provider (NVIDIA NIM ships one) configured under Platform '
        'Admin -> AI / NVIDIA NIM before the knowledge base can be indexed.'
    )


def decrypt_api_key(config):
    try:
        return _fernet().decrypt(config.api_key_encrypted.encode('utf-8')).decode('utf-8')
    except (InvalidToken, ValueError) as exc:
        raise AIConfigurationError('AI provider credentials could not be decrypted. Re-enter the API key in the admin panel.') from exc
