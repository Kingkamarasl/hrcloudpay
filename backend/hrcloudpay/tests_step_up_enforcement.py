"""Step-up MFA must actually gate the sensitive actions.

These are the end-to-end tests for the control itself: payroll approval, payroll
payment, and salary-change approval must refuse a session that has not cleared a
TOTP challenge recently, and must allow it once it has.

MFA is genuinely enrolled and the codes are computed from the real secret, so
nothing here is mocked away from the actual check.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import Company, User
from accounts.platform_models import Subscription
from employees.models import Employee, HRRequest
from payroll.models import PayrollRun
from security.models import MFADevice, SecuritySession
from accounts.secrets import encrypt_secret
from security.utils import hash_value, totp_code, totp_secret


class StepUpGateMixin:
    def _session(self, user, *, fresh):
        raw = f'session-{user.username}-{"fresh" if fresh else "stale"}'
        session = SecuritySession.objects.create(
            user=user, company=user.company, secret_hash=hash_value(raw),
            expires_at=timezone.now() + timedelta(hours=8), mfa_verified=fresh,
            mfa_verified_at=timezone.now() if fresh else None,
        )
        self.client.cookies['hrcloudpay_session'] = raw
        return session


class PayrollStepUpTests(StepUpGateMixin, TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='PayCo', email='pay@example.com', is_active=True)
        Subscription.objects.create(company=self.company, status='trial')
        self.user = User.objects.create_user(
            username='fin', email='fin@example.com', password='Str0ngPass-2026',
            company=self.company, role='admin',
        )
        self.secret = totp_secret()
        self.device = MFADevice.objects.create(
            user=self.user, secret_encrypted=encrypt_secret(self.secret), enabled=True,
        )
        self.run = PayrollRun.objects.create(
            company=self.company, period_start='2026-01-01', period_end='2026-01-31',
            status='processed',
        )

    def test_approval_is_refused_without_fresh_mfa(self):
        self._session(self.user, fresh=False)

        response = self.client.post(f'/api/payroll/runs/{self.run.id}/approve/', {})

        self.assertEqual(response.status_code, 403)
        self.run.refresh_from_db()
        self.assertEqual(self.run.status, 'processed', 'payroll was approved without MFA')

    def test_approval_proceeds_after_step_up(self):
        self._session(self.user, fresh=False)
        refused = self.client.post(f'/api/payroll/runs/{self.run.id}/approve/', {})
        self.assertEqual(refused.status_code, 403)

        stepped_up = self.client.post(
            '/api/auth/security/mfa/step-up/',
            {'code': totp_code(self.secret)}, content_type='application/json',
        )
        self.assertEqual(stepped_up.status_code, 200)

        approved = self.client.post(f'/api/payroll/runs/{self.run.id}/approve/', {})
        self.assertEqual(approved.status_code, 200, approved.content)
        self.run.refresh_from_db()
        self.assertEqual(self.run.status, 'approved')

    def test_payment_is_refused_without_fresh_mfa(self):
        self.run.status = 'approved'
        self.run.save(update_fields=['status'])
        self._session(self.user, fresh=False)

        response = self.client.post(
            f'/api/payroll/runs/{self.run.id}/pay/',
            {'payment_method': 'bank_transfer', 'payment_reference': 'REF-1'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)
        self.run.refresh_from_db()
        self.assertEqual(self.run.status, 'approved', 'payment recorded without MFA')

    def test_reads_are_not_blocked(self):
        """Step-up guards actions, not browsing."""
        self._session(self.user, fresh=False)

        response = self.client.get('/api/payroll/runs/')

        self.assertEqual(response.status_code, 200)

    def test_user_without_mfa_is_told_to_enroll(self):
        device = MFADevice.objects.filter(user=self.user).first()
        if device:
            device.delete()
        self._session(self.user, fresh=False)

        response = self.client.post(f'/api/payroll/runs/{self.run.id}/approve/', {})

        self.assertEqual(response.status_code, 403)
        body = response.json()
        self.assertEqual(body.get('code'), 'mfa_required')
        self.assertTrue(body.get('enrollment_required'))
        self.run.refresh_from_db()
        self.assertEqual(self.run.status, 'processed', 'payroll was approved without MFA')

    def test_token_authenticated_clients_cannot_approve_payroll(self):
        """A DRF token has no session to stamp, so a headless integration
        cannot move money. Refused explicitly rather than waved through."""
        from rest_framework.authtoken.models import Token
        from rest_framework.test import APIClient
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION='Token ' + Token.objects.create(user=self.user).key)

        response = api.post(f'/api/payroll/runs/{self.run.id}/approve/', {})

        self.assertEqual(response.status_code, 403)
        self.run.refresh_from_db()
        self.assertEqual(self.run.status, 'processed')


class SalaryChangeStepUpTests(StepUpGateMixin, TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='HrCo', email='hr@example.com', is_active=True)
        Subscription.objects.create(company=self.company, status='trial')
        self.user = User.objects.create_user(
            username='boss', email='boss@example.com', password='Str0ngPass-2026',
            company=self.company, role='owner',
        )
        self.secret = totp_secret()
        self.device = MFADevice.objects.create(
            user=self.user, secret_encrypted=encrypt_secret(self.secret), enabled=True,
        )
        self.employee = Employee.objects.create(
            company=self.company, first_name='Ama', last_name='Bello',
            employee_code='E1', email='ama@example.com', base_salary=5000,
        )
        self.request = HRRequest.objects.create(
            employee=self.employee, requested_by=self.user, request_type='salary',
            payload={'new_salary': 9000, 'reason': 'Annual review'}, status='pending',
        )
        self._session(self.user, fresh=False)

    def test_salary_approval_is_refused_without_fresh_mfa(self):
        response = self.client.post(f'/api/employees/hr-requests/{self.request.id}/approve/', {})

        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.json().get('mfa_required'))
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, 'pending')
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.base_salary, 5000, 'salary changed without MFA')

    def test_salary_approval_proceeds_after_step_up(self):
        self.client.post('/api/auth/security/mfa/step-up/',
                         {'code': totp_code(self.secret)}, content_type='application/json')

        response = self.client.post(f'/api/employees/hr-requests/{self.request.id}/approve/', {})

        self.assertEqual(response.status_code, 200, response.content)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, 'approved')

    def test_rejecting_does_not_require_mfa(self):
        """Refusing a change cannot move money, so it should not be gated."""
        response = self.client.post(f'/api/employees/hr-requests/{self.request.id}/reject/', {})

        self.assertEqual(response.status_code, 200, response.content)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, 'rejected')
