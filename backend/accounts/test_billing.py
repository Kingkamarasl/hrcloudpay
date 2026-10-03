from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from .models import Company, User
from .platform_models import Subscription
from .billing import subscription_state

class BillingStateTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Billing Co', email='billing@example.com', is_active=True)
        User.objects.create_user(username='owner', password='Testpass123!', company=self.company, role='owner')

    def test_trial_is_allowed(self):
        sub = Subscription.objects.create(company=self.company, status='trial', trial_ends_at=timezone.now()+timedelta(days=3))
        self.assertTrue(subscription_state(self.company)['allowed'])

    def test_expired_trial_is_blocked(self):
        Subscription.objects.create(company=self.company, status='trial', trial_ends_at=timezone.now()-timedelta(days=1))
        self.assertFalse(subscription_state(self.company)['allowed'])

    def test_grace_period_allows_access(self):
        Subscription.objects.create(company=self.company, status='past_due', grace_ends_at=timezone.now()+timedelta(days=2))
        self.assertTrue(subscription_state(self.company)['allowed'])
