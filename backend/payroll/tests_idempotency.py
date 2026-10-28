import hashlib
import json
from datetime import date, timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Company, IdempotencyRecord, User
from accounts.platform_models import Subscription
from employees.models import Employee
from payroll.models import PayrollConfig, PayrollRun, Payslip, TaxBracket


def empty_body_hash():
    return hashlib.sha256(
        json.dumps({}, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()


class PayrollIdempotencyTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name='Idempotency Co', email='idempotency@example.com', is_active=True)
        Subscription.objects.create(company=self.company, status='trial')
        self.user = User.objects.create_user(username='idempotency-owner', email='owner@idempotency.example', password='StrongPassword123!', company=self.company, role='owner')
        self.client.force_authenticate(self.user)
        config = PayrollConfig.objects.create(company=self.company, currency='USD')
        TaxBracket.objects.create(payroll_config=config, min_amount=0, max_amount=None, rate=0)
        Employee.objects.create(company=self.company, employee_code='IDEMP-1', first_name='Safe', last_name='Retry', email='safe@example.com', base_salary=1000)
        self.run = PayrollRun.objects.create(company=self.company, period_start=date(2027, 2, 1), period_end=date(2027, 2, 28))

    def test_repeated_processing_key_returns_original_result_without_duplicates(self):
        path = f'/api/payroll/runs/{self.run.id}/process/'
        first = self.client.post(path, {}, format='json', HTTP_IDEMPOTENCY_KEY='process-2027-02')
        second = self.client.post(path, {}, format='json', HTTP_IDEMPOTENCY_KEY='process-2027-02')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data, second.data)
        self.assertEqual(Payslip.objects.filter(payroll_run=self.run).count(), 1)

    def test_reusing_key_with_different_body_is_rejected(self):
        path = f'/api/payroll/runs/{self.run.id}/process/'
        self.assertEqual(self.client.post(path, {'preview': False}, format='json', HTTP_IDEMPOTENCY_KEY='process-body').status_code, 200)
        response = self.client.post(path, {'preview': True}, format='json', HTTP_IDEMPOTENCY_KEY='process-body')
        self.assertEqual(response.status_code, 409)
        self.assertIn('different request body', response.data['detail'])

    def _processing_record(self, key, started_at):
        """The row a request leaves behind when its worker dies mid-flight."""
        return IdempotencyRecord.objects.create(
            company=self.company,
            actor=self.user,
            key=key,
            operation=f'payroll.process:{self.run.id}',
            request_hash=empty_body_hash(),
            status='processing',
            started_at=started_at,
        )

    @override_settings(IDEMPOTENCY_STALE_SECONDS=60)
    def test_crashed_processing_key_is_taken_over_after_the_window(self):
        path = f'/api/payroll/runs/{self.run.id}/process/'
        record = self._processing_record('process-crashed', timezone.now() - timedelta(minutes=5))

        response = self.client.post(path, {}, format='json', HTTP_IDEMPOTENCY_KEY='process-crashed')

        self.assertEqual(response.status_code, 200)
        record.refresh_from_db()
        self.assertEqual(record.status, 'completed')
        self.assertEqual(Payslip.objects.filter(payroll_run=self.run).count(), 1)

    @override_settings(IDEMPOTENCY_STALE_SECONDS=60)
    def test_live_processing_key_is_not_stolen(self):
        path = f'/api/payroll/runs/{self.run.id}/process/'
        self._processing_record('process-live', timezone.now())

        response = self.client.post(path, {}, format='json', HTTP_IDEMPOTENCY_KEY='process-live')

        self.assertEqual(response.status_code, 409)
        self.assertIn('already being processed', response.data['detail'])
        self.assertEqual(Payslip.objects.filter(payroll_run=self.run).count(), 0)

    def test_on_leave_employees_stay_in_payroll(self):
        Employee.objects.filter(company=self.company).update(employment_status='on_leave')
        path = f'/api/payroll/runs/{self.run.id}/process/'

        response = self.client.post(path, {}, format='json')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Payslip.objects.filter(payroll_run=self.run).count(), 1)
