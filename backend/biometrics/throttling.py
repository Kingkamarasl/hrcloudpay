"""Rate limiting for punch ingestion.

A terminal has no user account, so the ingest endpoint is unauthenticated by
necessity and falls under DRF's global anonymous throttle: 100 requests per hour
per IP. That budget is shared with every other anonymous request from the same
address, which means a site behind one NAT has its terminals throttled by
browsing traffic from the same office - and a terminal flushing a day of queued
punches is refused outright, with the refused punches simply lost.

The identity that actually issues punches is the device, and its key is already
in the request. So that is what punches are counted against. Requests that do
not present a device identity keep the strict anonymous budget instead: they are
a misconfigured terminal or someone probing, and neither deserves a
device-sized allowance.
"""
import hashlib

from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle


def device_identity(request):
    """A stable, non-reversible identity for the terminal making the request.

    The key is hashed into the throttle key rather than used directly, for the
    same reason only its hash is stored on the device: a cache dump should not
    hand over a key that can inject attendance for a whole company.

    Returns None when the request presents no device credentials, which is the
    signal for the two throttles below to hand off to each other.
    """
    data = request.data
    if not hasattr(data, 'get'):
        return None
    device_id = data.get('device_id')
    raw_key = request.META.get('HTTP_X_BIOMETRIC_DEVICE_KEY', '')
    if not device_id or not raw_key:
        return None
    digest = hashlib.sha256(
        ('%s|%s' % (device_id, raw_key)).encode()).hexdigest()
    return 'device:%s' % digest[:32]


class BiometricDeviceThrottle(SimpleRateThrottle):
    """Counts punches against the device that sent them, not its IP."""

    scope = 'biometric_device'

    def allow_request(self, request, view):
        # An unidentified request is metered by AnonymousPunchThrottle. Letting
        # this class count it too would put it in the generous device bucket,
        # which is the opposite of what it should get.
        if device_identity(request) is None:
            return True
        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        identity = device_identity(request)
        if identity is None:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': identity}


class AnonymousPunchThrottle(AnonRateThrottle):
    """The ordinary anonymous budget, for requests with no device identity."""

    scope = 'anon'

    def allow_request(self, request, view):
        if device_identity(request) is not None:
            return True
        return super().allow_request(request, view)
