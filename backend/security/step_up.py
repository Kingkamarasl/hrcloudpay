"""Step-up authentication for sensitive actions.

Login-time MFA only proves who was at the keyboard when the session opened. A
session left open on a shared or unattended machine, or a stolen session
cookie, would otherwise let an insider approve payroll or change a salary
hours later with no second factor.

``RequiresFreshMfa`` closes that window: the action is refused unless the
caller completed a TOTP challenge within ``MFA_STEP_UP_WINDOW_SECONDS``. Users
without MFA enabled are not locked out of their own accounts - enrollment is
nudged rather than forced, and the refusal message says which action needs it.
"""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.permissions import BasePermission

from .models import SecuritySession


def step_up_window() -> timedelta:
    return timedelta(seconds=getattr(settings, 'MFA_STEP_UP_WINDOW_SECONDS', 900))


def mfa_is_fresh(session, now=None) -> bool:
    """True when the session completed MFA within the step-up window."""
    if session is None:
        return False
    if not getattr(session, 'mfa_verified', False):
        return False
    verified_at = getattr(session, 'mfa_verified_at', None)
    # No timestamp means the session was never stamped by MFAStepUpView or
    # by a real TOTP challenge. A plain password login carries
    # mfa_verified=True (meaning "no second factor applies") and must not
    # count as a step-up, so this deliberately fails closed rather than
    # falling back to created_at.
    if verified_at is None:
        return False
    return (now or timezone.now()) - verified_at <= step_up_window()


def mfa_enrolled(user) -> bool:
    device = getattr(user, 'mfa_device', None)
    return bool(device and device.enabled)


class RequiresFreshMfa(BasePermission):
    """Permission class requiring a recent MFA challenge.

    Only an interactive `SecuritySession` can satisfy this. A caller
    authenticated with a DRF `Token` has no session to stamp, so these actions
    are refused for token clients rather than silently allowed - paying a
    payroll run needs a human with a second factor, which is the entire point
    of the control. The refusal says so explicitly instead of looking like a
    missing permission.

    Refuses with 403 and an explicit ``mfa_required`` flag so the frontend can
    prompt for a code rather than showing a generic failure.
    """

    message = 'A fresh MFA code is required for this action.'

    MUTATING = ('POST', 'PUT', 'PATCH', 'DELETE')

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        # Non-mutating requests carry no risk; only guard the action itself.
        if request.method not in self.MUTATING:
            return True

        session = getattr(request, 'auth', None)
        if mfa_is_fresh(session):
            return True

        # Raising rather than returning False: DRF flattens a plain permission
        # denial to one `detail` string, which loses the flags the frontend
        # needs to choose between "enter a code" and "enroll first".
        if not isinstance(session, SecuritySession):
            raise MfaStepUpRequired({
                'required': True,
                'enrollment_required': False,
                'interactive_session_required': True,
                'detail': 'This action must be performed from an interactive session with two-factor authentication enabled.',
            })
        if not mfa_enrolled(request.user):
            raise MfaStepUpRequired({
                'required': True,
                'enrollment_required': True,
                'detail': 'Enable two-factor authentication to perform this action.',
            })
        raise MfaStepUpRequired({
            'required': True,
            'enrollment_required': False,
            'detail': f'Enter your MFA code to confirm this action (valid for {int(step_up_window().total_seconds() // 60)} minutes).',
        })


class MfaStepUpRequired(APIException):
    """403 carrying the structured reason a step-up was refused.

    DRF's default handler flattens a permission denial to a single `detail`
    string, which would leave the frontend unable to tell "enter a code" from
    "enroll first". Raising this instead preserves those flags.
    """

    status_code = status.HTTP_403_FORBIDDEN
    default_code = 'mfa_required'

    def __init__(self, payload):
        self.payload = payload
        # 'code' is duplicated into the body: DRF keeps the exception's code as
        # an attribute, but a client reading the JSON needs it to tell an
        # MFA challenge apart from an ordinary permission failure.
        super().__init__(
            {
                'code': 'mfa_required',
                'detail': payload.get('detail', 'A fresh MFA code is required.'),
                **payload,
            },
            code='mfa_required',
        )


def step_up_response(request):
    """Payload the permission attached to the request, for use by views."""
    return getattr(request, '_mfa_step_up', {
        'required': True,
        'enrollment_required': False,
        'detail': RequiresFreshMfa.message,
    })
