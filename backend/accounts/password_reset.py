"""Password reset, by emailed link.

Why Django's signed token rather than a model
--------------------------------------------
`django.contrib.auth.tokens.default_token_generator` signs a payload with
SECRET_KEY and carries a timestamp, so it expires without anything to clean up
and there is no reset-token table to migrate, back up or leak. A dedicated model
would only add a second thing that can be left behind in a database.

The three things this gets wrong easily, and does not
----------------------------------------------------
**Account enumeration.** The response is identical whether the address exists,
is unknown, or belongs to a company that has not been activated. A different
message is an account-existence oracle, and this endpoint is unauthenticated.

**Timing.** An unknown address short-circuits before the token is signed and the
mail is handed to SMTP. To keep the response time roughly flat, a cheap hash is
computed either way, so the unknown-address path is not obviously faster. This
is not a constant-time guarantee - it narrows the signal, it does not remove it -
and the throttle is the real control.

**Silent send failures.** The mail goes through `send_mail_logging_failure`, so a
broken SMTP configuration leaves a trace naming the address instead of returning
the success message below with nothing delivered. A user who never receives the
link is the most common way this feature gets reported as "it doesn't work".
"""
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from hrcloudpay.email_backend import send_mail_logging_failure

# One answer for every outcome. Not an oversight - see the module docstring.
GENERIC_RESPONSE = {
    'detail': 'If that address belongs to an account, a reset link is on its way.',
}

SUBJECT = 'Reset your HRCloudPay password'
BODY = (
    'Hello,\n\n'
    'Someone asked to reset the password for this address on HRCloudPay. '
    'Open the link below to choose a new one:\n\n'
    '{link}\n\n'
    'If it was not you, no action is needed - nothing changes until the link '
    'is used, and the link stops working after {hours} hours.\n'
)


class PasswordResetRequestView(APIView):
    """Send a reset link, if the address is one we know."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = 'password_reset'
    schema = None

    @staticmethod
    def _token_lifetime_hours():
        """How long the link is good for, in whole hours.

        `TOKEN_LIFETIME` has been a timedelta and a plain int of seconds in
        different Django versions, so both are handled. An email that promises a
        window the link does not honour is worse than one that quotes none, and
        the hours are computed from the token generator's own value rather than
        from a second number kept in step with it by hand.
        """
        from datetime import timedelta

        from django.contrib.auth.tokens import default_token_generator as gen

        lifetime = getattr(gen, 'TOKEN_LIFETIME', timedelta(days=1))
        seconds = lifetime.total_seconds() if hasattr(lifetime, 'total_seconds') else lifetime
        return max(1, int(seconds // 3600))

    @staticmethod
    def _deliver(user, token):
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        link = f'{settings.FRONTEND_URL}/reset-password/{uid}/{token}'

        return send_mail_logging_failure(
            subject=SUBJECT,
            message=BODY.format(
                link=link, hours=PasswordResetRequestView._token_lifetime_hours(),
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            what='password reset',
        )

    def post(self, request):
        address = str(request.data.get('email') or '').strip()
        if not address or '@' not in address:
            # Still the generic answer. Rejecting malformed input differently is
            # harmless, but answering for a well-formed unknown address differently
            # is not, and one code path is easier to keep correct.
            return Response(GENERIC_RESPONSE)

        # Case-insensitive, because `email` is unique in the database but that
        # uniqueness is not case-insensitive on every backend.
        user = User.objects.filter(email__iexact=address).first()

        if user is not None and user.is_active:
            try:
                token = default_token_generator.make_token(user)
            except Exception:
                # A signing failure must not become a 500 that tells the caller
                # this address is special.
                token = None
            if token is not None:
                self._deliver(user, token)

        return Response(GENERIC_RESPONSE)


class PasswordResetConfirmView(APIView):
    """Set a new password against a token from the emailed link."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = 'password_reset'
    schema = None

    def post(self, request):
        uid = str(request.data.get('uid') or '')
        token = str(request.data.get('token') or '')
        password = str(request.data.get('new_password') or '')

        if not uid or not token or not password:
            return Response(
                {'detail': 'This reset link is incomplete. Request a new one.'},
                status=400,
            )

        try:
            pk = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=pk, is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None

        if user is None or not default_token_generator.check_token(user, token):
            return Response(
                {'detail': 'This reset link is invalid or has expired. Request a new one.'},
                status=400,
            )

        try:
            password_validation.validate_password(password, user=user)
        except ValidationError as exc:
            # Two shapes. A form serializer raises a dict keyed by field;
            # `password_validation` raises a flat list, one message per failed
            # validator, with no field names at all. Assuming the first one made
            # this except block raise AttributeError, so a weak password
            # produced a 500 with a traceback instead of the 400 saying why.
            if hasattr(exc, 'message_dict'):
                errors = {field: list(messages)
                          for field, messages in exc.message_dict.items()}
            else:
                errors = {'new_password': list(exc.messages)}
            return Response(
                {'detail': 'Choose a stronger password.', 'errors': errors},
                status=400,
            )

        user.set_password(password)
        user.save(update_fields=['password'])

        # A password change must invalidate outstanding sessions: that is the
        # point of changing it after a suspected compromise, and leaving old
        # sessions working would make the reset decorative.
        _drop_sessions(user)

        return Response({'detail': 'Your password has been changed. You can sign in now.'})


def _drop_sessions(user):
    """End every existing session for this user.

    Rows are removed directly rather than through `django.contrib.auth.logout`,
    which needs a real request and a real session cookie and neither exists here.
    Rows are read and decoded rather than grepped, because `session_data` is not
    JSON: it is base64 of the JSON, with a signature appended. A substring search
    over that column matches nothing at all, which is exactly what happened - the
    filter looked plausible, ran without error, and silently deleted zero rows. A
    password reset that leaves every session alive is decorative.

    Decoding through SessionStore also means this keeps working if the signing
    scheme, the JSON serializer or the compression threshold changes.
    """
    from django.contrib.auth import SESSION_KEY
    from django.contrib.sessions.backends.db import SessionStore
    from django.contrib.sessions.models import Session
    from django.utils import timezone

    live = Session.objects.filter(expire_date__gt=timezone.now()).only(
        'session_key', 'session_data')
    for row in live:
        try:
            store = SessionStore(session_key=row.session_key)
            store.load()
            owner = store.get(SESSION_KEY)
        except Exception:
            # A row that will not decode is not this user's to end, and failing
            # to read it must not stop the rest being cleared.
            continue
        if owner is not None and str(owner) == str(user.pk):
            row.delete()
