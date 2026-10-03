"""
Verification tests for the bug-fix pass. Temporary scaffolding.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import resolve, reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import Company, User
from accounts.platform_models import Subscription
from employees.models import Employee
from leave.models import LeaveBalance, LeaveRequest


def make_company(name, email):
    """Company + active subscription so IsCompanyActive passes."""
    company = Company.objects.create(name=name, email=email, is_active=True)
    Subscription.objects.create(
        company=company, status='active',
        started_at=timezone.now(), renews_at=timezone.now() + timedelta(days=30),
    )
    return company


class EmployeeProfileIdTests(TestCase):
    """#1: user.employee_profile_id raised AttributeError; my-profile always 404."""

    def setUp(self):
        self.company = make_company('Acme', 'acme@example.com')
        self.emp = Employee.objects.create(
            company=self.company, employee_code='E1', first_name='Eve', last_name='One',
            email='eve@example.com', base_salary=1000, department='Sales',
        )
        self.user = User.objects.create_user(
            username='eve', email='eve@example.com', password='StrongPassword123!',
            company=self.company, role='employee',
        )
        self.emp.user = self.user
        self.emp.save(update_fields=['user'])
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_employee_id_property(self):
        self.assertEqual(self.user.employee_id, self.emp.id)

    def test_employee_id_is_none_when_unlinked(self):
        other = User.objects.create_user(
            username='nobody', email='nobody@example.com', password='StrongPassword123!',
            company=self.company, role='employee',
        )
        self.assertIsNone(other.employee_id)

    def test_my_profile_no_longer_404s_for_linked_employee(self):
        response = self.client.get('/api/employees/employees/my-profile/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['employee_code'], 'E1')

    def test_employee_directory_is_scoped_to_self(self):
        other = Employee.objects.create(
            company=self.company, employee_code='E2', first_name='Otto', last_name='Two',
            email='otto@example.com', base_salary=1000, department='Engineering',
        )
        response = self.client.get('/api/employees/employees/')
        self.assertEqual(response.status_code, 200, response.data)
        codes = {e['employee_code'] for e in response.data.get('results', response.data)}
        self.assertIn('E1', codes)
        self.assertNotIn('E2', codes)

    def test_submit_self_request_accepted_for_linked_employee(self):
        response = self.client.post(
            '/api/employees/employees/submit-self-request/',
            {'request_type': 'personal_details', 'payload': {'first_name': 'Eve'}},
            format='json',
        )
        self.assertIn(response.status_code, (200, 201), response.data)

    def test_personal_details_list_endpoint_does_not_500(self):
        """#10: EmployeePersonalDetailsViewSet had no serializer_class -> 500."""
        response = self.client.get('/api/employees/personal-details/')
        self.assertEqual(response.status_code, 200, response.data)

    def test_photo_is_self_recognised(self):
        """#1: is_self was always False, so employees could never change own photo."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        png = b'\x89PNG\r\n\x1a\n' + b'0' * 32
        response = self.client.post(
            f'/api/employees/employees/{self.emp.id}/photo/',
            {'photo': SimpleUploadedFile('me.png', png, content_type='image/png')},
            format='multipart',
        )
        # A 403 here would mean is_self is still broken.
        self.assertNotEqual(response.status_code, 403, response.data)


class LeaveApprovalGuardTests(TestCase):
    """#2/#3: re-approval double-deducted; inverted dates credited the balance."""

    def setUp(self):
        self.company = make_company('Acme2', 'acme2@example.com')
        self.hr = User.objects.create_user(
            username='hr', email='hr@example.com', password='StrongPassword123!',
            company=self.company, role='hr',
        )
        self.emp = Employee.objects.create(
            company=self.company, employee_code='L1', first_name='Lee', last_name='One',
            email='lee@example.com', base_salary=1000,
        )
        LeaveBalance.objects.create(
            employee=self.emp, leave_type='annual', balance_days=Decimal('20'),
        )
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def test_double_approval_deducts_once(self):
        request = LeaveRequest.objects.create(
            employee=self.emp, leave_type='annual',
            start_date='2026-09-01', end_date='2026-09-05',  # 5 days
        )
        url = f'/api/leave/requests/{request.id}/approve/'
        first = self.client.post(url, {}, format='json')
        self.assertEqual(first.status_code, 200, first.data)

        balance = LeaveBalance.objects.get(employee=self.emp, leave_type='annual')
        self.assertEqual(balance.balance_days, Decimal('15'))

        second = self.client.post(url, {}, format='json')
        self.assertEqual(second.status_code, 409, second.data)

        balance.refresh_from_db()
        self.assertEqual(balance.balance_days, Decimal('15'), 'balance deducted twice')

    def test_approve_then_reject_restores_balance(self):
        request = LeaveRequest.objects.create(
            employee=self.emp, leave_type='annual',
            start_date='2026-09-01', end_date='2026-09-05',
        )
        self.client.post(f'/api/leave/requests/{request.id}/approve/', {}, format='json')
        reject = self.client.post(f'/api/leave/requests/{request.id}/reject/', {}, format='json')
        self.assertEqual(reject.status_code, 200, reject.data)
        balance = LeaveBalance.objects.get(employee=self.emp, leave_type='annual')
        self.assertEqual(balance.balance_days, Decimal('20'), 'days not credited back')

    def test_rejected_request_cannot_be_approved(self):
        request = LeaveRequest.objects.create(
            employee=self.emp, leave_type='annual',
            start_date='2026-09-01', end_date='2026-09-05', status='rejected',
        )
        response = self.client.post(f'/api/leave/requests/{request.id}/approve/', {}, format='json')
        self.assertEqual(response.status_code, 409, response.data)

    def test_inverted_date_range_is_rejected(self):
        response = self.client.post('/api/leave/requests/', {
            'employee': self.emp.id, 'leave_type': 'annual',
            'start_date': '2026-09-10', 'end_date': '2026-09-01',
        }, format='json')
        self.assertEqual(response.status_code, 400, response.data)

    def test_valid_range_accepted(self):
        response = self.client.post('/api/leave/requests/', {
            'employee': self.emp.id, 'leave_type': 'annual',
            'start_date': '2026-09-01', 'end_date': '2026-09-05',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['days_requested'], 5)


class RoutingTests(TestCase):
    """#8: bulk_salary_update shared url_path with salary_change and was shadowed."""

    def test_bulk_salary_update_is_distinct_route(self):
        match = resolve('/api/employees/employees/bulk-salary-update/')
        self.assertEqual(match.url_name, 'employee-bulk-salary-update')

    def test_single_salary_change_still_routes(self):
        match = resolve('/api/employees/employees/1/salary-change/')
        self.assertEqual(match.url_name, 'employee-salary-change')

    def test_bulk_salary_update_is_detail_false(self):
        from employees.views import EmployeeViewSet
        import inspect
        action = EmployeeViewSet.bulk_salary_update
        self.assertFalse(action.detail, 'bulk endpoint must be detail=False (no pk kwarg)')
        # detail=False means DRF calls handler(request) with no pk.
        params = list(inspect.signature(action).parameters)
        self.assertNotIn('pk', params)

    def test_bulk_salary_update_reports_unknown_employee_ids(self):
        """Ids outside the company must surface as failures, not silent success."""
        from accounts.models import Company
        from employees.models import Employee
        company = make_company('BulkCo', 'bulk@example.com')
        other = Company.objects.create(name='Other', email='other@example.com', is_active=True)
        stranger = Employee.objects.create(
            company=other, employee_code='X1', first_name='X', last_name='Y',
            email='x@example.com', base_salary=100,
        )
        hr = User.objects.create_user(
            username='bhr', email='bhr@example.com', password='StrongPassword123!',
            company=company, role='hr',
        )
        client = APIClient()
        client.force_authenticate(hr)
        response = client.post('/api/employees/employees/bulk-salary-update/', {
            'employees': [stranger.id], 'new_salary': '5000',
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['success'], [])
        self.assertEqual(len(response.data['failure']), 1)


class AuditCompanyTests(TestCase):
    """#6: AI audit() call sites passed a non-Company as the `company` arg."""

    def setUp(self):
        self.company = make_company('Acme5', 'acme5@example.com')

    def test_audit_rejects_non_company(self):
        from accounts.audit import audit
        from ai.models import AIConversation
        user = User.objects.create_user(
            username='aichat', email='aichat@example.com', password='StrongPassword123!',
            company=self.company, role='owner',
        )
        conversation = AIConversation.objects.create(company=self.company, user=user, title='t')
        with self.assertRaises(ValueError):
            audit(None, 'ai_chat', 'msg', conversation, 'ai_conversation', conversation.id)

    def test_audit_accepts_company(self):
        from accounts.audit import audit
        from accounts.platform_models import AuditLog
        audit(None, 'ai_chat', 'msg', self.company, 'ai_conversation', 1)
        self.assertEqual(AuditLog.objects.count(), 1)


class LogoutTests(TestCase):
    """#4: SPA logout hit LogoutView, which only deleted a DRF Token."""

    def setUp(self):
        self.company = make_company('Acme3', 'acme3@example.com')
        self.user = User.objects.create_user(
            username='bob', email='bob@example.com', password='StrongPassword123!',
            company=self.company, role='owner',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_logout_revokes_security_session_and_clears_cookie(self):
        from security.models import SecuritySession
        import hashlib
        raw = 'a' * 64
        session = SecuritySession.objects.create(
            user=self.user, company=self.company,
            secret_hash=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(hours=12),
        )
        self.client.cookies['hrcloudpay_session'] = raw
        # Authenticate the way the SPA does: via the security cookie.
        self.client.force_authenticate(self.user, token=session)

        response = self.client.post('/api/auth/logout/', {}, format='json')
        self.assertIn(response.status_code, (200, 204), response.status_code)
        session.refresh_from_db()
        self.assertIsNotNone(session.revoked_at, 'SecuritySession was not revoked')
        self.assertIn('hrcloudpay_session', response.cookies)
        self.assertEqual(response.cookies['hrcloudpay_session'].value, '')


class FeatureFlagTests(TestCase):
    """#12: require_feature() never passed company, so rollout_percent was ignored."""

    def setUp(self):
        self.company = make_company('Acme4', 'acme4@example.com')

    def test_partial_rollout_buckets_by_company(self):
        from accounts.features import is_feature_enabled
        from accounts.platform_models import FeatureFlag
        FeatureFlag.objects.update_or_create(
            key='payroll_overtime',
            defaults={'name': 'Overtime', 'description': '', 'enabled': True,
                      'rollout_percent': 10, 'environment': 'all'},
        )
        # bucket = company.id % 100; a bucket at/above rollout_percent is excluded.
        self.company.id = 15
        self.assertFalse(is_feature_enabled('payroll_overtime', company=self.company))
        self.company.id = 5
        self.assertTrue(is_feature_enabled('payroll_overtime', company=self.company))

    def test_require_feature_accepts_company(self):
        from accounts.features import require_feature
        from accounts.platform_models import FeatureFlag
        FeatureFlag.objects.update_or_create(
            key='payroll_overtime',
            defaults={'name': 'Overtime', 'description': '', 'enabled': True,
                      'rollout_percent': 10, 'environment': 'all'},
        )
        self.company.id = 15
        ok, response = require_feature('payroll_overtime', company=self.company)
        self.assertFalse(ok)
        self.assertEqual(response.status_code, 403)
        self.company.id = 5
        ok, response = require_feature('payroll_overtime', company=self.company)
        self.assertTrue(ok)
        self.assertIsNone(response)


class FeatureUnavailableMessageTests(TestCase):
    """The 403 body must describe what actually happened, not always blame an admin.

    The old message claimed a platform administrator had disabled the feature
    for every 403, and pointed users at a support channel they cannot reach:
    /auth/platform/support/ is IsAdminUser, and no support inbox is configured.
    """

    def setUp(self):
        self.company = make_company('Acme5', 'acme5@example.com')

    def _flag(self, **defaults):
        from accounts.platform_models import FeatureFlag
        base = {'name': 'Salary advances', 'description': '', 'enabled': True,
                'rollout_percent': 100, 'environment': 'all'}
        base.update(defaults)
        return FeatureFlag.objects.update_or_create(key='payroll_salary_advances',
                                                    defaults=base)[0]

    def _detail(self):
        from accounts.features import require_feature
        ok, response = require_feature('payroll_salary_advances', company=self.company)
        self.assertFalse(ok)
        self.assertEqual(response.status_code, 403)
        return response.data

    def test_disabled_flag_blames_the_administrator(self):
        self._flag(enabled=False)
        body = self._detail()
        self.assertEqual(body['reason'], 'disabled')
        self.assertIn('turned off for your workspace', body['detail'])

    def test_partial_rollout_does_not_claim_an_admin_decision(self):
        """The damaging case: the tenant is simply not in the cohort yet."""
        self._flag(rollout_percent=10)
        self.company.id = 42
        body = self._detail()
        self.assertEqual(body['reason'], 'rollout_bucket')
        self.assertNotIn('administrator', body['detail'])
        self.assertIn('rolled out gradually', body['detail'])
        # It must not tell the user to go and chase somebody, because no human
        # decision is involved and it may arrive on its own.
        self.assertIn('no action is needed', body['detail'])

    def test_zero_percent_rollout_reads_as_paused_not_denied(self):
        self._flag(rollout_percent=0)
        body = self._detail()
        self.assertEqual(body['reason'], 'rollout_zero')
        self.assertIn('paused', body['detail'])
        self.assertNotIn('administrator', body['detail'])

    def test_environment_restriction_is_named_as_such(self):
        """A test/live-scoped flag must be reported as an environment restriction.

        Which scope actually blocks depends on DEBUG, and the test runner forces
        DEBUG=False - so derive the blocking scope rather than assuming it.
        """
        from django.conf import settings
        blocked_env = 'test' if not settings.DEBUG else 'live'
        self._flag(environment=blocked_env)
        body = self._detail()
        self.assertEqual(body['reason'], 'environment')
        self.assertIn('not available in this environment', body['detail'])

    def test_environment_matching_the_running_one_is_not_blocked(self):
        from django.conf import settings
        self._flag(environment='all')
        from accounts.features import is_feature_enabled
        self.assertTrue(is_feature_enabled('payroll_salary_advances',
                                           company=self.company))
        # The scope that MATCHES the running environment is the opposite of the
        # one that blocks: DEBUG=False means 'live' is the permitted scope.
        if settings.DEBUG:
            self._flag(environment='test')
        else:
            self._flag(environment='live')
        self.assertTrue(is_feature_enabled('payroll_salary_advances',
                                           company=self.company))

    def test_no_message_invents_a_support_channel(self):
        """There is no support inbox, and the ticket endpoint is admin-only."""
        from accounts.features import (REASON_DISABLED, REASON_ENVIRONMENT,
                                       REASON_ROLLOUT_BUCKET,
                                       REASON_ROLLOUT_ZERO,
                                       feature_unavailable_message)
        reasons = [REASON_DISABLED, REASON_ENVIRONMENT,
                   REASON_ROLLOUT_ZERO, REASON_ROLLOUT_BUCKET]
        for reason in reasons:
            detail = feature_unavailable_message('Salary advances', reason)
            self.assertNotIn('contact support', detail.lower())
            self.assertNotIn('@', detail)

    def test_unknown_reason_falls_back_to_safe_wording(self):
        from accounts.features import feature_unavailable_message
        detail = feature_unavailable_message('Salary advances', 'something_new')
        self.assertIn('turned off for your workspace', detail)

    def test_is_feature_enabled_still_returns_a_plain_bool(self):
        """Existing callers rely on this returning True/False, not a tuple."""
        from accounts.features import is_feature_enabled
        self._flag(enabled=False)
        self.assertIs(is_feature_enabled('payroll_salary_advances',
                                        company=self.company), False)
        self._flag(enabled=True)
        self.assertIs(is_feature_enabled('payroll_salary_advances',
                                        company=self.company), True)

    def test_public_feature_map_shape_is_unchanged(self):
        """public_feature_map() is consumed as {key: bool} by the frontend."""
        from accounts.features import public_feature_map
        self._flag(enabled=False)
        m = public_feature_map(company=self.company)
        self.assertIsInstance(m['payroll_salary_advances'], bool)

    def test_status_map_carries_the_reason(self):
        from accounts.features import public_feature_status_map
        self._flag(enabled=False)
        m = public_feature_status_map(company=self.company)
        self.assertFalse(m['payroll_salary_advances']['enabled'])
        self.assertEqual(m['payroll_salary_advances']['reason'], 'disabled')
        self.assertIn('turned off', m['payroll_salary_advances']['message'])
        self._flag(enabled=True)
        m = public_feature_status_map(company=self.company)
        self.assertEqual(m['payroll_salary_advances']['reason'], '')
        self.assertEqual(m['payroll_salary_advances']['message'], '')

    def test_status_map_message_matches_the_403_body_wording(self):
        """One home for the wording: the panel and the 403 must not disagree."""
        from accounts.features import public_feature_status_map, require_feature
        self._flag(enabled=False)
        status = public_feature_status_map(company=self.company)
        ok, response = require_feature('payroll_salary_advances', company=self.company)
        self.assertFalse(ok)
        self.assertEqual(response.data['detail'],
                         status['payroll_salary_advances']['message'])

    def test_status_map_reports_rollout_bucket_for_this_tenant(self):
        from accounts.features import public_feature_status_map
        self._flag(enabled=True, rollout_percent=10)
        self.company.id = 42
        m = public_feature_status_map(company=self.company)
        self.assertEqual(m['payroll_salary_advances']['reason'], 'rollout_bucket')
        self.assertNotIn('administrator', m['payroll_salary_advances']['message'])

    def test_endpoint_returns_features_and_reasons(self):
        """The UI needs both, and must not have to infer the reason."""
        from rest_framework.test import APIClient
        self._flag(enabled=False)
        user = User.objects.create_user(
            username='flaguser', email='flaguser@example.com',
            password='StrongPassword123!', company=self.company, role='owner',
        )
        client = APIClient()
        client.force_authenticate(user)
        r = client.get('/api/auth/features/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn('features', body)
        self.assertIn('reasons', body)
        self.assertIs(body['features']['payroll_salary_advances'], False)
        self.assertEqual(body['reasons']['payroll_salary_advances'], 'disabled')
        self.assertIn('turned off', body['messages']['payroll_salary_advances'])
        # An enabled feature must not be listed as having a reason.
        self.assertNotIn('payroll_bank_file', body['reasons'])
        self.assertNotIn('payroll_bank_file', body['messages'])


class SeedCommandTests(TestCase):
    """#7: seed_country_rules referenced an undefined PAYE_RULES -> NameError."""

    def test_command_runs(self):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('seed_country_rules', stdout=out)
        from regional.models import StatutoryRule
        self.assertGreater(StatutoryRule.objects.filter(rule_type='paye').count(), 0)
        self.assertIn('PAYE', out.getvalue())
