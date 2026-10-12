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

def clean_secret(value):
    """Normalise a pasted credential before it is encrypted or sent.

    Both payment providers were failing on secrets that were correct apart from
    the whitespace around them. The key is typed into a password field by a
    person copying it out of a dashboard or a .env file, and browsers submit
    whatever was pasted - including the trailing newline, and on Windows the
    carriage return with it. Nothing stripped it: encrypt_secret stored it
    byte-for-byte and decrypt_secret returned it byte-for-byte, so a single
    stray newline travelled all the way into the HTTP header.

    Paddle rejects that with `authentication_malformed` - "Authentication
    header included, but incorrectly formatted" - which is an accurate and
    completely unhelpful error, because the credential was not malformed, only
    wrapped in a newline.

    Two things are removed:

      * surrounding whitespace, including the \\r\\n a Windows paste carries
      * a duplicated `Bearer ` prefix, which arrives when someone copies the
        whole header rather than the token. Without this the request sends
        `Bearer Bearer pdl_...`, which fails the same way.

    Applied at the request as well as on save: a secret pasted before this
    existed is already in the database with its newline attached, and trimming
    only on the way in would make the operator re-enter a credential they
    already had right.
    """
    if not value: return ''
    cleaned=str(value).strip()
    for scheme in ('Bearer ', 'bearer ', 'BEARER '):
        if cleaned.startswith(scheme):
            cleaned=cleaned[len(scheme):].strip()
            break
    return cleaned

def decrypt_secret(value):
    if not value: return ''
    for key in _keys():
        try: return _fernet(key).decrypt(value.encode()).decode()
        except (InvalidToken, ValueError, TypeError): continue
    raise ValueError('Unable to decrypt secret with configured encryption keys.')

def rotate_secret(value):
    return encrypt_secret(decrypt_secret(value)) if value else ''
