"""Platform company activation: an emailed link, and saying so honestly.

The screen this covers regenerates an activation token and mails it. It used to
report "generated and emailed" whether or not anything was sent, and returned the
activation URL alongside the claim - so an operator whose mail server was
completely broken saw the same green confirmation as one whose mail worked, and
had a working link in hand to activate the company by hand. Nothing in the
interface distinguished the two states, which is how a broken SMTP configuration
survived a working admin console.
"""
from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import AuditLog, Company, User
from accounts.platform_models import EmailConfig
from django.test import TestCase

RESEND = '/api/auth/platform/companies/{}/resend-activation/'
SMTP_PASSWORD = 'smtp-secret-value'


class ResendActivationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Northwind Logistics', email='owner@northwind.example',
            is_active=False, plan='starter',
        )
        self.root = User.objects.create_superuser(
            username='root', email='root@example.com',
            password='Str0ngPass-2026!', company=None,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.root)

    def post(self):
        return self.client.post(
            RESEND.format(self.company.id), {}, format='json',
        )

    def test_a_successful_send_says_it_was_emailed(self):
        with patch('hrcloudpay.email_backend.send_mail', return_value=1):
            response = self.post()

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['emailed'])
        self.assertIn('emailed', response.data['message'])

    def test_a_failed_send_is_reported_as_a_failure(self):
        """The whole point. A 200 here means the operator believes mail works."""
        with patch('hrcloudpay.email_backend.send_mail',
                   side_effect=OSError('Connection refused')):
            response = self.post()

        self.assertEqual(response.status_code, 503, response.data)
        self.assertFalse(response.data['emailed'])
        self.assertIn('NOT delivered', response.data['detail'])

    def test_a_failed_send_still_returns_the_link(self):
        """A mail outage must not block a platform admin from onboarding a
        tenant - but the link has to be labelled as not sent, or it becomes the
        quiet workaround that hid the outage."""
        with patch('hrcloudpay.email_backend.send_mail',
                   side_effect=OSError('Connection refused')):
            response = self.post()

        self.assertIn('activation_url', response.data)
        self.assertIn(str(self.company.id), response.data['activation_url'])

    def test_the_token_is_regenerated_even_when_the_mail_fails(self):
        """Otherwise a failed resend would report the old, already-used link."""
        original = self.company.activation_token
        with patch('hrcloudpay.email_backend.send_mail',
                   side_effect=OSError('Connection refused')):
            self.post()

        self.company.refresh_from_db()
        self.assertNotEqual(self.company.activation_token, original)

    def test_an_active_company_is_refused(self):
        self.company.is_active = True
        self.company.save(update_fields=['is_active'])

        self.assertEqual(self.post().status_code, 400)

    def test_a_tenant_admin_cannot_resend(self):
        worker = User.objects.create_user(
            username='owner', email='owner@northwind.example',
            password='Str0ngPass-2026!', company=self.company, role='owner',
        )
        self.client.force_authenticate(worker)

        self.assertEqual(self.post().status_code, 403)

    def test_the_attempt_is_audited_either_way(self):
        """A failed send is the one worth having in the trail."""
        with patch('hrcloudpay.email_backend.send_mail',
                   side_effect=OSError('Connection refused')):
            self.post()

        entry = AuditLog.objects.filter(target_type='company').first()
        self.assertIsNotNone(entry)


class RegistrationSendsTheLinkTests(TestCase):
    """The public path, which cannot report a failure to an anonymous caller.

    A signup must not 500 because the mail server is down - the company exists
    and the user is real - so this one logs rather than surfacing. What it must
    not do is quietly skip the send, which is the bug the resend screen was
    hiding.
    """

    REGISTER = '/api/auth/register/'

    def test_registration_attempts_the_send(self):
        with patch('hrcloudpay.email_backend.send_mail',
                   return_value=1) as send:
            response = self.client.post(self.REGISTER, {
                'company_name': 'Northwind Logistics',
                'country': 'NG',
                'company_email': 'accounts@northwind.example',
                'username': 'northwind-owner',
                'email': 'owner@northwind.example',
                'password': 'Str0ngPass-2026',
            }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        send.assert_called_once()
        recipients = send.call_args.kwargs['recipient_list']
        self.assertEqual(recipients, ['accounts@northwind.example'])

    def test_registration_still_succeeds_when_the_send_fails(self):
        with patch('hrcloudpay.email_backend.send_mail',
                   side_effect=OSError('Connection refused')):
            response = self.client.post(self.REGISTER, {
                'company_name': 'Northwind Logistics',
                'country': 'NG',
                'company_email': 'accounts@northwind.example',
                'username': 'northwind-owner',
                'email': 'owner@northwind.example',
                'password': 'Str0ngPass-2026',
            }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(Company.objects.filter(
            email='accounts@northwind.example').exists())

    def test_the_failure_is_logged_with_the_recipient(self):
        """This is the only trace a failed signup send leaves, so it has to name
        the address - otherwise the log says mail is broken and not to whom."""
        with patch('hrcloudpay.email_backend.send_mail',
                   side_effect=OSError('Connection refused')):
            with self.assertLogs('hrcloudpay.email_backend', level='ERROR') as log:
                self.client.post(self.REGISTER, {
                    'company_name': 'Northwind Logistics',
                    'country': 'NG',
                    'company_email': 'accounts@northwind.example',
                    'username': 'northwind-owner',
                    'email': 'owner@northwind.example',
                    'password': 'Str0ngPass-2026',
                }, format='json')

        self.assertIn('accounts@northwind.example', ''.join(log.output))