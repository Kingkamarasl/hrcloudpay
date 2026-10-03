from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Company, User
from accounts.platform_models import Subscription
from regional.models import StatutoryFiling, StatutoryFilingRule


class StatutoryFilingWorkflowTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Statutory Co', email='statutory@example.com', is_active=True,
        )
        Subscription.objects.create(company=self.company, status='trial')
        self.owner = User.objects.create_user(
            username='statutory-owner', email='owner@statutory.example',
            password='StrongPassword123!', company=self.company, role='owner',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.rule = StatutoryFilingRule.objects.create(
            country_code='NG', code='paye', name='PAYE', authority='Tax Authority',
            filing_type='tax', frequency='monthly', due_day=10,
            effective_from=date(2026, 1, 1),
        )
        self.filing = StatutoryFiling.objects.create(
            company=self.company, rule=self.rule,
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
            due_date=date.today() + timedelta(days=10), amount=Decimal('100.00'),
        )

    def endpoint(self, action):
        return f'/api/regional/filings/{self.filing.id}/{action}/'

    def test_workflow_requires_each_transition_and_closes_the_filing(self):
        response = self.client.post(self.endpoint('approve'), {}, format='json')
        self.assertEqual(response.status_code, 400)

        response = self.client.post(self.endpoint('review'), {'notes': 'Amounts checked'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'reviewed')
        self.assertIsNotNone(response.data['reviewed_at'])

        response = self.client.post(self.endpoint('approve'), {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'approved')

        response = self.client.post(self.endpoint('payment'), {'amount': '100.00'}, format='json')
        self.assertEqual(response.status_code, 400)

        response = self.client.post(self.endpoint('payment'), {
            'amount': '100.00', 'method': 'bank_transfer',
            'transaction_reference': 'PAY-100', 'receipt_reference': 'REC-100',
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.filing.refresh_from_db()
        self.assertEqual(self.filing.status, 'paid')

        response = self.client.post(self.endpoint('submit'), {'submission_reference': 'AUTH-100'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'submitted')

        response = self.client.post(self.endpoint('payment'), {
            'amount': '100.00', 'method': 'bank_transfer', 'transaction_reference': 'CHANGED',
        }, format='json')
        self.assertEqual(response.status_code, 400)

        response = self.client.post(self.endpoint('close'), {'notes': 'Receipt archived'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'closed')
        self.assertIsNotNone(response.data['closed_at'])

    def test_legacy_mark_filed_endpoint_cannot_bypass_workflow(self):
        response = self.client.post(f'/api/regional/filings/{self.filing.id}/file/', {'reference': 'BYPASS'}, format='json')
        self.assertEqual(response.status_code, 410)
        self.filing.refresh_from_db()
        self.assertEqual(self.filing.status, 'open')

    def test_filing_actions_are_tenant_scoped(self):
        other_company = Company.objects.create(
            name='Other Co', email='other@example.com', is_active=True,
        )
        Subscription.objects.create(company=other_company, status='trial')
        other_user = User.objects.create_user(
            username='other-owner', email='owner@other.example',
            password='StrongPassword123!', company=other_company, role='owner',
        )
        other_client = APIClient()
        other_client.force_authenticate(other_user)

        response = other_client.post(self.endpoint('review'), {}, format='json')
        self.assertEqual(response.status_code, 404)
