"""Client network address resolution.

Lives in ``accounts`` rather than ``security`` because both apps need it and
``security`` already depends on ``accounts``; resolving the address here keeps a
single implementation instead of one per app that can drift apart.
"""
import ipaddress

from django.conf import settings


def clean_ip(value):
    """Return a syntactically valid IP string, or ''.

    Forwarding headers are supplied by the client unless a trusted proxy
    overwrites them, so anything that is not a real address is discarded rather
    than stored in a ``GenericIPAddressField`` or shown to a user.
    """
    candidate = (value or '').strip()
    if not candidate:
        return ''
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return ''


def is_private_ip(value):
    """True for loopback, private, link-local, reserved and unspecified addresses.

    An unparseable value counts as private: there is never anything useful to
    look up or display.
    """
    try:
        address = ipaddress.ip_address((value or '').strip())
    except ValueError:
        return True
    return bool(
        address.is_private or address.is_loopback or address.is_link_local
        or address.is_reserved or address.is_multicast or address.is_unspecified
    )


def client_ip(request):
    """Best-effort originating client address for a request.

    ``X-Forwarded-For`` is consulted only when ``TRUSTED_PROXY_COUNT`` says how
    many reverse proxies sit in front of Django, and the address is then taken
    from the right-hand end of the header - past every entry those proxies
    appended. A client therefore cannot forge its own address by prepending to
    the header, and a directly exposed deployment is unaffected.

    Previously the ``security`` app preferred ``REMOTE_ADDR`` and ignored
    ``X-Forwarded-For`` entirely, so behind a load balancer every security
    session and event recorded the balancer's address, while ``accounts.audit``
    used the opposite precedence. The two disagreed about the same request.
    """
    trusted = getattr(settings, 'TRUSTED_PROXY_COUNT', 0)
    if trusted:
        entries = [
            address for address in (
                clean_ip(part) for part in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')
            ) if address
        ]
        if entries:
            # Each trusted proxy appends one entry, so the client is N from the right.
            return entries[len(entries) - trusted] if len(entries) > trusted else entries[0]
        real_ip = clean_ip(request.META.get('HTTP_X_REAL_IP', ''))
        if real_ip:
            return real_ip
    return clean_ip(request.META.get('REMOTE_ADDR', ''))
