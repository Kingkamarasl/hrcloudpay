"""Regression tests for the security hardening pass.

Each test targets a specific weakness that existed before:

* login / MFA accepted unlimited per-account attempts from rotating IPs;
* `/auth/login/` and `/auth/register/` returned an unrotatable DRF token;
* `MFAView` setup let any live session silently strip an active factor;
* payroll approval and salary changes needed no second factor at all;
* no Content-Security-Policy was sent.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.db import OperationalError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token

from accounts.models import Company, User
from security.login_lockout import check_locked, get_lockout, record_failure, record_success
from security.models import LoginThrottle, SecuritySession
from security.step_up import mfa_is_fresh
from security.utils import hash_value, totp_code, totp_secret
from security.models import MFADevice
from accounts.secrets import encrypt_secret


def make_company(name='Acme'):
    return Company.objects.create(name=name, email=f'{name.lower()}@example.com')


def make_user(username, company=None, role='owner', **extra):
    return User.objects.create_user(
        username=username, email=f'{username}@example.com',
        password='Str0ngPass-2026', company=company or make_company(username), role=role, **extra,
    )


class LoginLockoutTests(TestCase):
    def test_failures_accumulate_against_the_account(self):
        for _ in range(3):
            record_failure('username', 'victim')

        self.assertEqual(LoginThrottle.objects.get(identifier='username:victim').failure_count, 3)

    def test_lockout_kicks_in_at_the_threshold(self):
        for _ in range(5):
            remaining = record_failure('username', 'victim')

        self.assertGreater(remaining, 0)
        self.assertGreater(check_locked('username', 'victim'), 0)

    def test_lockout_is_progressive_then_capped(self):
        """A fixed delay would let a script retry forever at a steady rate.
        The delay grows with each failure and then plateaus at a ceiling, so a
        determined attacker cannot push the penalty arbitrarily high (which
        would be a denial-of-service against a real user)."""
        delays = []
        for _ in range(10):
            record_failure('username', 'victim')
            delays.append(check_locked('username', 'victim'))

        # Nothing is locked below the threshold (5 consecutive failures).
        self.assertEqual(delays[:4], [0, 0, 0, 0])
        # The first lockout is short - a user who mistyped should not be locked
        # out for an hour - and every further failure lengthens it.
        self.assertGreater(delays[4], 0)
        self.assertLess(delays[4], 60)
        # Failures 5..8 step up the ramp: 30s, 60s, 300s, 900s.
        for earlier, later in zip(delays[4:8], delays[5:9]):
            self.assertGreater(later, earlier)
        # Failure 9 onward is held at the ceiling, so the penalty cannot be
        # pushed indefinitely by a determined attacker.
        self.assertEqual(delays[9], delays[8])

    def test_success_clears_the_counter(self):
        for _ in range(3):
            record_failure('username', 'victim')
        record_success('username', 'victim')

        self.assertEqual(LoginThrottle.objects.get(identifier='username:victim').failure_count, 0)
        self.assertEqual(check_locked('username', 'victim'), 0)

    def test_identifier_is_normalised(self):
        """Case and whitespace differences must not hand out extra attempts."""
        record_failure('username', '  Victim  ')
        record_failure('username', 'victim')

        self.assertEqual(LoginThrottle.objects.count(), 1)
        self.assertEqual(LoginThrottle.objects.get().failure_count, 2)


class MissingLockoutTableTests(TestCase):
    """A checkout without `security/0003` must still be able to sign in.

    The regression: `SecureLoginView` calls `check_locked()` *before* it
    authenticates, so on any database missing `security_loginthrottle` every
    sign-in - right password or wrong - returned 500, and there was no way to
    log in to diagnose it. The view already guarded `emit()` and the MFA device
    lookup for exactly this; the lockout calls were the earliest caller in the
    function and had been missed, which is why applying the migration was the
    only way out.
    """

    ERROR = OperationalError('no such table: security_loginthrottle')

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.company = make_company('BootstrapCo')
        self.user = make_user('bob', self.company)

    def _without_the_table(self):
        """Make every `LoginThrottle` query fail the way a missing table does."""
        manager = MagicMock()
        manager.filter.side_effect = self.ERROR
        manager.select_for_update.return_value.get_or_create.side_effect = self.ERROR
        return patch.object(LoginThrottle, 'objects', manager)

    def _post(self, password='Str0ngPass-2026'):
        return self.client.post(
            '/api/auth/security/login/',
            {'username': 'bob', 'password': password},
            content_type='application/json',
        )

    @override_settings(DEBUG=True)
    def test_development_sign_in_survives_the_missing_table(self):
        """The whole point: a correct password still signs in rather than 500."""
        with self._without_the_table():
            response = self._post()

        self.assertEqual(response.status_code, 200,
                         'login is unreachable when security/0003 is unapplied')

    @override_settings(DEBUG=True)
    def test_a_wrong_password_still_reports_401_rather_than_500(self):
        with self._without_the_table():
            response = self._post(password='wrong')

        self.assertEqual(response.status_code, 401)

    @override_settings(DEBUG=False)
    def test_production_fails_loudly_rather_than_silently_dropping_the_lockout(self):
        """Serving logins with brute-force protection quietly disabled is a
        security downgrade nobody chose. A missing table in production is a
        deployment fault and must be visible, so it re-raises."""
        with self._without_the_table():
            with self.assertRaises(OperationalError):
                self._post()

    @override_settings(DEBUG=True)
    def test_the_helpers_degrade_to_their_documented_fallbacks(self):
        """None means "not locked" and 0 means "no seconds left", so a caller
        cannot mistake an absent table for an active lockout."""
        with self._without_the_table():
            self.assertIsNone(get_lockout('username', 'bob'))
            self.assertEqual(check_locked('username', 'bob'), 0)
            self.assertEqual(record_failure('username', 'bob'), 0)
            self.assertIsNone(record_success('username', 'bob'))


class SecureLoginThrottleTests(TestCase):
    """`/auth/security/login/` is the live endpoint the SPA uses."""

    def setUp(self):
        # DRF throttling is cache-backed and survives between tests, so clear
        # it or a previous test's budget silently throttles this one.
        from django.core.cache import cache
        cache.clear()
        self.company = make_company('LoginCo')
        self.user = make_user('alice', self.company)

    def _post(self, username, password='wrong'):
        return self.client.post(
            '/api/auth/security/login/',
            {'username': username, 'password': password},
            content_type='application/json',
        )

    def test_bad_credentials_are_audited(self):
        from security.models import SecurityEvent
        self._post('alice')

        self.assertTrue(SecurityEvent.objects.filter(event_type='login_failed').exists())

    def test_account_locks_out_after_repeated_failures(self):
        """The regression: previously every attempt just returned 401 forever.

        Kept under the per-IP scoped rate so this asserts the per-account
        lockout specifically rather than DRF's throttle.
        """
        statuses = [self._post('alice').status_code for _ in range(6)]

        self.assertIn(429, statuses, 'account was never locked out')
        locked = self._post('alice')
        self.assertEqual(locked.status_code, 429)
        self.assertIn('locked_for', locked.json())
        self.assertIn('Retry-After', locked.headers)

    def test_lockout_does_not_leak_whether_the_account_exists(self):
        """The message must be identical for a real and a nonexistent user.

        DRF's per-IP throttle is cleared between the two so this compares the
        account-lockout response, not the shared rate limiter.
        """
        from django.core.cache import cache
        for _ in range(5):
            self._post('alice')
        real = self._post('alice')
        cache.clear()
        for _ in range(5):
            self._post('ghost')
        fake = self._post('ghost')

        self.assertEqual(real.status_code, fake.status_code)
        self.assertEqual(real.json()['detail'], fake.json()['detail'])
        self.assertNotIn('alice', str(real.json()))

    def test_correct_password_still_works_when_not_locked(self):
        response = self._post('alice', 'Str0ngPass-2026')

        self.assertEqual(response.status_code, 200)
        self.assertIn('hrcloudpay_session', response.cookies)

    def test_successful_login_clears_earlier_failures(self):
        for _ in range(3):
            self._post('alice')
        ip_record = LoginThrottle.objects.filter(identifier_type='ip').first()
        self.assertIsNotNone(ip_record, 'failed attempts should be counted per IP too')
        ip_record.failure_count = 3
        ip_record.save(update_fields=['failure_count'])
        response = self._post('alice', 'Str0ngPass-2026')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(LoginThrottle.objects.get(identifier='username:alice').failure_count, 0)
        ip_record.refresh_from_db()
        self.assertEqual(ip_record.failure_count, 0)


@override_settings(THROTTLE_LOGIN_RATE='3/minute')
class ScopedThrottleTests(TestCase):
    """DRF ScopedRateThrottle is the per-IP half; the lockout is the per-account half."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.company = make_company('ThrottleCo')
        self.user = make_user('bob', self.company)

    def test_repeated_requests_are_throttled_by_rate(self):
        statuses = []
        for _ in range(6):
            response = self.client.post(
                '/api/auth/security/login/',
                {'username': 'bob', 'password': 'nope'},
                content_type='application/json',
            )
            statuses.append(response.status_code)

        self.assertIn(429, statuses)


class NoPermanentTokenTests(TestCase):
    def setUp(self):
        self.company = make_company('TokenCo')
        self.user = make_user('carol', self.company)

    def test_login_does_not_issue_a_permanent_token(self):
        response = self.client.post(
            '/api/auth/login/',
            {'username': 'carol', 'password': 'Str0ngPass-2026'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('token', response.json())
        self.assertFalse(Token.objects.filter(user=self.user).exists())

    def test_register_does_not_issue_a_token(self):
        response = self.client.post(
            '/api/auth/register/',
            {'company_name': 'New Co', 'email': 'owner@newco.example',
             'password': 'Str0ngPass-2026', 'name': 'Owner'},
            content_type='application/json',
        )

        self.assertIn(response.status_code, (201, 400))
        if response.status_code == 201:
            self.assertNotIn('token', response.json())
            self.assertFalse(Token.objects.exists())

    def test_revoke_command_clears_existing_tokens(self):
        Token.objects.create(user=self.user)
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command('revoke_api_tokens', stdout=out)

        self.assertFalse(Token.objects.exists())
        self.assertIn('Revoked 1', out.getvalue())


class MFAStripTests(TestCase):
    def setUp(self):
        self.company = make_company('MfaCo')
        self.user = make_user('dave', self.company)
        self.secret = totp_secret()
        self.device = MFADevice.objects.create(
            user=self.user, secret_encrypted=encrypt_secret(self.secret), enabled=True,
        )
        self.raw = 'session-secret-value'
        self.session = SecuritySession.objects.create(
            user=self.user, company=self.company, secret_hash=hash_value(self.raw),
            expires_at=timezone.now() + timedelta(hours=8), mfa_verified=True,
        )
        self.client.cookies['hrcloudpay_session'] = self.raw

    def test_setup_cannot_silently_replace_an_active_factor(self):
        """The regression: setup overwrote the secret and disabled MFA outright.

        Anyone holding a live session cookie could downgrade the account to
        MFA-less and then phish the replacement code.
        """
        response = self.client.post(
            '/api/auth/security/mfa/',
            {'action': 'setup'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.json().get('code_required'))
        self.device.refresh_from_db()
        self.assertTrue(self.device.enabled)

    def test_setup_allowed_with_the_current_code(self):
        response = self.client.post(
            '/api/auth/security/mfa/',
            {'action': 'setup', 'code': totp_code(self.secret)},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('secret', response.json())

    def test_disable_requires_the_current_code(self):
        response = self.client.post(
            '/api/auth/security/mfa/',
            {'action': 'disable', 'code': '000000'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.device.refresh_from_db()
        self.assertTrue(self.device.enabled)

    def test_step_up_stamps_the_current_session(self):
        response = self.client.post(
            '/api/auth/security/mfa/step-up/',
            {'code': totp_code(self.secret)}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.mfa_verified_at)

    def test_step_up_rejects_a_bad_code(self):
        response = self.client.post(
            '/api/auth/security/mfa/step-up/',
            {'code': '000000'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.mfa_verified_at)


class StepUpFreshnessTests(TestCase):
    def test_session_with_fresh_mfa_passes(self):
        session = SecuritySession(mfa_verified=True, mfa_verified_at=timezone.now())

        self.assertTrue(mfa_is_fresh(session))

    def test_stale_mfa_fails(self):
        session = SecuritySession(
            mfa_verified=True,
            mfa_verified_at=timezone.now() - timedelta(hours=2),
        )

        self.assertFalse(mfa_is_fresh(session))

    def test_unverified_session_fails(self):
        self.assertFalse(mfa_is_fresh(SecuritySession(mfa_verified=False, mfa_verified_at=timezone.now())))

    def test_none_session_fails(self):
        self.assertFalse(mfa_is_fresh(None))

    def test_plain_login_is_not_a_step_up(self):
        """A session created without clearing a TOTP challenge must not count,
        otherwise step-up would be decorative."""
        session = SecuritySession(mfa_verified=True, mfa_verified_at=None, created_at=timezone.now())

        self.assertFalse(mfa_is_fresh(session))


class ContentSecurityPolicyTests(TestCase):
    def test_csp_header_is_present(self):
        response = self.client.get('/api/auth/security/csrf/')

        self.assertIn('Content-Security-Policy', response)
        policy = response['Content-Security-Policy']
        self.assertIn("default-src 'self'", policy)
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertIn("object-src 'none'", policy)

    def test_no_unsafe_eval_in_script_src(self):
        response = self.client.get('/api/auth/security/csrf/')

        self.assertNotIn('unsafe-eval', response['Content-Security-Policy'])

    @override_settings(CSP_REPORT_ONLY=True)
    def test_report_only_mode(self):
        response = self.client.get('/api/auth/security/csrf/')

        self.assertIn('Content-Security-Policy-Report-Only', response)
        self.assertNotIn('Content-Security-Policy', response)

    @override_settings(CSP_DIRECTIVES="default-src 'none'")
    def test_policy_can_be_overridden(self):
        response = self.client.get('/api/auth/security/csrf/')

        self.assertEqual(response['Content-Security-Policy'], "default-src 'none'")
