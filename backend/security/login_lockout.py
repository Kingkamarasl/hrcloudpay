"""Progressive account lockout for failed logins.

Two independent limits, because they defend against different things:

* **Per-IP** (DRF ``AnonRateThrottle``/``ScopedRateThrottle``) stops one address
  spraying many accounts.
* **Per-account** (this module) stops many addresses hammering one account,
  which per-IP limiting cannot see at all.

The lockout is progressive rather than a fixed 10-tries-then-locked: each
failure doubles the penalty, capped, so an attacker gets a handful of cheap
guesses against an unknown password and then cannot continue at all, while a
legitimate user who fat-fingers twice is only mildly delayed.
"""

from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.db import ProgrammingError, transaction
from django.db.utils import OperationalError
from django.utils import timezone

from .models import LoginThrottle

# Progressive backoff in seconds. The first entry applies at the lockout
# threshold and each further failure steps to the next, with the last value
# repeating as a ceiling so the penalty cannot be pushed arbitrarily high.
BACKOFF_SECONDS = (30, 60, 300, 900, 3600)

# Failures older than this start a fresh window, so a user who fails twice a
# week is never locked out for their normal typo rate.
FAILURE_WINDOW = timedelta(minutes=15)


def _seconds_for(failure_count: int) -> int:
    """Delay for the Nth consecutive failure.

    Indexed from the threshold, not from the first failure, so the *first*
    lockout is deliberately short (a user who fat-fingered a few times is not
    locked out for an hour) and each additional failure steps up the ramp.
    """
    index = max(0, failure_count - _threshold())
    if index >= len(BACKOFF_SECONDS):
        return BACKOFF_SECONDS[-1]
    return BACKOFF_SECONDS[index]


def _threshold() -> int:
    return getattr(settings, 'LOGIN_LOCKOUT_THRESHOLD', 5)


def _identifier(identifier_type: str, value: str) -> str:
    return f'{identifier_type}:{(value or "unknown").strip().lower()[:254]}'


def _tolerate_missing_table(fallback):
    """Let a checkout without `security/0003` still reach the login page.

    `LoginThrottle` arrives in migration `security/0003`. Every function in this
    module queries it, and `SecureLoginView` calls them *before* it
    authenticates, so an unguarded query turns every sign-in - correct password
    or not - into a 500, and the only way to diagnose it is to open a shell and
    notice the migration was never applied.

    That is the same trap the login view already guards for `emit()` and the MFA
    device lookup, so the rule is the same one: tolerate it under `DEBUG` so a
    developer is never locked out of their own machine, and re-raise in
    production, where an absent table is a deployment fault. Re-raising is
    deliberate rather than lenient - quietly serving logins with the brute-force
    lockout disabled is a security downgrade nobody chose to make, and it is
    silent. A loud 500 is the correct outcome for a misconfigured deploy.

    The policy lives here, not at each call site, so a future caller cannot
    reintroduce the outage by forgetting the guard. The `fallback` is the value
    a caller gets instead: `None` for "no lockout", `0` for "no seconds left".
    """
    def decorate(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except (OperationalError, ProgrammingError):
                if not settings.DEBUG:
                    raise
                return fallback
        return inner
    return decorate


@_tolerate_missing_table(None)
def get_lockout(identifier_type: str, value: str):
    """Return the active lockout for an identifier, or None if not locked."""
    return LoginThrottle.objects.filter(
        identifier=_identifier(identifier_type, value),
        identifier_type=identifier_type,
        locked_until__gt=timezone.now(),
    ).first()


@_tolerate_missing_table(0)
def check_locked(identifier_type: str, value: str):
    """Return seconds remaining on an active lockout, or 0 when not locked."""
    record = get_lockout(identifier_type, value)
    if not record:
        return 0
    return max(0, int((record.locked_until - timezone.now()).total_seconds()))


@_tolerate_missing_table(0)
def record_failure(identifier_type: str, value: str) -> int:
    """Count a failed attempt and apply progressive lockout. Returns seconds locked."""
    key = _identifier(identifier_type, value)
    now = timezone.now()
    with transaction.atomic():
        record, _ = LoginThrottle.objects.select_for_update().get_or_create(
            identifier=key,
            identifier_type=identifier_type,
            defaults={'failure_count': 0, 'window_started_at': now},
        )
        if now - record.window_started_at > FAILURE_WINDOW:
            record.failure_count = 0
            record.window_started_at = now
        record.failure_count += 1
        fields = ['failure_count', 'window_started_at', 'updated_at']

        if record.failure_count >= _threshold():
            seconds = _seconds_for(record.failure_count)
            record.locked_until = now + timedelta(seconds=seconds)
            fields.append('locked_until')
        record.save(update_fields=fields)

    return check_locked(identifier_type, value)


@_tolerate_missing_table(None)
def record_success(identifier_type: str, value: str) -> None:
    """Clear the counter after a successful login."""
    LoginThrottle.objects.filter(
        identifier=_identifier(identifier_type, value),
        identifier_type=identifier_type,
    ).update(failure_count=0, locked_until=None, window_started_at=timezone.now())


def lockout_message(seconds: int) -> str:
    """User-facing text. Deliberately does not reveal the lockout policy."""
    if seconds >= 3600:
        minutes = max(1, round(seconds / 60))
        return f'Too many failed sign-in attempts. Try again in about {minutes} minutes.'
    return f'Too many failed sign-in attempts. Try again in {max(1, round(seconds))} seconds.'
