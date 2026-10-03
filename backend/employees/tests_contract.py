from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from employees.models import Employee, Contract, Department
from accounts.models import Company
from django.utils import timezone
from datetime import timedelta

User = get_user_model()

class ContractEndTest(TestCase):
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
        self.user = User.objects.create_user(
            username="hr_user", 
            password="password123", 
            company=self.company, 
            role='hr'
        )
        self.client.force_authenticate(user=self.user)
        
        # Create Employee
        self.employee = Employee.objects.create(
            company=self.company,
            first_name="John",
            last_name="Doe",
            email="john@test.com",
            employee_code="EMP001"
        )
        
        # Create Contract
        self.contract = Contract.objects.create(
            employee=self.employee,
            contract_type='full_time',
            start_date=timezone.localdate() - timedelta(days=30)
        )

    def test_contract_end_success(self):
        # Test ending a contract with a specific date
        end_date = timezone.localdate() + timedelta(days=10)
        url = f'/api/employees/contracts/{self.contract.id}/end/'
        data = {'end_date': end_date.strftime('%Y-%m-%d')}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, 200)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.end_date, end_date)

    def test_contract_end_invalid_date(self):
        # Test ending a contract with a date before start date
        start_date = self.contract.start_date
        end_date = start_date - timedelta(days=1)
        url = f'/api/employees/contracts/{self.contract.id}/end/'
        data = {'end_date': end_date.strftime('%Y-%m-%d')}
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, 400)
