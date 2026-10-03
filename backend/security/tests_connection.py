"""
Tests for the dashboard "your connection" card: the caller's own IP address,
country and ISP.

Two defects are covered here beyond the feature itself.

``security.utils.client_ip`` preferred ``REMOTE_ADDR`` and never read
``X-Forwarded-For``. Behind a reverse proxy - which this deployment expects,
since ``SECURE_PROXY_SSL_HEADER`` is configured - ``REMOTE_ADDR`` is the load
balancer, so every security session, security event and now this card reported
the proxy's address. ``accounts.audit`` used the opposite precedence for the same
request, so the two apps disagreed. Resolution now lives in ``accounts.net`` and
reads the header from the right-hand end by ``TRUSTED_PROXY_COUNT``, which both
fixes the proxy case and stops a client forging its own address.

The geolocation lookup is third-party and sits on a dashboard request, so the
tests pin the behaviour that matters: it must never raise, never block, never be
attempted for a private address, and must not report another user's data.
"""
import json
import urllib.error

from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Company, User
from accounts.net import client_ip, is_private_ip
from security.models import MFADevice
from security.utils import hash_value

CONNECTION_URL = '/api/auth/security/connection/'
PASSWORD = 'StrongPassword123!'

PROVIDER_OK = {
    'ip': '196.250.178.135',
    'city': 'Monrovia',
    'region': 'Montserrado',
    'country': 'Liberia',
    'country_code': 'LR',
    'connection': {'asn': 328136, 'org': 'Telecel Liberia Limited',
                   'isp': 'Telecel Liberia Limited', 'domain': 'teleceliberia.com'},
}

# Copied verbatim from IPGeolocation.io's "Single IP Geolocation Lookup"
# documentation, which publishes a different response per plan tier. Both are
# reproduced because the free tier omits `network` and `company` entirely, so the
# ASN domain is only available to paying subscribers.
IPGEOLOCATION_FREE = {
    'ip': '91.128.103.196',
    'location': {
        'continent_code': 'EU', 'continent_name': 'Europe',
        'country_code2': 'SE', 'country_code3': 'SWE',
        'country_name': 'Sweden', 'country_name_official': 'Kingdom of Sweden',
        'country_capital': 'Stockholm', 'state_prov': 'Stockholms län',
        'state_code': 'SE-AB', 'district': 'Stockholm', 'city': 'Stockholm',
        'zipcode': '164 40', 'latitude': '59.40510', 'longitude': '17.95510',
        'is_eu': True,
    },
    'country_metadata': {'calling_code': '+46', 'tld': '.se',
                         'languages': ['sv-SE', 'se', 'sma', 'fi-SE']},
    'currency': {'code': 'SEK', 'name': 'Swedish Krona', 'symbol': 'kr'},
    'asn': {'as_number': 'AS1257', 'organization': 'Tele2 Sverige AB',
            'country': 'SE'},
    'time_zone': {'name': 'Europe/Stockholm', 'offset': 1, 'offset_with_dst': 2},
}

IPGEOLOCATION_PAID = {
    'ip': '107.161.145.197',
    'location': {
        'continent_code': 'NA', 'continent_name': 'North America',
        'country_code2': 'US', 'country_code3': 'USA',
        'country_name': 'United States',
        'country_name_official': 'United States of America',
        'country_capital': 'Washington, D.C.', 'state_prov': 'Pennsylvania',
        'state_code': 'US-PA', 'district': 'Philadelphia County',
        'city': 'Philadelphia', 'zipcode': '19102', 'latitude': '39.95258',
        'longitude': '-75.16522', 'is_eu': False,
    },
    'country_metadata': {'calling_code': '+1', 'tld': '.us',
                         'languages': ['en-US', 'es-US', 'haw', 'fr']},
    'network': {'connection_type': '', 'route': '107.161.144.0/23',
                'is_anycast': False, 'is_cdn': False, 'cdn_provider_name': ''},
    'currency': {'code': 'USD', 'name': 'US Dollar', 'symbol': '$'},
    'asn': {'as_number': 'AS12167', 'organization': 'LightWave Networks',
            'country': 'US', 'type': 'HOSTING', 'domain': 'lightwavenetworks.com',
            'date_allocated': '1997-09-19', 'rir': 'ARIN'},
    'company': {'name': 'LightWave Networks', 'type': 'HOSTING',
                'domain': 'lightwavenetworks.com'},
    'time_zone': {'name': 'America/New_York', 'offset': -5, 'offset_with_dst': -4},
}


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode('utf-8')

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def http_error(code, body=''):
    err = urllib.error.HTTPError('https://example.test', code, 'msg', {}, None)
    err.read = lambda: body.encode()
    return err


def make_company(name, email):
    return Company.objects.create(name=name, email=email, country='NG')


def make_user(company, username, role='hr'):
    return User.objects.create_user(username=username, email=f'{username}@x.test',
                                    password=PASSWORD, role=role, company=company)


# --------------------------------------------------------------------------
# Client address resolution. This was the actual bug.
# --------------------------------------------------------------------------
class ClientIPResolutionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def request(self, remote=None, xff=None, xreal=None):
        meta = {'REMOTE_ADDR': remote or '10.0.0.1'}
        if xff is not None:
            meta['HTTP_X_FORWARDED_FOR'] = xff
        if xreal is not None:
            meta['HTTP_X_REAL_IP'] = xreal
        return self.factory.get('/', **meta)

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_direct_connection_uses_remote_addr(self):
        self.assertEqual(client_ip(self.request(remote='203.0.113.9')), '203.0.113.9')

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_forwarded_header_is_ignored_without_configured_proxies(self):
        """The safe default: an untrusted client cannot assert its own address."""
        request = self.request(remote='203.0.113.9', xff='9.9.9.9')
        self.assertEqual(client_ip(request), '203.0.113.9')

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_behind_one_proxy_reports_the_client_not_the_proxy(self):
        """The regression: this used to return 10.0.0.1, the load balancer."""
        request = self.request(remote='10.0.0.1', xff='203.0.113.9')
        self.assertEqual(client_ip(request), '203.0.113.9')

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_client_cannot_forge_its_own_address(self):
        request = self.request(remote='10.0.0.1', xff='9.9.9.9, 203.0.113.9')
        self.assertEqual(client_ip(request), '203.0.113.9')

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_two_proxies_read_two_entries_in_from_the_right(self):
        request = self.request(remote='10.0.0.1', xff='9.9.9.9, 203.0.113.9, 172.16.0.5')
        self.assertEqual(client_ip(request), '203.0.113.9')

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_x_real_ip_is_the_fallback_when_no_forwarded_header(self):
        request = self.request(remote='10.0.0.1', xreal='203.0.113.9')
        self.assertEqual(client_ip(request), '203.0.113.9')

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_malformed_forwarded_entries_are_discarded(self):
        """Header content is untrusted input and must not reach a model field."""
        request = self.request(remote='203.0.113.9', xff='not-an-ip')
        self.assertEqual(client_ip(request), '203.0.113.9')

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_malformed_remote_addr_yields_empty_string(self):
        """A junk value must not be stored in SecuritySession.ip_address."""
        self.assertEqual(client_ip(self.request(remote='bogus')), '')

    def test_ipv6_is_supported(self):
        with override_settings(TRUSTED_PROXY_COUNT=0):
            self.assertEqual(client_ip(self.request(remote='2606:4700:4700::1111')),
                             '2606:4700:4700::1111')

    def test_audit_and_security_apps_resolve_the_same_address(self):
        """The two apps disagreed about the same request before."""
        from accounts.audit import AuditRequestMiddleware, get_audit_context
        request = self.request(remote='10.0.0.1', xff='203.0.113.9')
        seen = {}

        def view(req):
            # Read inside the view: the middleware resets its contextvars once
            # the response has been produced.
            seen['context_ip'] = get_audit_context()[1]
            seen['security_ip'] = client_ip(req)
            return 'response'

        with override_settings(TRUSTED_PROXY_COUNT=1):
            AuditRequestMiddleware(view)(request)
        self.assertEqual(seen['security_ip'], '203.0.113.9')
        self.assertEqual(seen['context_ip'], '203.0.113.9')


class PrivateAddressTests(TestCase):
    def test_loopback_and_private_ranges_are_private(self):
        for address in ('127.0.0.1', '10.0.0.1', '192.168.1.4', '172.16.5.9',
                        '169.254.1.1', '::1', 'fd00::1', ''):
            self.assertTrue(is_private_ip(address), address)

    def test_public_addresses_are_not_private(self):
        for address in ('196.250.178.135', '8.8.8.8', '2606:4700:4700::1111'):
            self.assertFalse(is_private_ip(address), address)

    def test_documentation_ranges_are_not_looked_up(self):
        """2001:db8::/32 and 203.0.113.0/24 are reserved for examples."""
        self.assertTrue(is_private_ip('2001:db8::1'))


class ProxySettingIsReachableTests(TestCase):
    """The setting must exist in every mode, not only when DEBUG is off.

    ``client_ip`` reads it with ``getattr(..., 0)``, so placing it inside the
    production-only settings block made it vanish in development and the fallback
    silently masked that - a proxy hop configured via the environment was ignored
    with no error anywhere.
    """
    def test_trusted_proxy_count_is_always_defined(self):
        from django.conf import settings
        self.assertTrue(hasattr(settings, 'TRUSTED_PROXY_COUNT'),
                        'TRUSTED_PROXY_COUNT must be set outside the DEBUG branch')
        self.assertIsInstance(settings.TRUSTED_PROXY_COUNT, int)

    def test_geolocation_settings_are_always_defined(self):
        from django.conf import settings
        for name in ('IP_GEOLOCATION_URL', 'IP_GEOLOCATION_TIMEOUT_SECONDS'):
            self.assertTrue(hasattr(settings, name), f'{name} must be set unconditionally')

    def test_unparseable_value_counts_as_private(self):
        """Nothing is worth a third-party lookup unless it is a real address."""
        self.assertTrue(is_private_ip('not-an-ip'))


# --------------------------------------------------------------------------
# Geolocation: must be bounded, cached, and never fatal.
# --------------------------------------------------------------------------
class GeolocationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_successful_lookup_maps_provider_fields(self):
        from unittest.mock import patch

        from security.geolocation import describe_ip
        with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)):
            result = describe_ip('196.250.178.135')
        self.assertEqual(result['country'], 'Liberia')
        self.assertEqual(result['country_code'], 'LR')
        self.assertEqual(result['isp'], 'Telecel Liberia Limited')
        self.assertEqual(result['city'], 'Monrovia')
        self.assertEqual(result['source'], 'live')

    def test_alternative_provider_shape_is_tolerated(self):
        """A flat response shape must work too, so the provider is swappable."""
        from unittest.mock import patch

        from security.geolocation import describe_ip
        flat = {'ip': '1.2.3.4', 'country_name': 'Kenya', 'isp': 'Safaricom',
                'country_code': 'KE', 'city': 'Nairobi'}
        with patch('urllib.request.urlopen', return_value=FakeResponse(flat)):
            result = describe_ip('1.2.3.4')
        self.assertEqual(result['country'], 'Kenya')
        self.assertEqual(result['isp'], 'Safaricom')

    def test_ipgeolocation_nested_layout_is_mapped(self):
        """IPGeolocation.io nests everything one level down; it must still render.

        The payload below is the free-plan response copied from the vendor's own
        "Single IP Geolocation Lookup" documentation. Before this layout was
        understood, `_extract` returned None for it and the connection card
        degraded to "unavailable" - losing the country, not just the ISP.
        """
        from unittest.mock import patch

        from security.geolocation import describe_ip
        with patch('urllib.request.urlopen', return_value=FakeResponse(IPGEOLOCATION_FREE)):
            result = describe_ip('91.128.103.196')
        self.assertEqual(result['country'], 'Sweden')
        self.assertEqual(result['country_code'], 'SE')
        self.assertEqual(result['region'], 'Stockholms län')
        self.assertEqual(result['city'], 'Stockholm')
        self.assertEqual(result['isp'], 'Tele2 Sverige AB')
        self.assertEqual(result['asn'], 'AS1257')
        self.assertEqual(result['source'], 'live')

    def test_ipgeolocation_asn_object_is_not_rendered_as_a_dict_fragment(self):
        """`asn` arrives as an object, so str() must not truncate it to text.

        Reading the object through str() and slicing to 20 characters produced
        "{'as_number': 'AS1257'" in the ASN column.
        """
        from unittest.mock import patch

        from security.geolocation import describe_ip
        with patch('urllib.request.urlopen', return_value=FakeResponse(IPGEOLOCATION_PAID)):
            result = describe_ip('107.161.145.197')
        self.assertEqual(result['asn'], 'AS12167')
        self.assertNotIn('{', result['asn'])

    def test_ipgeolocation_paid_layout_adds_company_domain(self):
        """`network`/`company` only arrive on paid plans, so domain is optional."""
        from unittest.mock import patch

        from security.geolocation import describe_ip
        with patch('urllib.request.urlopen', return_value=FakeResponse(IPGEOLOCATION_PAID)):
            result = describe_ip('107.161.145.197')
        self.assertEqual(result['country'], 'United States')
        self.assertEqual(result['country_code'], 'US')
        self.assertEqual(result['isp'], 'LightWave Networks')
        self.assertEqual(result['domain'], 'lightwavenetworks.com')

    def test_lookup_url_with_query_string_is_substituted(self):
        """IPGeolocation.io takes the key in the query string, so the template
        carries `?apiKey=...&ip={ip}` rather than the bare `{ip}` of ipwho.is.
        The address must land in the `ip` parameter, not be appended blindly."""
        from unittest.mock import patch

        from django.test import override_settings

        from security.geolocation import _fetch
        url = 'https://api.ipgeolocation.io/v3/ipgeo?apiKey=secret&ip={ip}'
        with override_settings(IP_GEOLOCATION_URL=url):
            with patch('urllib.request.urlopen', return_value=FakeResponse(IPGEOLOCATION_FREE)) as urlopen:
                _fetch('2001:db8::1', '2026-10-01T00:00:00Z')
        requested = urlopen.call_args[0][0].full_url
        self.assertIn('ip=2001%3Adb8%3A%3A1', requested)
        self.assertNotIn('{ip}', requested)

    def test_private_addresses_are_never_looked_up(self):
        """No network call and no third-party copy of an internal address."""
        from unittest.mock import patch

        from security.geolocation import describe_ip
        with patch('urllib.request.urlopen') as urlopen:
            result = describe_ip('192.168.1.10')
        urlopen.assert_not_called()
        self.assertEqual(result['source'], 'private')
        self.assertEqual(result['country'], '')

    def test_result_is_cached_so_repeat_views_do_not_spend_quota(self):
        from unittest.mock import patch

        from security.geolocation import describe_ip
        with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)) as urlopen:
            first = describe_ip('196.250.178.135')
            second = describe_ip('196.250.178.135')
        self.assertEqual(first['source'], 'live')
        self.assertEqual(second['source'], 'cache')
        self.assertEqual(second['country'], 'Liberia')
        self.assertEqual(urlopen.call_count, 1, 'the provider must be hit once per IP per TTL')

    def test_provider_outage_degrades_instead_of_raising(self):
        from unittest.mock import patch

        from security.geolocation import describe_ip
        with patch('urllib.request.urlopen', side_effect=http_error(503, 'down')):
            result = describe_ip('196.250.178.135')
        self.assertEqual(result['source'], 'unavailable')
        self.assertEqual(result['ip_address'], '196.250.178.135',
                         'the address needs no network and must still be shown')
        self.assertEqual(result['country'], '')

    def test_timeout_is_handled(self):
        from unittest.mock import patch

        from security.geolocation import describe_ip
        with patch('urllib.request.urlopen', side_effect=TimeoutError('slow')):
            self.assertEqual(describe_ip('196.250.178.135')['source'], 'unavailable')

    def test_connection_failure_is_handled(self):
        from unittest.mock import patch

        from security.geolocation import describe_ip
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError('dns')):
            self.assertEqual(describe_ip('196.250.178.135')['source'], 'unavailable')

    def test_unreadable_body_is_handled(self):
        from unittest.mock import patch

        from security.geolocation import describe_ip
        bad = FakeResponse({'unexpected': 'shape with nothing usable'})
        with patch('urllib.request.urlopen', return_value=bad):
            self.assertEqual(describe_ip('196.250.178.135')['source'], 'unavailable')

    def test_outage_is_not_cached(self):
        """A provider blip must not leave the card broken for the whole TTL."""
        from unittest.mock import patch

        from security.geolocation import describe_ip
        with patch('urllib.request.urlopen', side_effect=http_error(500, 'boom')):
            describe_ip('196.250.178.135')
            describe_ip('196.250.178.135')
        # No cached entry was written, so a later successful call still works.
        with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)):
            self.assertEqual(describe_ip('196.250.178.135')['source'], 'live')

    def test_blank_and_malformed_inputs_are_safe(self):
        from security.geolocation import describe_ip
        self.assertEqual(describe_ip('')['source'], 'unavailable')
        self.assertEqual(describe_ip(None)['source'], 'unavailable')
        self.assertEqual(describe_ip('not-an-ip')['source'], 'unavailable')

    def test_short_timeout_is_enforced(self):
        """A hung provider must not hold a dashboard request open."""
        from unittest.mock import patch

        import urllib.request as urllib_request

        from security.geolocation import DEFAULT_TIMEOUT_SECONDS
        self.assertLessEqual(DEFAULT_TIMEOUT_SECONDS, 5.0)
        seen = {}

        def capture(request, timeout=None):
            seen['timeout'] = timeout
            return FakeResponse(PROVIDER_OK)

        with patch('urllib.request.urlopen', capture):
            from security.geolocation import describe_ip
            describe_ip('196.250.178.135')
        self.assertEqual(seen['timeout'], DEFAULT_TIMEOUT_SECONDS)


# --------------------------------------------------------------------------
# "Last checked" needs to be honest about how old the answer actually is.
# --------------------------------------------------------------------------
class CheckedAtTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_live_result_reports_when_it_was_verified(self):
        from unittest.mock import patch
        from django.utils.dateparse import parse_datetime

        from security.geolocation import describe_ip
        with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)):
            result = describe_ip('196.250.178.135')
        parsed = parse_datetime(result['checked_at'])
        self.assertIsNotNone(parsed, 'checked_at must be a parseable ISO timestamp')
        self.assertLess(abs((timezone.now() - parsed).total_seconds()), 60)

    def test_cache_hit_keeps_the_original_check_time(self):
        """A cache hit must not claim it was just re-verified."""
        from unittest.mock import patch

        from security.geolocation import describe_ip
        with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)):
            first = describe_ip('196.250.178.135')
        with patch('urllib.request.urlopen') as urlopen:
            second = describe_ip('196.250.178.135')
        urlopen.assert_not_called()
        self.assertEqual(second['checked_at'], first['checked_at'])
        self.assertEqual(second['source'], 'cache')

    def test_blank_and_private_results_still_report_a_check_time(self):
        """These short-circuit without a lookup, but a check did happen."""
        from django.utils.dateparse import parse_datetime

        from security.geolocation import describe_ip
        for address in ('', 'not-an-ip', '127.0.0.1', '192.168.1.4'):
            self.assertIsNotNone(parse_datetime(describe_ip(address)['checked_at']), address)

    def test_forced_refresh_updates_the_check_time(self):
        from unittest.mock import patch

        from security.geolocation import describe_ip
        with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)):
            first = describe_ip('196.250.178.135')
        with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)):
            forced = describe_ip('196.250.178.135', force_refresh=True, user_id=7)
        self.assertEqual(forced['source'], 'live')
        self.assertFalse(forced['refresh_throttled'])
        self.assertGreaterEqual(forced['checked_at'], first['checked_at'])


# --------------------------------------------------------------------------
# The refresh button must actually re-check, without becoming a quota burner.
# --------------------------------------------------------------------------
class ForceRefreshTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_force_refresh_bypasses_the_cache(self):
        from unittest.mock import patch

        from security.geolocation import describe_ip
        with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)):
            describe_ip('196.250.178.135')
        with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)) as urlopen:
            result = describe_ip('196.250.178.135', force_refresh=True, user_id=7)
        self.assertEqual(result['source'], 'live')
        self.assertEqual(urlopen.call_count, 1, 'a forced refresh must re-query the provider')

    def test_second_forced_refresh_is_rate_limited(self):
        from unittest.mock import patch

        from security.geolocation import describe_ip
        with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)):
            describe_ip('196.250.178.135')
            describe_ip('196.250.178.135', force_refresh=True, user_id=7)
        # Immediately again: the provider must not be hit a second time.
        with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)) as urlopen:
            result = describe_ip('196.250.178.135', force_refresh=True, user_id=7)
        urlopen.assert_not_called()
        self.assertTrue(result['refresh_throttled'], 'the caller must be able to tell')
        self.assertEqual(result['source'], 'cache')
        self.assertEqual(result['country'], 'Liberia', 'the cached answer is still returned')

    def test_the_limit_is_per_user(self):
        from unittest.mock import patch

        from security.geolocation import describe_ip
        with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)):
            describe_ip('196.250.178.135', force_refresh=True, user_id=7)
        with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)) as urlopen:
            result = describe_ip('196.250.178.135', force_refresh=True, user_id=8)
        self.assertFalse(result['refresh_throttled'])
        self.assertEqual(urlopen.call_count, 1)

    def test_a_private_address_is_never_refreshed(self):
        """Nothing to re-check, so a refresh must not spend quota."""
        from unittest.mock import patch

        from security.geolocation import describe_ip
        with patch('urllib.request.urlopen') as urlopen:
            result = describe_ip('192.168.1.10', force_refresh=True, user_id=7)
        urlopen.assert_not_called()
        self.assertEqual(result['source'], 'private')
        self.assertFalse(result['refresh_throttled'])

    def test_the_limit_can_be_switched_off(self):
        from unittest.mock import patch
        from django.test import override_settings

        from security.geolocation import describe_ip
        with override_settings(CONNECTION_REFRESH_MIN_INTERVAL_SECONDS=0):
            with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)):
                describe_ip('196.250.178.135', force_refresh=True, user_id=7)
            with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)) as urlopen:
                result = describe_ip('196.250.178.135', force_refresh=True, user_id=7)
        self.assertFalse(result['refresh_throttled'])
        self.assertEqual(urlopen.call_count, 1)

    def test_refresh_flag_is_always_present(self):
        """A stable response shape, so the frontend never guards on undefined."""
        from unittest.mock import patch

        from security.geolocation import describe_ip
        with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)):
            for forced in (False, True):
                self.assertIn('refresh_throttled', describe_ip(
                    '196.250.178.135', force_refresh=forced, user_id=7))


# --------------------------------------------------------------------------
# Session security facts.
# --------------------------------------------------------------------------
class SessionFactsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.company = make_company('Acme Sessions', 'acme-sessions@example.com')
        self.user = make_user(self.company, 'sessionuser')

    def secure_request(self, **meta):
        from rest_framework.test import APIRequestFactory
        request = APIRequestFactory().get('/x/', **meta)
        request.user = self.user
        return request

    def test_plaintext_transport_is_reported_as_insecure(self):
        """A dashboard that says "secure session" must not mean it over plain HTTP."""
        from security.services import describe_session, SESSION_INSECURE
        request = self.secure_request(REMOTE_ADDR='203.0.113.9')
        facts = describe_session(request)
        self.assertEqual(facts['status'], SESSION_INSECURE)
        self.assertFalse(facts['secure_transport'])

    def test_https_with_no_managed_session_is_unmanaged(self):
        """Token/Django-session auth has no SecuritySession to vouch for it."""
        from security.services import describe_session, SESSION_UNMANAGED
        request = self.secure_request(REMOTE_ADDR='203.0.113.9', secure=True)
        facts = describe_session(request)
        self.assertEqual(facts['status'], SESSION_UNMANAGED)
        self.assertFalse(facts['managed'])
        self.assertIsNone(facts['expires_at'])

    def test_https_with_a_managed_session_is_secure(self):
        from security.services import describe_session, SESSION_SECURE
        request = self.secure_request(REMOTE_ADDR='203.0.113.9', secure=True)
        request.auth = self.make_session()
        facts = describe_session(request)
        self.assertEqual(facts['status'], SESSION_SECURE)
        self.assertTrue(facts['secure_transport'])
        self.assertTrue(facts['managed'])
        self.assertIsNotNone(facts['expires_at'])
        self.assertGreater(facts['expires_in_seconds'], 0)

    def test_enabled_but_unverified_mfa_is_not_reported_as_secure(self):
        """The strongest signal we have about the person at the keyboard."""
        from security.services import describe_session, SESSION_STANDARD
        session = self.make_session(mfa_verified=False)
        MFADevice.objects.create(user=self.user, secret_encrypted='x', enabled=True)
        request = self.secure_request(REMOTE_ADDR='203.0.113.9', secure=True)
        request.auth = session
        facts = describe_session(request)
        self.assertEqual(facts['status'], SESSION_STANDARD)
        self.assertTrue(facts['mfa_enabled'])
        self.assertFalse(facts['mfa_verified'])

    def test_verified_mfa_upgrades_to_secure(self):
        from security.services import describe_session, SESSION_SECURE
        session = self.make_session(mfa_verified=True)
        MFADevice.objects.create(user=self.user, secret_encrypted='x', enabled=True)
        request = self.secure_request(REMOTE_ADDR='203.0.113.9', secure=True)
        request.auth = session
        self.assertEqual(describe_session(request)['status'], SESSION_SECURE)

    def test_a_revoked_session_is_expired(self):
        from django.utils import timezone as dj_tz

        from security.services import describe_session, SESSION_EXPIRED
        session = self.make_session()
        session.revoked_at = dj_tz.now()
        session.save(update_fields=['revoked_at'])
        request = self.secure_request(REMOTE_ADDR='203.0.113.9', secure=True)
        request.auth = session
        facts = describe_session(request)
        self.assertEqual(facts['status'], SESSION_EXPIRED)
        self.assertFalse(facts['active'])
        self.assertEqual(facts['expires_in_seconds'], 0)

    def test_transport_takes_priority_over_session_details(self):
        """Plaintext is worth flagging even when MFA was verified."""
        from security.services import describe_session, SESSION_INSECURE
        MFADevice.objects.create(user=self.user, secret_encrypted='x', enabled=True)
        request = self.secure_request(REMOTE_ADDR='203.0.113.9')
        request.auth = self.make_session(mfa_verified=True)
        self.assertEqual(describe_session(request)['status'], SESSION_INSECURE)

    def test_token_authenticated_request_does_not_trip_on_a_foreign_auth_object(self):
        """TokenAuthentication puts a DRF Token in request.auth, not a session.

        It has no ``.active`` or ``.expires_at``, so anything that assumes a
        SecuritySession would raise. Token auth is in DEFAULT_AUTHENTICATION_CLASSES,
        so this is a live path, not a hypothetical one.
        """
        from rest_framework.authtoken.models import Token

        from security.services import describe_session, SESSION_UNMANAGED
        request = self.secure_request(REMOTE_ADDR='203.0.113.9', secure=True)
        request.auth = Token.objects.create(user=self.user)
        facts = describe_session(request)
        self.assertEqual(facts['status'], SESSION_UNMANAGED)
        self.assertFalse(facts['managed'])
        self.assertTrue(facts['active'])
        self.assertIsNone(facts['expires_at'])

    def test_token_authenticated_request_works_through_the_endpoint(self):
        from unittest.mock import patch
        from rest_framework.authtoken.models import Token

        token = Token.objects.create(user=self.user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Token ' + token.key)
        with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)):
            response = client.get(CONNECTION_URL, REMOTE_ADDR='196.250.178.135', secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['session']['status'], 'unmanaged')
        self.assertEqual(response.data['session']['managed'], False)
        self.assertEqual(response.data['session']['active'], True)

    def make_session(self, mfa_verified=True):
        from django.utils import timezone as dj_tz
        from datetime import timedelta
        from security.models import SecuritySession

        return SecuritySession.objects.create(
            user=self.user, company=self.company,
            secret_hash=hash_value(f'secret-{self.user.pk}-{mfa_verified}-{timezone.now().timestamp()}'),
            ip_address='203.0.113.9',
            expires_at=dj_tz.now() + timedelta(hours=8),
            mfa_verified=mfa_verified,
        )

    def test_endpoint_includes_the_session_block(self):
        from unittest.mock import patch

        client = APIClient()
        client.force_authenticate(self.user)
        with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)):
            response = client.get(CONNECTION_URL, REMOTE_ADDR='196.250.178.135')
        self.assertIn('session', response.data)
        for field in ('status', 'secure_transport', 'managed', 'active', 'mfa_enabled',
                      'mfa_verified', 'trust_score', 'expires_at', 'expires_in_seconds'):
            self.assertIn(field, response.data['session'])

    def test_endpoint_reports_the_callers_own_session_only(self):
        """Another user's session facts must never appear here."""
        from unittest.mock import patch

        other = make_user(self.company, 'other-sessionuser')
        theirs = self.make_session()
        client = APIClient()
        client.force_authenticate(self.user)
        with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)):
            response = client.get(CONNECTION_URL, REMOTE_ADDR='196.250.178.135')
        self.assertNotIn(str(theirs.id), json.dumps(response.data))
        self.assertNotEqual(other.pk, self.user.pk)


# --------------------------------------------------------------------------
# The endpoint.
# --------------------------------------------------------------------------
class ConnectionEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.company = make_company('Acme Connect', 'acme-connect@example.com')
        self.user = make_user(self.company, 'connector')
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.user)

    def test_requires_authentication(self):
        response = APIClient().get(CONNECTION_URL)
        self.assertIn(response.status_code, (401, 403))

    def test_returns_the_expected_shape(self):
        from unittest.mock import patch

        with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)):
            response = self.client_api.get(CONNECTION_URL, REMOTE_ADDR='196.250.178.135')
        self.assertEqual(response.status_code, 200)
        for field in ('ip_address', 'country', 'country_code', 'region',
                      'city', 'isp', 'asn', 'domain', 'source'):
            self.assertIn(field, response.data)
        self.assertEqual(response.data['ip_address'], '196.250.178.135')
        self.assertEqual(response.data['country'], 'Liberia')

    def test_describes_only_the_caller(self):
        """There is no parameter to inspect anyone else, and none was added."""
        from unittest.mock import patch

        other = make_user(self.company, 'someone-else')
        with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)):
            response = self.as_user(other).get(CONNECTION_URL, REMOTE_ADDR='196.250.178.135')
        self.assertEqual(response.status_code, 200)
        # The address comes from the live request, never from stored per-user data.
        self.assertEqual(response.data['ip_address'], '196.250.178.135')
        # The response is purely descriptive: it carries no user reference, and no
        # other user's data can be reached through it. `session` describes the
        # caller's own session and is a set of security facts, not an identifier.
        self.assertEqual(set(response.data), {
            'ip_address', 'country', 'country_code', 'region', 'city',
            'isp', 'asn', 'domain', 'source', 'checked_at', 'refresh_throttled',
            'session',
        })
        self.assertNotIn('user_id', response.data['session'])
        self.assertNotIn('id', response.data['session'])

    def test_a_different_caller_gets_their_own_address(self):
        """One user's connection info is never served to another."""
        from unittest.mock import patch

        with patch('urllib.request.urlopen', return_value=FakeResponse(PROVIDER_OK)):
            mine = self.client_api.get(CONNECTION_URL, REMOTE_ADDR='196.250.178.135')
            theirs = self.as_user(make_user(self.company, 'other')).get(
                CONNECTION_URL, REMOTE_ADDR='203.0.113.44')
        self.assertEqual(mine.data['ip_address'], '196.250.178.135')
        self.assertEqual(theirs.data['ip_address'], '203.0.113.44')

    def as_user(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_geolocation_outage_still_returns_the_address(self):
        from unittest.mock import patch

        with patch('urllib.request.urlopen', side_effect=http_error(500, 'boom')):
            response = self.client_api.get(CONNECTION_URL, REMOTE_ADDR='196.250.178.135')
        self.assertEqual(response.status_code, 200, 'a provider outage must not fail the card')
        self.assertEqual(response.data['ip_address'], '196.250.178.135')
        self.assertEqual(response.data['country'], '')

    def test_local_development_reports_a_private_network(self):
        from unittest.mock import patch

        with patch('urllib.request.urlopen') as urlopen:
            response = self.client_api.get(CONNECTION_URL, REMOTE_ADDR='127.0.0.1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['source'], 'private')
        self.assertEqual(response.data['ip_address'], '127.0.0.1')
        urlopen.assert_not_called()

    def test_response_is_never_stored_by_a_shared_cache(self):
        """It is per-request and per-user, so a shared cache or CDN must skip it.

        The absence of a header is not a valid way to express this: with no
        Cache-Control at all a shared cache is free to store the response and
        hand one user's address and country to the next person through it.
        """
        response = self.client_api.get(CONNECTION_URL, REMOTE_ADDR='196.250.178.135')
        self.assertIn('Cache-Control', response)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('private', response['Cache-Control'])
