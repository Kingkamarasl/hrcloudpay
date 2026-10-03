from datetime import timedelta
from django.utils import timezone
from django.db.models import Count
from .models import SecurityEvent, SecurityIncident, RiskSignal, DeviceTrust, SecuritySession
from .utils import client_ip, hash_value

# Session states surfaced on the dashboard's connection card. The backend reports
# the facts; the frontend decides how to word and colour them.
SESSION_SECURE = 'secure'        # HTTPS, active, and MFA satisfied where enabled
SESSION_STANDARD = 'standard'    # HTTPS and active, but MFA is enabled and unverified
SESSION_UNMANAGED = 'unmanaged'  # authenticated, but not via a SecuritySession
SESSION_INSECURE = 'insecure'    # served over plaintext HTTP
SESSION_EXPIRED = 'expired'      # the session is no longer usable

def emit(request, event_type, severity='low', message='', company=None, actor=None, metadata=None):
    return SecurityEvent.objects.create(company=company or getattr(actor, 'company', None), actor=actor, event_type=event_type, severity=severity, message=message or event_type, ip_address=client_ip(request) if request else None, user_agent=(request.META.get('HTTP_USER_AGENT','')[:1000] if request else ''), metadata=metadata or {})

def create_incident(company, title, severity='medium', summary='', evidence=None):
    return SecurityIncident.objects.create(company=company, title=title, severity=severity, summary=summary, evidence=evidence or [])

def detect_auth_burst(company, user=None):
    since = timezone.now() - timedelta(minutes=10)
    qs = SecurityEvent.objects.filter(company=company, event_type='login_failed', created_at__gte=since)
    count = qs.count()
    if count >= 10:
        signal = RiskSignal.objects.create(company=company, user=user, signal_type='authentication_burst', score=min(100, 40 + count * 4), evidence={'failed_logins': count, 'window_minutes': 10}, expires_at=timezone.now()+timedelta(hours=1))
        create_incident(company, 'Repeated authentication failures', 'high' if count >= 20 else 'medium', 'Repeated failed authentication attempts detected.', [{'signal': str(signal.id)}])
        return signal
    return None

def trust_score(user, session=None, device=None):
    score = 100
    if not user.is_active: score = 0
    if hasattr(user, 'mfa_device') and not user.mfa_device.enabled: score -= 20
    if user.role in ('owner','admin') and (not hasattr(user,'mfa_device') or not user.mfa_device.enabled): score -= 25
    if device and device.state == 'blocked': score = 0
    elif device and device.state == 'untrusted': score -= 20
    if session and not session.active: score = 0
    return max(0, min(100, score))

def can_sensitive_action(user, session=None, minimum=60):
    return trust_score(user, session=session) >= minimum


def describe_session(request):
    """Security facts about the session that is serving this request.

    Reported as raw facts plus a single ``status`` enum, so the wording and
    colours stay a presentation concern. Only ever describes the caller: the
    session is the one attached to this request.
    """
    user = request.user
    session = getattr(request, 'auth', None)
    managed = isinstance(session, SecuritySession)

    active = bool(session.active) if managed else bool(user and user.is_authenticated)
    mfa_device = getattr(user, 'mfa_device', None)
    mfa_enabled = bool(mfa_device and mfa_device.enabled)
    mfa_verified = bool(session.mfa_verified) if managed else False
    # Honours SECURE_PROXY_SSL_HEADER, so this is correct behind a TLS
    # terminating proxy rather than reporting every proxied request as plain HTTP.
    secure_transport = bool(request.is_secure())

    if not active:
        status = SESSION_EXPIRED
    elif not secure_transport:
        status = SESSION_INSECURE
    elif not managed:
        status = SESSION_UNMANAGED
    elif mfa_enabled and not mfa_verified:
        status = SESSION_STANDARD
    else:
        status = SESSION_SECURE

    expires_at = session.expires_at if managed else None
    expires_in = 0
    if managed and active and expires_at is not None:
        expires_in = max(0, int((expires_at - timezone.now()).total_seconds()))

    return {
        'status': status,
        'secure_transport': secure_transport,
        'managed': managed,
        'active': active,
        'mfa_enabled': mfa_enabled,
        'mfa_verified': mfa_verified,
        'trust_score': trust_score(user, session=session if managed else None),
        'expires_at': expires_at.isoformat() if expires_at is not None else None,
        'expires_in_seconds': expires_in,
    }
