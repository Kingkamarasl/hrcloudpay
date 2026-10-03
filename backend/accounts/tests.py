from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Company, User
from accounts.platform_models import Subscription
from employees.models import Employee


def active_company(name, email, plan='starter'):
    """Create an active Company with an active Subscription.

    IsCompanyActive rejects a company with no subscription row
    (accounts/billing.subscription_state -> 'missing' -> not allowed), so tests
    that exercise company-scoped endpoints need one or every request 403s for a
    reason unrelated to what they are asserting.

    `plan` defaults to 'starter' (3 active user accounts). Pass a larger plan
    when a test needs to create more staff accounts than that.
    """
    company = Company.objects.create(name=name, email=email, is_active=True, plan=plan)
    Subscription.objects.create(
        company=company, status='active',
        started_at=timezone.now(), renews_at=timezone.now() + timedelta(days=30),
    )
    return company


class StaffAccountCreationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        # 'professional' gives room for the owner plus three staff accounts, so
        # these tests exercise the role rules rather than the starter user cap.
        self.company = active_company('Acme', 'acme@example.com', plan='professional')
        self.owner = User.objects.create_user(
            username='owner1', email='owner1@example.com', password='StrongPassword123!',
            company=self.company, role='owner',
        )
        self.client.force_authenticate(self.owner)

    def test_owner_can_create_hr_and_finance_accounts(self):
        for role in ('hr', 'finance', 'admin'):
            response = self.client.post('/api/auth/users/', {
                'username': f'{role}-user', 'email': f'{role}@example.com',
                'password': 'StrongPassword123!', 'role': role,
            }, format='json')
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(response.data['role'], role)

    def test_department_manager_requires_managed_department(self):
        response = self.client.post('/api/auth/users/', {
            'username': 'dept-mgr', 'email': 'dept@example.com',
            'password': 'StrongPassword123!', 'role': 'department_manager',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_employee_role_requires_and_links_employee_record(self):
        employee = Employee.objects.create(
            company=self.company, employee_code='E1', first_name='Awa', last_name='Diallo',
            email='awa@example.com', base_salary=1000, hire_date=date.today(), department='Sales',
        )
        response = self.client.post('/api/auth/users/', {
            'username': 'awa-login', 'email': 'awa-login@example.com',
            'password': 'StrongPassword123!', 'role': 'employee', 'employee_id': employee.id,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        employee.refresh_from_db()
        self.assertIsNotNone(employee.user)
        self.assertEqual(employee.user.username, 'awa-login')

    def test_non_admin_cannot_create_staff_accounts(self):
        hr_user = User.objects.create_user(
            username='hr1', email='hr1@example.com', password='StrongPassword123!',
            company=self.company, role='hr',
        )
        client = APIClient()
        client.force_authenticate(hr_user)
        response = client.post('/api/auth/users/', {
            'username': 'sneaky', 'email': 'sneaky@example.com',
            'password': 'StrongPassword123!', 'role': 'admin',
        }, format='json')
        self.assertEqual(response.status_code, 403)


class DepartmentScopingTests(TestCase):
    def setUp(self):
        self.company = active_company('Acme', 'acme2@example.com')
        self.sales_emp = Employee.objects.create(
            company=self.company, employee_code='S1', first_name='Sales', last_name='One',
            email='sales1@example.com', base_salary=1000, department='Sales',
        )
        self.eng_emp = Employee.objects.create(
            company=self.company, employee_code='E1', first_name='Eng', last_name='One',
            email='eng1@example.com', base_salary=1000, department='Engineering',
        )
        self.manager = User.objects.create_user(
            username='sales-mgr', email='salesmgr@example.com', password='StrongPassword123!',
            company=self.company, role='department_manager', managed_department='Sales',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def test_department_manager_only_sees_own_department_employees(self):
        response = self.client.get('/api/employees/employees/')
        names = [e['employee_code'] for e in response.data.get('results', response.data)]
        self.assertIn('S1', names)
        self.assertNotIn('E1', names)

    def test_department_manager_cannot_mark_attendance_outside_department(self):
        response = self.client.post('/api/attendance/records/', {
            'employee': self.eng_emp.id, 'date': '2026-09-01', 'status': 'present',
        }, format='json')
        self.assertEqual(response.status_code, 403)

    def test_department_manager_can_mark_attendance_within_department(self):
        response = self.client.post('/api/attendance/records/', {
            'employee': self.sales_emp.id, 'date': '2026-09-01', 'status': 'present',
        }, format='json')
        self.assertEqual(response.status_code, 201)


class PayrollAccessRestrictedFromHRTests(TestCase):
    def setUp(self):
        self.company = active_company('Acme', 'acme3@example.com')
        self.hr_user = User.objects.create_user(
            username='hr-only', email='hronly@example.com', password='StrongPassword123!',
            company=self.company, role='hr',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.hr_user)

    def test_hr_cannot_access_payroll_summary(self):
        response = self.client.get('/api/payroll/summary/')
        self.assertEqual(response.status_code, 403)

    def test_hr_cannot_access_payroll_runs(self):
        response = self.client.get('/api/payroll/runs/')
        self.assertEqual(response.status_code, 403)

class SensitiveAuditTests(TestCase):
    def setUp(self):
        self.company = active_company('Audit Co', 'audit@example.com')
        self.owner = User.objects.create_user(username='audit-owner', email='audit-owner@example.com', password='StrongPassword123!', company=self.company, role='owner')
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.employee = Employee.objects.create(company=self.company, employee_code='AUD1', first_name='Audit', last_name='Employee', email='audit-employee@example.com', base_salary=1000, department='Finance')

    def test_salary_change_is_audited(self):
        response = self.client.patch(f'/api/employees/employees/{self.employee.id}/', {'base_salary': '1500.00'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        from accounts.platform_models import AuditLog
        log = AuditLog.objects.filter(action='salary_change', target_id=str(self.employee.id)).latest('created_at')
        self.assertEqual(log.metadata['changes']['base_salary']['before'], '1000.00')
        self.assertEqual(log.metadata['changes']['base_salary']['after'], '1500.00')

    def test_termination_is_audited(self):
        response = self.client.patch(f'/api/employees/employees/{self.employee.id}/', {'employment_status': 'terminated'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        from accounts.platform_models import AuditLog
        self.assertTrue(AuditLog.objects.filter(action='termination', target_id=str(self.employee.id)).exists())

    def test_permission_change_is_audited(self):
        staff = User.objects.create_user(username='staff-audit', email='staff-audit@example.com', password='StrongPassword123!', company=self.company, role='hr')
        response = self.client.patch(f'/api/auth/users/{staff.id}/', {'role': 'finance'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        from accounts.platform_models import AuditLog
        self.assertTrue(AuditLog.objects.filter(action='permission_change', target_id=str(staff.id)).exists())

    def test_login_success_and_failure_are_audited(self):
        self.client.force_authenticate(user=None)
        response = self.client.post('/api/auth/login/', {'username': 'audit-owner', 'password': 'wrong'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertTrue(__import__('accounts.platform_models', fromlist=['AuditLog']).AuditLog.objects.filter(action='login_failed').exists())
        response = self.client.post('/api/auth/login/', {'username': 'audit-owner', 'password': 'StrongPassword123!'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(__import__('accounts.platform_models', fromlist=['AuditLog']).AuditLog.objects.filter(action='login', actor=self.owner).exists())
