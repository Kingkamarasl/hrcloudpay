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


def decrypt_api_key(config):
    try:
        return _fernet().decrypt(config.api_key_encrypted.encode('utf-8')).decode('utf-8')
    except (InvalidToken, ValueError) as exc:
        raise AIConfigurationError('AI provider credentials could not be decrypted. Re-enter the API key in the admin panel.') from exc
