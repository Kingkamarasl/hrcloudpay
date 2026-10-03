import base64, hashlib, hmac, secrets, struct, time
from django.conf import settings
from accounts.secrets import encrypt_secret, decrypt_secret
from accounts.net import client_ip, clean_ip, is_private_ip

def hash_value(value):
    return hashlib.sha256(str(value).encode()).hexdigest()

def new_secret():
    return secrets.token_urlsafe(48)

def totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')

def totp_code(secret, timestamp=None):
    timestamp = int(timestamp or time.time()) // 30
    key = base64.b32decode(secret + '=' * ((8-len(secret)%8)%8), casefold=True)
    digest = hmac.new(key, struct.pack('>Q', timestamp), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = struct.unpack('>I', digest[offset:offset+4])[0] & 0x7fffffff
    return f'{value % 1000000:06d}'

def verify_totp(secret, code, window=1):
    now = int(time.time())
    return any(hmac.compare_digest(totp_code(secret, now + offset*30), str(code)) for offset in range(-window, window+1))

def encrypt_config(data):
    import json
    return encrypt_secret(json.dumps(data, separators=(',', ':')))

def decrypt_config(value):
    import json
    return json.loads(decrypt_secret(value))
