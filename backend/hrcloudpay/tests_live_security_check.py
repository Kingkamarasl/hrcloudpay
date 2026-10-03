"""Live end-to-end verification of the security hardening (not a unit test).

Run with:  python manage.py test hrcloudpay.tests_live_security_check -v 2
Uses the Django test client against a real database, so routing, throttling,
cookies and the audit chain all behave as they do in production.
"""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token

from accounts.models import Company, User
from accounts.platform_models import AuditLog, Subscription
from payroll.models import PayrollRun
from security.models import MFADevice, SecuritySession
from security.utils import hash_value, totp_code, totp_secret
from accounts.secrets import encrypt_secret


@override_settings(ALLOWED_HOSTS=['*'])
class LiveSecurityCheckTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Live Co', email='live@example.com', is_active=True)
        Subscription.objects.create(company=self.company, status='trial')
        self.user = User.objects.create_user(
            username='liveuser', email='live@example.com', password='Str0ngPass-2026',
            company=self.company, role='owner',
        )

    def test_1_login_returns_no_permanent_token(self):
        response = self.client.post(
            '/api/auth/login/',
            {'username': 'liveuser', 'password': 'Str0ngPass-2026'},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('token', response.json())
        self.assertEqual(Token.objects.count(), 0)

    def test_2_step_up_endpoint_is_routed(self):
        response = self.client.post('/api/auth/security/mfa/step-up/', {}, content_type='application/json')
        self.assertEqual(response.status_code, 403)  # routed, just unauthenticated

    def test_3_payroll_approval_gated_and_step_up_flow(self):
        self.secret = totp_secret()
        MFADevice.objects.create(
            user=self.user, secret_encrypted=encrypt_secret(self.secret), enabled=True,
        )
        raw = 'live-session'
        SecuritySession.objects.create(
            user=self.user, company=self.company, secret_hash=hash_value(raw),
            expires_at=timezone.now() + timedelta(hours=1),
            mfa_verified=False, mfa_verified_at=None,
        )
        self.client.cookies['hrcloudpay_session'] = raw
        run = PayrollRun.objects.create(
            company=self.company, period_start='2026-02-01', period_end='2026-02-28', status='processed',
        )
        refused = self.client.post(f'/api/payroll/runs/{run.id}/approve/', {})
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(refused.json().get('code'), 'mfa_required')

        stepped = self.client.post(
            '/api/auth/security/mfa/step-up/', {'code': totp_code(self.secret)}, content_type='application/json',
        )
        self.assertEqual(stepped.status_code, 200)
        approved = self.client.post(f'/api/payroll/runs/{run.id}/approve/', {})
        self.assertEqual(approved.status_code, 200, approved.content)

    def test_4_login_locks_out_after_repeated_failures(self):
        from django.core.cache import cache
        cache.clear()
        statuses = []
        for _ in range(6):
            r = self.client.post(
                '/api/auth/security/login/',
                {'username': 'liveuser', 'password': 'wrong'},
                content_type='application/json',
            )
            statuses.append(r.status_code)
        self.assertIn(429, statuses, f'no lockout: {statuses}')

    def test_5_csp_header_is_live(self):
        r = self.client.get('/api/auth/security/csrf/')
        self.assertIn('Content-Security-Policy', r)
        self.assertIn("default-src 'self'", r['Content-Security-Policy'])

    def test_6_audit_chain_verifies_after_real_activity(self):
        from accounts.audit_chain import verify_chain
        AuditLog.objects.create(action='login', message='live check')
        v = verify_chain()
        self.assertTrue(v['ok'], v['problems'])
        self.assertGreaterEqual(v['checked'], 1)
