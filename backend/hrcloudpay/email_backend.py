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
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.backends.console import EmailBackend as ConsoleBackend
from django.core.mail.backends.smtp import EmailBackend as SMTPEmailBackend


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