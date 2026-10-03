"""Best-effort IP geolocation for the caller's own connection.

Only ever used to describe the address the request arrived from, so the lookup is
deliberately defensive:

* private, loopback and reserved addresses short-circuit - there is no useful
  answer for them and sending them to a third party is pointless;
* a short timeout, because this sits on a dashboard request that must not hang;
* cached per address, so a busy office does not spend the provider's quota on
  every page load;
* it never raises. A provider outage degrades the dashboard card to "unavailable"
  and leaves the IP address itself, which needs no network, intact.

Every result carries ``checked_at`` - when the answer was actually verified - so
a cached hit can honestly report how old it is, and a forced refresh can be
rate limited instead of letting a client spend provider quota at will.
"""
import ipaddress
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .utils import is_private_ip

logger = logging.getLogger(__name__)

DEFAULT_LOOKUP_URL = 'https://ipwho.is/{ip}'
CACHE_PREFIX = 'ai:ipgeo:'
CACHE_TTL_SECONDS = 24 * 60 * 60
# Short on purpose: this is one line on a dashboard, not the page's main work.
DEFAULT_TIMEOUT_SECONDS = 3.0
# A cached entry is already correct for a day, so a manual refresh is about
# reassurance rather than accuracy. Bounding it keeps a client (or a stuck
# retry loop) from turning the card into a way to burn the provider's quota.
FORCE_REFRESH_PREFIX = 'ai:ipgeo:forced:'
DEFAULT_FORCE_REFRESH_MIN_INTERVAL_SECONDS = 30

SOURCE_LIVE = 'live'
SOURCE_CACHE = 'cache'
SOURCE_PRIVATE = 'private'
SOURCE_UNAVAILABLE = 'unavailable'


def _now():
    return timezone.now().isoformat()


def _blank(ip_address, source, checked_at):
    return {
        'ip_address': ip_address,
        'country': '',
        'country_code': '',
        'region': '',
        'city': '',
        'isp': '',
        'asn': '',
        'domain': '',
        'source': source,
        'checked_at': checked_at,
    }


def _extract(payload, ip_address, checked_at):
    """Map a provider response onto our shape, tolerating field differences.

    Two provider layouts are in use, and both are probed so that switching
    provider is a configuration change rather than a code change:

    * ipwho.is (the default) - ``country``/``country_code``/``region``/``city`` at
      the top level and the network operator under ``connection.isp``.
    * IPGeolocation.io v3 - every location field one level down under ``location``
      (``country_name``, ``country_code2``, ``state_prov``) and the network
      operator at ``asn.organization``. ``network`` and ``company`` only arrive on
      paid plans, so the ASN domain is optional.
    """
    if not isinstance(payload, dict):
        return None
    # ipwho.is nests the network operator; several alternatives put it at the top
    # level, so both are accepted.
    connection = payload.get('connection') if isinstance(payload.get('connection'), dict) else {}
    # IPGeolocation.io returns `asn` as an object rather than an identifier.
    # Resolving it to a dict first is what stops `asn` being rendered by str() and
    # sliced to 20 characters, which produced "{'as_number': 'AS1257'" on screen.
    asn = payload.get('asn') if isinstance(payload.get('asn'), dict) else {}
    company = payload.get('company') if isinstance(payload.get('company'), dict) else {}
    location = payload.get('location') if isinstance(payload.get('location'), dict) else {}
    country = payload.get('country') or location.get('country_name') or ''
    if not country and isinstance(payload.get('country_name'), str):
        country = payload['country_name']
    isp = (
        connection.get('isp') or payload.get('isp')
        or asn.get('organization') or company.get('name')
        or connection.get('org') or payload.get('org') or ''
    )
    if not country and not isp:
        return None
    return {
        'ip_address': ip_address,
        'country': str(country).strip()[:100],
        'country_code': str(
            payload.get('country_code') or payload.get('countryCode')
            or location.get('country_code2') or ''
        )[:8],
        'region': str(payload.get('region') or location.get('state_prov') or '')[:100],
        'city': str(payload.get('city') or location.get('city') or '')[:100],
        'isp': str(isp).strip()[:200],
        'asn': str(connection.get('asn') or asn.get('as_number') or '')[:20],
        'domain': str(
            connection.get('domain') or asn.get('domain') or company.get('domain') or ''
        )[:200],
        'source': SOURCE_LIVE,
        'checked_at': checked_at,
    }


def _fetch(ip_address, checked_at):
    template = getattr(settings, 'IP_GEOLOCATION_URL', None) or DEFAULT_LOOKUP_URL
    url = template.format(ip=urllib.parse.quote(ip_address, safe=''))
    timeout = getattr(settings, 'IP_GEOLOCATION_TIMEOUT_SECONDS', DEFAULT_TIMEOUT_SECONDS)
    request = urllib.request.Request(url, headers={
        'Accept': 'application/json',
        'User-Agent': 'HRCloudPay/1.0 (+ip-geolocation)',
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        logger.info('IP geolocation provider returned HTTP %s', exc.code)
        return None
    except (urllib.error.URLError, TimeoutError) as exc:
        logger.info('IP geolocation provider unreachable: %s', exc)
        return None
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        logger.info('IP geolocation provider returned an unreadable body: %s', exc)
        return None
    return _extract(payload, ip_address, checked_at)


def _force_refresh_allowed(user_id):
    """Claim the refresh slot for this user, atomically.

    ``cache.add`` only succeeds when the key is absent, so two clicks arriving
    together cannot both win the slot.
    """
    if not user_id:
        return True
    interval = getattr(settings, 'CONNECTION_REFRESH_MIN_INTERVAL_SECONDS',
                        DEFAULT_FORCE_REFRESH_MIN_INTERVAL_SECONDS)
    if interval <= 0:
        return True
    return bool(cache.add(f'{FORCE_REFRESH_PREFIX}{user_id}', 1, interval))


def describe_ip(ip_address, force_refresh=False, user_id=None):
    """Resolve an address to location details, or a blank result. Never raises.

    ``force_refresh`` bypasses the cache but is rate limited per user. When the
    limit is hit the cached answer is returned with ``refresh_throttled`` set, so
    the caller can say so rather than silently appearing to do nothing.
    """
    ip_address = (ip_address or '').strip()
    checked_at = _now()
    if not ip_address:
        return _blank('', SOURCE_UNAVAILABLE, checked_at)
    try:
        ipaddress.ip_address(ip_address)
    except ValueError:
        return _blank('', SOURCE_UNAVAILABLE, checked_at)
    if is_private_ip(ip_address):
        # Nothing to look up, so a forced refresh must not spend quota either.
        result = _blank(ip_address, SOURCE_PRIVATE, checked_at)
        result['refresh_throttled'] = False
        return result

    key = CACHE_PREFIX + ip_address
    cached = cache.get(key)

    if force_refresh and not _force_refresh_allowed(user_id):
        result = dict(cached) if cached else _blank(ip_address, SOURCE_UNAVAILABLE, checked_at)
        result['source'] = SOURCE_CACHE if cached else SOURCE_UNAVAILABLE
        result['refresh_throttled'] = True
        return result

    if cached is not None and not force_refresh:
        result = dict(cached)
        result['source'] = SOURCE_CACHE
        result['refresh_throttled'] = False
        return result

    checked_at = _now()
    fetched = _fetch(ip_address, checked_at)
    if fetched is None:
        # Not cached: the failure is probably not per-address, and caching it
        # would make an outage stick for the whole TTL.
        result = _blank(ip_address, SOURCE_UNAVAILABLE, checked_at)
        result['refresh_throttled'] = False
        return result

    cache.set(key, fetched, CACHE_TTL_SECONDS)
    fetched['refresh_throttled'] = False
    return fetched
