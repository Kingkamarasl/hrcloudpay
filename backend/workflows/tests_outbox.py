from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Company, User
from .models import HRNotification, NotificationDelivery, NotificationPreference
from .services import notify, process_notification_outbox


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class NotificationOutboxTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Outbox Co', email='outbox@example.com', is_active=True)
        self.user = User.objects.create_user(username='hr-outbox', email='hr@outbox.example', password='StrongPassword123!', company=self.company, role='hr')

    def test_email_delivery_requires_user_preference(self):
        notify(self.company, 'Contract renewal', 'Review a contract.', notification_type='contract')
        self.assertEqual(NotificationDelivery.objects.count(), 0)
        NotificationPreference.objects.create(user=self.user, email_enabled=True)
        notify(self.company, 'Another renewal', 'Review another contract.', notification_type='contract')
        self.assertEqual(NotificationDelivery.objects.count(), 1)

    def test_outbox_sends_once_and_is_idempotent(self):
        NotificationPreference.objects.create(user=self.user, email_enabled=True)
        notify(self.company, 'Leave request', 'Review leave.', notification_type='leave', dedupe_key='leave:1')
        notify(self.company, 'Leave request', 'Review leave.', notification_type='leave', dedupe_key='leave:1')
        self.assertEqual(NotificationDelivery.objects.count(), 1)
        result = process_notification_outbox()
        self.assertEqual(result['sent'], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(NotificationDelivery.objects.get().status, 'sent')
        self.assertEqual(process_notification_outbox()['sent'], 0)

    @patch('django.core.mail.EmailMessage.send', side_effect=RuntimeError('SMTP unavailable'))
    def test_failed_delivery_is_scheduled_for_retry(self, _send):
        NotificationPreference.objects.create(user=self.user, email_enabled=True)
        notify(self.company, 'Payroll ready', 'Review payroll.', notification_type='payroll')
        result = process_notification_outbox()
        self.assertEqual(result['failed'], 1)
        delivery = NotificationDelivery.objects.get()
        self.assertEqual(delivery.status, 'failed')
        self.assertEqual(delivery.attempts, 1)
        self.assertGreater(delivery.next_attempt_at, timezone.now())
