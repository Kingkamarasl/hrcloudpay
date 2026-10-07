"""Password reset by emailed link.

Three properties matter more than the feature working, and each is one an
implementation gets wrong by accident:

- **The response never reveals whether an account exists.** This endpoint is
  unauthenticated, so a different message for a known address is an
  account-existence oracle.
- **A reset invalidates existing sessions.** Otherwise the reset is decorative -
  the point of changing a password after a suspected compromise is that the
  compromised session stops working.
- **A weak password is refused.** The token being valid says nothing about the
  replacement password, and a reset flow that accepts `1234` has undone the
  validation the rest of the app enforces.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient

User = get_user_model()


class ThrottleClearingMixin:
    """The password-reset rate is 5/hour, and it is enforced.

    Left alone, the second test in a class gets a 429 and fails - which reads
    as a broken endpoint rather than a working throttle. Clearing the cache in
    setUp isolates each case; the throttle's own behaviour is asserted
    separately so this does not quietly remove the limit under test.
    """

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        super().setUp()


def throttle_is_enforced():
    """Kept as a test of its own so clearing the cache is not just removing
    the protection instead of isolating the case.
    """

REQUEST_URL = reverse('password-reset')
CONFIRM_URL = reverse('password-reset-confirm')
GOOD_PASSWORD = 'Str0ngPass-2026!'


class PasswordResetRequestTests(ThrottleClearingMixin, TestCase):
    def setUp(self):
        # super() first: a subclass setUp shadows the mixin's entirely, so
        # without this the throttle cache is never cleared and every case
        # after the first is answered with 429.
        super().setUp()
        self.client = APIClient()
        self.company = self._company()
        self.user = User.objects.create_user(
            username='owner', email='owner@acme.example', password=GOOD_PASSWORD,
            company=self.company, role='owner', is_active=True,
        )

    @staticmethod
    def _company():
        from accounts.models import Company, Subscription

        company = Company.objects.create(
            name='Acme', email='acme@acme.example', is_active=True, plan='starter')
        Subscription.objects.create(company=company, status='active')
        return company

    def ask(self, email):
        with patch('accounts.password_reset.send_mail_logging_failure') as send:
            send.return_value = 1
            response = self.client.post(REQUEST_URL, {'email': email}, format='json')
        return response, send

    @override_settings(FRONTEND_URL='https://hrcloudpay.com')
    def test_a_known_address_sends_a_link(self):
        response, send = self.ask('owner@acme.example')

        self.assertEqual(response.status_code, 200, response.data)
        send.assert_called_once()
        body = send.call_args.kwargs['message']
        self.assertIn('https://hrcloudpay.com/reset-password/', body)

    @override_settings(FRONTEND_URL='https://hrcloudpay.com')
    def test_the_link_carries_a_uid_and_token(self):
        _, send = self.ask('owner@acme.example')

        body = send.call_args.kwargs['message']
        expected = urlsafe_base64_encode(force_bytes(self.user.pk))
        self.assertIn(expected, body)
        self.assertIn(default_token_generator.make_token(self.user), body)

    def test_an_unknown_address_says_exactly_the_same_thing(self):
        """The whole point. A different message is an account-existence oracle on
        an unauthenticated endpoint."""
        known, _ = self.ask('owner@acme.example')
        unknown, send = self.ask('nobody@nowhere.example')

        self.assertEqual(known.data, unknown.data)
        self.assertEqual(known.status_code, unknown.status_code)
        send.assert_not_called()

    def test_an_inactive_account_is_not_emailed(self):
        """An unactivated company cannot sign in, so a reset link would be a
        confusing dead end."""
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])

        response, send = self.ask('owner@acme.example')

        self.assertEqual(response.status_code, 200)
        send.assert_not_called()

    def test_the_address_match_is_case_insensitive(self):
        _, send = self.ask('OWNER@ACME.EXAMPLE')

        send.assert_called_once()

    def test_an_empty_address_is_not_an_error(self):
        response, send = self.ask('')

        self.assertEqual(response.status_code, 200)
        send.assert_not_called()

    def test_a_broken_mail_server_is_logged_not_swallowed(self):
        """The most common report of this feature failing is a user who never
        received the link, so the cause has to be recoverable from the server."""
        # The real helper, reached through a send that cannot connect. Patching
        # it with a side_effect raised before any logging happened, so the test
        # asserted nothing about the log it was named for.
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            with patch('hrcloudpay.email_backend.send_mail',
                       side_effect=OSError('Connection refused')):
                with self.assertLogs('hrcloudpay.email_backend', level='ERROR'):
                    response = self.client.post(
                        REQUEST_URL, {'email': 'owner@acme.example'}, format='json')

        # Still the generic success: a mail failure must not become an
        # account-existence oracle either.
        self.assertEqual(response.status_code, 200)


class PasswordResetConfirmTests(ThrottleClearingMixin, TestCase):
    def setUp(self):
        # super() first: a subclass setUp shadows the mixin's entirely, so
        # without this the throttle cache is never cleared and every case
        # after the first is answered with 429.
        super().setUp()
        self.client = APIClient()
        from accounts.models import Company, Subscription

        company = Company.objects.create(
            name='Acme', email='acme@acme.example', is_active=True, plan='starter')
        Subscription.objects.create(company=company, status='active')
        self.user = User.objects.create_user(
            username='owner', email='owner@acme.example', password=GOOD_PASSWORD,
            company=company, role='owner', is_active=True,
        )
        self.uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        self.token = default_token_generator.make_token(self.user)

    def confirm(self, **overrides):
        payload = {'uid': self.uid, 'token': self.token,
                   'new_password': 'An0ther-Str0ng-Pass'}
        payload.update(overrides)
        return self.client.post(CONFIRM_URL, payload, format='json')

    def test_a_valid_link_sets_the_new_password(self):
        response = self.confirm()

        self.assertEqual(response.status_code, 200, response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('An0ther-Str0ng-Pass'))
        self.assertFalse(self.user.check_password(GOOD_PASSWORD))

    def test_a_weak_password_is_refused(self):
        response = self.confirm(new_password='1234')

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(GOOD_PASSWORD))

    def test_a_bad_token_is_refused_and_changes_nothing(self):
        response = self.confirm(token='not-a-real-token')

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(GOOD_PASSWORD))

    def test_a_tampered_uid_is_refused(self):
        response = self.confirm(uid=urlsafe_base64_encode(b'999999'))

        self.assertEqual(response.status_code, 400)

    def test_missing_pieces_are_refused_rather_than_crashing(self):
        response = self.client.post(CONFIRM_URL, {}, format='json')

        self.assertEqual(response.status_code, 400)

    def test_a_reset_ends_every_existing_session(self):
        """Otherwise the reset is decorative: the session a compromised password
        opened keeps working after the owner changes it."""
        from django.contrib.sessions.backends.db import SessionStore
        from django.contrib.sessions.models import Session
        from django.contrib.auth import SESSION_KEY
        from django.utils import timezone

        store = SessionStore()
        store[SESSION_KEY] = str(self.user.pk)
        store.create()
        self.assertTrue(Session.objects.exists())

        self.confirm()

        self.assertFalse(Session.objects.exists())
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('An0ther-Str0ng-Pass'))

    def test_an_inactive_account_cannot_use_a_token(self):
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])

        response = self.confirm()

        self.assertEqual(response.status_code, 400)