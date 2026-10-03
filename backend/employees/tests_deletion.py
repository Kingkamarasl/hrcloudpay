
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from employees.models import Employee, Contract
from accounts.models import Company
from accounts.platform_models import AuditLog
from django.utils import timezone
from datetime import timedelta

User = get_user_model()

class EmployeeDeletionTest(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Create Company
        self.company = Company.objects.create(
            name="Test Company",
            email="test@company.com",
            is_active=True
        )

        # Create Subscription to satisfy IsCompanyActive
        from accounts.platform_models import Subscription
        Subscription.objects.create(
            company=self.company,
            status='active',
            billing_cycle='monthly',
            provider='manual'
        )

        # Create HR User
        self.hr_user = User.objects.create_user(
            username="hr_user",
            password="password123",
            company=self.company,
            role='hr'
        )
        self.client.force_authenticate(user=self.hr_user)

        # Create Employee User
        self.emp_user = User.objects.create_user(
            username="emp_user",
            password="password123",
            company=self.company,
            role='employee'
        )

        # Create Employee
        self.employee = Employee.objects.create(
            company=self.company,
            user=self.emp_user,
            first_name="John",
            last_name="Doe",
            email="john@test.com",
            employee_code="EMP001"
        )

        # Create Contract for the employee
        self.contract = Contract.objects.create(
            employee=self.employee,
            contract_type='full_time',
            start_date=timezone.localdate() - timedelta(days=30)
        )

    def test_employee_deletion_via_api(self):
        """Test that deleting an employee via API works as expected."""
        url = f'/api/employees/employees/{self.employee.id}/'
        
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, 204)
        
        # 1. Verify employee is gone
        self.assertFalse(Employee.objects.filter(id=self.employee.id).exists())
        
        # 2. Verify contracts are cascaded
        self.assertFalse(Contract.objects.filter(employee_id=self.employee.id).exists())
        
        # 3. Verify user is deactivated
        self.emp_user.refresh_from_db()
        self.assertFalse(self.emp_user.is_active)
        
        # 4. Verify audit log
        audit_exists = AuditLog.objects.filter(
            company=self.company, 
            target_type='employee', 
            target_id=self.employee.id, 
            action='delete'
        ).exists()
        self.assertTrue(audit_exists, "Audit log entry should exist for employee deletion")

    def test_employee_deletion_unauthorized(self):
        """Test that an employee cannot delete themselves."""
        self.client.force_authenticate(user=self.emp_user)
        url = f'/api/employees/employees/{self.employee.id}/'
        
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Employee.objects.filter(id=self.employee.id).exists())
