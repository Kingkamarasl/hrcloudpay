from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Company, User
from accounts.platform_models import Subscription
from employees.models import Employee
from payroll.models import PayrollConfig, PayrollRun, Payslip, TaxBracket


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
