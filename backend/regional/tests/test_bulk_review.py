from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Company, User
from accounts.platform_models import Subscription
from regional.models import StatutoryFiling, StatutoryFilingRule


class BulkReviewTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Bulk Co', email='bulk@example.com', is_active=True)
        Subscription.objects.create(company=self.company, status='trial')
        self.user = User.objects.create_user(
            username='bulk-owner', email='bulk-owner@example.com', password='StrongPassword123!',
            company=self.company, role='owner',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.rule = StatutoryFilingRule.objects.create(
            country_code='NG', code='paye', name='PAYE', authority='Tax',
            frequency='monthly', due_day=10, effective_from=date(2026, 1, 1),
        )
        self.f1 = StatutoryFiling.objects.create(
            company=self.company, rule=self.rule,
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
            due_date=date.today() + timedelta(days=10), amount=Decimal('100.00'),
        )
        self.f2 = StatutoryFiling.objects.create(
            company=self.company, rule=self.rule,
            period_start=date(2026, 2, 1), period_end=date(2026, 2, 28),
            due_date=date.today() + timedelta(days=10), amount=Decimal('100.00'),
        )

    def test_bulk_review_transitions_open_filings(self):
        res = self.client.post('/api/regional/filings/bulk-review/', {'ids': [self.f1.id, self.f2.id, 999999]}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['reviewed'], 2)
        self.assertEqual(len(res.data['skipped']), 1)
        self.f1.refresh_from_db()
        self.assertEqual(self.f1.status, 'reviewed')
        self.assertIsNotNone(self.f1.reviewed_at)

    def test_bulk_review_rejects_empty(self):
        res = self.client.post('/api/regional/filings/bulk-review/', {'ids': []}, format='json')
        self.assertEqual(res.status_code, 400)
