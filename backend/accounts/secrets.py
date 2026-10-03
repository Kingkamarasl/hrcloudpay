import base64, hashlib, os
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

def _keys():
    configured=[x.strip() for x in getattr(settings,'SECRET_ENCRYPTION_KEYS', '').split(',') if x.strip()]
    if configured: return configured
    return [base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest()).decode()]

def _fernet(key):
    raw=key.encode()
    if len(raw)==44: return Fernet(raw)
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw).digest()))

def encrypt_secret(value):
    if not value: return ''
    return _fernet(_keys()[0]).encrypt(value.encode()).decode()

def decrypt_secret(value):
    if not value: return ''
    for key in _keys():
        try: return _fernet(key).decrypt(value.encode()).decode()
        except (InvalidToken, ValueError, TypeError): continue
    raise ValueError('Unable to decrypt secret with configured encryption keys.')

def rotate_secret(value):
    return encrypt_secret(decrypt_secret(value)) if value else ''
