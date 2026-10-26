from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Company, User
from accounts.platform_models import Subscription
from employees.models import Employee
from payroll.models import Payslip, PayrollConfig, PayrollRun, StatutoryContribution, TaxBracket
from payroll.services import calculate_payslip, calculate_progressive_tax


class PayrollEngineTests(TestCase):
    def test_progressive_tax_applies_each_bracket_slice(self):
        config = PayrollConfig.objects.create(company=Company.objects.create(name='Tax Co', email='tax@example.com'))
        TaxBracket.objects.create(payroll_config=config, min_amount=0, max_amount=1000, rate=0)
        TaxBracket.objects.create(payroll_config=config, min_amount=1000, max_amount=None, rate=10)
        self.assertEqual(calculate_progressive_tax(Decimal('2000'), config.tax_brackets), Decimal('100.00'))

    def test_calculation_includes_allowance_tax_and_employee_contribution(self):
        company = Company.objects.create(name='Payroll Co', email='payroll@example.com')
        config = PayrollConfig.objects.create(company=company, currency='GNF')
        TaxBracket.objects.create(payroll_config=config, min_amount=0, max_amount=None, rate=10)
        StatutoryContribution.objects.create(
            payroll_config=config, name='Social Security', employee_rate=5, employer_rate=5,
        )
        employee = Employee.objects.create(
            company=company, employee_code='E1', first_name='Awa', last_name='Diallo',
            email='awa@example.com', base_salary=1000,
        )
        result = calculate_payslip(employee, config)
        self.assertEqual(result['gross_salary'], Decimal('1000'))
        self.assertEqual(result['tax_amount'], Decimal('100.00'))
        self.assertEqual(result['total_contributions'], Decimal('50.00'))
        self.assertEqual(result['net_salary'], Decimal('850.00'))

    def test_payslip_cannot_mix_employee_and_payroll_run_companies(self):
        first = Company.objects.create(name='First Co', email='first@example.com')
        second = Company.objects.create(name='Second Co', email='second@example.com')
        employee = Employee.objects.create(
            company=second, employee_code='E2', first_name='Binta', last_name='Diallo',
            email='binta@example.com', base_salary=1000,
        )
        run = PayrollRun.objects.create(
            company=first, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        )

        with self.assertRaises(ValidationError):
            Payslip.objects.create(
                payroll_run=run, employee=employee, base_salary=1000,
                gross_salary=1000, net_salary=900,
            )

    def test_payslip_cannot_have_negative_net_salary(self):
        company = Company.objects.create(name='Net Co', email='net@example.com')
        employee = Employee.objects.create(
            company=company, employee_code='E3', first_name='Kofi', last_name='Mensah',
            email='kofi@example.com', base_salary=1000,
        )
        run = PayrollRun.objects.create(
            company=company, period_start=date(2026, 2, 1), period_end=date(2026, 2, 28),
        )

        with self.assertRaises(ValidationError):
            Payslip.objects.create(
                payroll_run=run, employee=employee, base_salary=1000,
                gross_salary=1000, net_salary=-1,
            )


class PayrollAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name='API Co', email='api-company@example.com', is_active=True)
        Subscription.objects.create(company=self.company, status='trial')
        self.user = User.objects.create_user(
            username='api-owner', email='api-owner@example.com', password='StrongPassword123!',
            company=self.company, role='owner',
        )
        self.client.force_authenticate(self.user)

    def _employee_with_user(self, username, code):
        user = User.objects.create_user(
            username=username, email=f'{username}@example.com',
            password='StrongPassword123!', company=self.company, role='employee',
        )
        employee = Employee.objects.create(
            company=self.company, user=user, employee_code=code,
            first_name=username, last_name='Employee', email=f'{code}@example.com',
        )
        return user, employee

    def _payslip(self, employee, period_start, period_end):
        run = PayrollRun.objects.create(
            company=employee.company, period_start=period_start, period_end=period_end,
        )
        return Payslip.objects.create(
            payroll_run=run, employee=employee,
            base_salary=Decimal('1000.00'), gross_salary=Decimal('1000.00'),
            net_salary=Decimal('900.00'),
        )

    def _stepped_up_session(self):
        """Create a SecuritySession already stamped as freshly MFA-verified."""
        from accounts.secrets import encrypt_secret
        from django.utils import timezone
        from datetime import timedelta
        from security.models import MFADevice, SecuritySession
        from security.utils import hash_value, totp_secret

        MFADevice.objects.create(
            user=self.user, secret_encrypted=encrypt_secret(totp_secret()), enabled=True,
        )
        raw = 'payroll-test-session'
        SecuritySession.objects.create(
            user=self.user, company=self.company, secret_hash=hash_value(raw),
            expires_at=timezone.now() + timedelta(hours=1),
            mfa_verified=True, mfa_verified_at=timezone.now(),
        )
        return raw

    def test_rejects_invalid_payroll_period(self):
        response = self.client.post('/api/payroll/runs/', {
            'period_start': '2026-09-30', 'period_end': '2026-09-01',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_rejects_duplicate_payroll_period(self):
        payload = {'period_start': '2026-09-01', 'period_end': '2026-09-30'}
        self.assertEqual(self.client.post('/api/payroll/runs/', payload, format='json').status_code, 201)
        self.assertEqual(self.client.post('/api/payroll/runs/', payload, format='json').status_code, 400)

    def test_database_enforces_unique_payroll_period_per_company(self):
        period = {'period_start': date(2026, 11, 1), 'period_end': date(2026, 11, 30)}
        PayrollRun.objects.create(company=self.company, **period)
        with self.assertRaises(IntegrityError):
            PayrollRun.objects.create(company=self.company, **period)

    def test_process_and_download_payslip_pdf(self):
        config = PayrollConfig.objects.create(company=self.company, currency='GNF')
        TaxBracket.objects.create(payroll_config=config, min_amount=0, max_amount=None, rate=0)
        Employee.objects.create(
            company=self.company, employee_code='E1', first_name='Awa', last_name='Diallo',
            email='awa-api@example.com', base_salary=1000, hire_date=date.today(),
        )
        run = PayrollRun.objects.create(company=self.company, period_start=date(2026, 9, 1), period_end=date(2026, 9, 30))
        process = self.client.post(f'/api/payroll/runs/{run.id}/process/', {}, format='json')
        self.assertEqual(process.status_code, 200)
        payslip_id = process.data['payslips'][0]['id']
        pdf = self.client.get(f'/api/payroll/payslips/{payslip_id}/?download=pdf')
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertTrue(pdf.content.startswith(b'%PDF'))

    def test_approve_pay_and_export_payroll(self):
        config = PayrollConfig.objects.create(company=self.company, currency='GNF')
        TaxBracket.objects.create(payroll_config=config, min_amount=0, max_amount=None, rate=0)
        Employee.objects.create(
            company=self.company, employee_code='E2', first_name='Moussa', last_name='Camara',
            email='moussa@example.com', base_salary=2000,
        )
        # Approving and paying a run requires a step-up MFA challenge on an
        # interactive session, so this test drives the real cookie session
        # rather than force_authenticate(). See security.step_up.
        self.client = APIClient()
        self.client.cookies['hrcloudpay_session'] = self._stepped_up_session()
        run = PayrollRun.objects.create(company=self.company, period_start=date(2026, 10, 1), period_end=date(2026, 10, 31))
        self.assertEqual(self.client.post(f'/api/payroll/runs/{run.id}/process/', {}, format='json').status_code, 200)
        approved = self.client.post(f'/api/payroll/runs/{run.id}/approve/', {}, format='json')
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.data['status'], 'approved')
        paid = self.client.post(f'/api/payroll/runs/{run.id}/pay/', {'payment_method': 'bank_transfer', 'payment_reference': 'BANK-001'}, format='json')
        self.assertEqual(paid.status_code, 200)
        self.assertEqual(paid.data['status'], 'paid')
        self.assertEqual(self.client.get('/api/payroll/summary/').data['net'], '2000.00')
        export = self.client.get('/api/payroll/export/')
        self.assertEqual(export.status_code, 200)
        self.assertIn(b'BANK-001', export.content)

    def test_employee_can_only_list_and_retrieve_their_own_payslips(self):
        employee_user, employee = self._employee_with_user('self-service', 'E-SELF')
        _, coworker = self._employee_with_user('coworker', 'E-COWORKER')
        own_slip = self._payslip(employee, date(2026, 11, 1), date(2026, 11, 30))
        coworker_slip = self._payslip(coworker, date(2026, 12, 1), date(2026, 12, 31))
        self.client.force_authenticate(employee_user)

        response = self.client.get('/api/payroll/payslips/')

        self.assertEqual(response.status_code, 200)
        items = response.data.get('results', response.data)
        self.assertEqual([item['id'] for item in items], [own_slip.id])
        self.assertEqual(
            self.client.get(f'/api/payroll/payslips/{coworker_slip.id}/').status_code,
            404,
        )

    def test_employee_without_a_linked_profile_is_denied_payslips(self):
        unlinked = User.objects.create_user(
            username='unlinked-employee', email='unlinked@example.com',
            password='StrongPassword123!', company=self.company, role='employee',
        )
        self.client.force_authenticate(unlinked)

        response = self.client.get('/api/payroll/payslips/')

        self.assertEqual(response.status_code, 403)

    def test_hr_and_department_manager_cannot_read_company_payslips(self):
        for role in ('hr', 'department_manager'):
            with self.subTest(role=role):
                user = User.objects.create_user(
                    username=f'{role}-viewer', email=f'{role}@example.com',
                    password='StrongPassword123!', company=self.company, role=role,
                )
                self.client.force_authenticate(user)
                response = self.client.get('/api/payroll/payslips/')
                self.assertEqual(response.status_code, 403)

    def test_finance_can_read_company_payslips(self):
        _, employee = self._employee_with_user('payroll-employee', 'E-PAYROLL')
        self._payslip(employee, date(2026, 11, 1), date(2026, 11, 30))
        finance = User.objects.create_user(
            username='finance-viewer', email='finance@example.com',
            password='StrongPassword123!', company=self.company, role='finance',
        )
        self.client.force_authenticate(finance)

        response = self.client.get('/api/payroll/payslips/')

        self.assertEqual(response.status_code, 200)
        items = response.data.get('results', response.data)
        self.assertEqual(len(items), 1)
