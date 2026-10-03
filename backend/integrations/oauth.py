import base64
import hashlib
import json
import secrets
import urllib.parse
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from accounts.secrets import decrypt_secret, encrypt_secret
from .models import IntegrationConnection, OAuthState

PROVIDERS = {
    'microsoft365': {
        'authorize': 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize',
        'token': 'https://login.microsoftonline.com/common/oauth2/v2.0/token',
        'scopes': 'openid profile email offline_access User.Read User.ReadBasic.All',
        'client_id': 'MICROSOFT_CLIENT_ID', 'client_secret': 'MICROSOFT_CLIENT_SECRET',
    },
    'quickbooks': {
        'authorize': 'https://appcenter.intuit.com/connect/oauth2',
        'token': 'https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer',
        'scopes': 'com.intuit.quickbooks.accounting openid profile email offline_access',
        'client_id': 'QUICKBOOKS_CLIENT_ID', 'client_secret': 'QUICKBOOKS_CLIENT_SECRET',
    },
    'xero': {
        'authorize': 'https://login.xero.com/identity/connect/authorize',
        'token': 'https://identity.xero.com/connect/token',
        'scopes': 'openid profile email offline_access accounting.settings accounting.manualjournals',
        'client_id': 'XERO_CLIENT_ID', 'client_secret': 'XERO_CLIENT_SECRET',
    },
}


def _setting(name, default=''):
    return getattr(settings, name, default) or ''

def provider_credentials(provider):
    from .models import IntegrationProviderConfig
    from accounts.secrets import decrypt_secret
    cfg = IntegrationProviderConfig.objects.filter(provider=provider, enabled=True).first()
    if cfg and cfg.client_id and cfg.encrypted_client_secret:
        return cfg.client_id, decrypt_secret(cfg.encrypted_client_secret)
    meta = PROVIDERS.get(provider, {})
    return _setting(meta.get('client_id','')), _setting(meta.get('client_secret',''))


def redirect_uri(provider):
    return f"{_setting('FRONTEND_URL').rstrip('/')}/integrations?oauth={provider}"


def callback_uri(provider):
    return f"{_setting('BACKEND_PUBLIC_URL', _setting('FRONTEND_URL')).rstrip('/')}/api/integrations/oauth/{provider}/callback/"


def build_authorize_url(provider, state):
    cfg = PROVIDERS[provider]
    client_id, _secret = provider_credentials(provider)
    if not client_id:
        raise ValueError(f'{provider} is not configured on this server. Add the OAuth client ID and secret in environment settings (see .env.example), then restart the backend.')
    params = {
        'client_id': client_id,
        'response_type': 'code',
        'redirect_uri': callback_uri(provider),
        'response_mode': 'query',
        'scope': cfg['scopes'],
        'state': state,
    }
    if provider == 'microsoft365':
        params['prompt'] = 'select_account'
    return cfg['authorize'] + '?' + urllib.parse.urlencode(params)


def _post_form(url, data, basic_auth=None):
    payload = urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
    if basic_auth:
        raw = f'{basic_auth[0]}:{basic_auth[1]}'.encode()
        request.add_header('Authorization', 'Basic ' + base64.b64encode(raw).decode())
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode())
    except Exception as exc:
        raise ValueError(f'Provider token request failed: {exc}') from exc


def exchange_code(provider, code):
    cfg = PROVIDERS[provider]
    client_id, client_secret = provider_credentials(provider)
    if not client_id or not client_secret:
        raise ValueError(f'{provider} OAuth credentials are missing. Set the client ID and secret in your environment, then restart the server.')
    data = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': callback_uri(provider)}
    # QuickBooks and Xero expect client authentication; Microsoft accepts secret in the body.
    if provider in ('quickbooks', 'xero'):
        result = _post_form(cfg['token'], data, basic_auth=(client_id, client_secret))
    else:
        data.update({'client_id': client_id, 'client_secret': client_secret})
        result = _post_form(cfg['token'], data)
    if not result.get('access_token'):
        raise ValueError('Provider did not return an access token.')
    return result


def create_connection(company, provider, token_data, created_by=None, external_account_id='', display_name=''):
    connection, _ = IntegrationConnection.objects.get_or_create(company=company, provider=provider)
    connection.status = 'connected'
    connection.external_account_id = external_account_id[:255]
    connection.display_name = display_name[:120]
    connection.metadata = {
        **(connection.metadata or {}),
        'scope': token_data.get('scope', ''),
        'token_type': token_data.get('token_type', 'Bearer'),
        'connected_by': getattr(created_by, 'id', None),
    }
    connection.access_token = encrypt_secret(token_data.get('access_token', ''))
    connection.refresh_token = encrypt_secret(token_data.get('refresh_token', ''))
    expires = token_data.get('expires_in')
    connection.token_expires_at = timezone.now() + timedelta(seconds=int(expires)) if expires else None
    connection.save()
    return connection


def _get_json(url, token):
    request = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode())
    except Exception as exc:
        raise ValueError(f'Provider API request failed: {exc}') from exc


def refresh_access_token(connection):
    if not connection.refresh_token:
        raise ValueError('This connection has no refresh token. Reconnect the integration.')
    cfg = PROVIDERS[connection.provider]
    client_id, client_secret = provider_credentials(connection.provider)
    refresh_token = decrypt_secret(connection.refresh_token)
    data = {'grant_type': 'refresh_token', 'refresh_token': refresh_token}
    if connection.provider in ('quickbooks', 'xero'):
        result = _post_form(cfg['token'], data, basic_auth=(client_id, client_secret))
    else:
        data.update({'client_id': client_id, 'client_secret': client_secret})
        result = _post_form(cfg['token'], data)
    connection.access_token = encrypt_secret(result['access_token'])
    if result.get('refresh_token'):
        connection.refresh_token = encrypt_secret(result['refresh_token'])
    if result.get('expires_in'):
        connection.token_expires_at = timezone.now() + timedelta(seconds=int(result['expires_in']))
    connection.save(update_fields=['access_token','refresh_token','token_expires_at','updated_at'])
    return result['access_token']


def valid_access_token(connection):
    if not connection.access_token:
        raise ValueError('Integration is not connected.')
    if connection.token_expires_at and connection.token_expires_at <= timezone.now() + timedelta(minutes=2):
        return refresh_access_token(connection)
    return decrypt_secret(connection.access_token)


def fetch_microsoft_users(connection):
    token = valid_access_token(connection)
    url = 'https://graph.microsoft.com/v1.0/users?$select=id,displayName,givenName,surname,mail,userPrincipalName,jobTitle,mobilePhone,accountEnabled&$top=999'
    users = []
    while url:
        data = _get_json(url, token)
        users.extend(data.get('value', []))
        url = data.get('@odata.nextLink')
    return users


def fetch_provider_identity(provider, token_data):
    token = token_data.get('access_token')
    if provider == 'quickbooks':
        return _get_json('https://accounts.platform.intuit.com/v1/openid_connect/userinfo', token)
    if provider == 'xero':
        return {'connections': _get_json('https://api.xero.com/connections', token)}
    if provider == 'microsoft365':
        return _get_json('https://graph.microsoft.com/v1.0/me?$select=id,displayName,mail,userPrincipalName', token)
    return {}


def _post_json(url, token, payload, headers=None):
    body=json.dumps(payload).encode()
    request=urllib.request.Request(url, data=body, headers={'Authorization':f'Bearer {token}','Accept':'application/json','Content-Type':'application/json', **(headers or {})}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw=response.read().decode()
            return json.loads(raw) if raw else {}
    except Exception as exc:
        raise ValueError(f'Provider API request failed: {exc}') from exc


def provider_get(connection, url, headers=None):
    token=valid_access_token(connection)
    request=urllib.request.Request(url, headers={'Authorization':f'Bearer {token}','Accept':'application/json', **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except Exception as exc:
        raise ValueError(f'Provider API request failed: {exc}') from exc


def provider_post(connection, url, payload, headers=None):
    return _post_json(url, valid_access_token(connection), payload, headers=headers)


def quickbooks_base(connection):
    base='https://sandbox-quickbooks.api.intuit.com' if connection.environment == 'sandbox' else 'https://quickbooks.api.intuit.com'
    if not connection.external_account_id:
        raise ValueError('QuickBooks company/realm ID is missing. Reconnect the integration.')
    return f'{base}/v3/company/{connection.external_account_id}'


def quickbooks_accounts(connection):
    query=urllib.parse.quote('select * from Account maxresults 1000')
    return provider_get(connection, f'{quickbooks_base(connection)}/query?query={query}')


def quickbooks_create_journal(connection, payload):
    return provider_post(connection, f'{quickbooks_base(connection)}/journalentry', payload)


def xero_connections(connection):
    return provider_get(connection, 'https://api.xero.com/connections')


def xero_accounts(connection):
    if not connection.external_account_id:
        raise ValueError('Xero tenant ID is missing. Reconnect the integration.')
    return provider_get(connection, 'https://api.xero.com/api.xro/2.0/Accounts', headers={'Xero-tenant-id':connection.external_account_id})


def xero_create_manual_journal(connection, payload):
    if not connection.external_account_id:
        raise ValueError('Xero tenant ID is missing. Reconnect the integration.')
    return provider_post(connection, 'https://api.xero.com/api.xro/2.0/ManualJournals', payload, headers={'Xero-tenant-id':connection.external_account_id})
