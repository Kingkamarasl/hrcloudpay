"""Outbound mail driven by the platform admin's `EmailConfig` row.

Why this exists: `EMAIL_BACKEND` in the environment defaults to the console
backend, which on a container prints SMTP traffic to stdout that nobody reads.
Activation links, password resets and invitations then disappear with no failure
logged anywhere. The person who can fix that should not need a deployment edit,
so the configuration lives in the database and this backend reads it per send.

Two deliberate behaviours:

- **An explicit `EMAIL_BACKEND` in the environment still wins.** See
  `settings.py`. An operator who set it is not overridden by a feature they did
  not ask for.
- **With no usable config, this delegates to the console backend** rather than
  raising. A misconfigured deployment then still shows the mail it would have
  sent, which is what the console backend is for.

Django's test runner replaces `EMAIL_BACKEND` with locmem before any test runs,
so none of this is on the path for the suite.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.backends.console import EmailBackend as ConsoleBackend
from django.core.mail.backends.smtp import EmailBackend as SMTPEmailBackend

logger = logging.getLogger(__name__)


class PlatformEmailBackend(BaseEmailBackend):
    """SMTP using the stored `EmailConfig`, falling back to the console."""

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        config = self._load_config()
        if config is None:
            return ConsoleBackend().send_messages(email_messages)

        # Deliberately not caught. If the stored secret cannot be decrypted with
        # the configured keys - usually SECRET_ENCRYPTION_KEYS rotated out from
        # under it - then falling back to the console would hide a broken
        # credential behind silently lost email. This raises loudly instead.
        password = config.get_password()

        if config.from_email:
            site_default = settings.DEFAULT_FROM_EMAIL
            for message in email_messages:
                # Replaces the site-wide default only. A sender chosen per
                # message still wins, so this cannot quietly redirect mail that
                # a caller deliberately addressed.
                if not message.from_email or message.from_email == site_default:
                    message.from_email = config.from_email

        connection = SMTPEmailBackend(
            host=config.host,
            port=config.port,
            username=config.username or None,
            password=password or None,
            use_tls=config.use_tls,
            use_ssl=config.use_ssl,
            timeout=config.timeout_seconds,
            fail_silently=self.fail_silently,
        )
        return connection.send_messages(email_messages)

    @staticmethod
    def _load_config():
        from accounts.platform_models import EmailConfig

        config = EmailConfig.objects.first()
        if config is None or not config.usable:
            return None
        return config


def send_mail_logging_failure(
    subject, message, from_email, recipient_list, what='message', **kwargs,
):
    """Send one message, recording the cause when it cannot be delivered.

    Django's ``fail_silently=True`` returns 0 and raises nothing. A refused
    port, an unroutable host, a rejected sender and a wrong password all
    produce no exception, no log line and no trace anywhere - the message is
    gone, while the caller reports success to the person waiting for it.

    That is not hypothetical. A deployment that named Django's stock SMTP
    backend without ever configuring EMAIL_HOST reached localhost:25, so every
    activation mail failed on every signup. Registration still returned 201 and
    told the user to check their email, while the platform's own test-send
    screen passed throughout, because it bypassed the broken path on purpose.

    The failure is still not raised. A signup must not return 500 because the
    mail server is down, and the account itself was created successfully either
    way. But it is logged at ERROR with the exception attached, so the cause is
    recoverable from the logs instead of from a customer.

    Returns the count of accepted messages - 0 on failure, the same value
    ``fail_silently=True`` returns, so callers need no change.
    """
    try:
        return send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=recipient_list,
            # Always False: the point is to catch the exception in order to
            # record it. fail_silently here would reintroduce the silence.
            fail_silently=False,
            **kwargs,
        )
    except Exception:
        logger.exception(
            'Could not send %s email to %s. It was not delivered and the '
            'recipient will not be told. Check the EmailConfig sender, then '
            'use Platform Admin -> Email / SMTP to send a test.',
            what, ', '.join(str(address) for address in recipient_list),
        )
        return 0