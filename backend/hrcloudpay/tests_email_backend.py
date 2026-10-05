"""`send_mail_logging_failure`: a send that fails must still leave a trace.

Django's own ``fail_silently=True`` returns 0 and raises nothing. A refused port,
an unroutable host or a rejected sender then produce no exception and no log line
at all - the message is simply gone, while the caller reports success to the
person waiting for it.

That is not theoretical. A deployment naming Django's stock SMTP backend without
ever configuring ``EMAIL_HOST`` reached ``localhost:25``, so every activation mail
failed on every signup. Registration still returned 201 and told the user to check
their email. The failure was invisible for an hour of debugging, and the platform's
own test-send screen passed throughout because it bypassed the broken path.

The helper keeps the "do not raise" behaviour - a signup must not 500 because a
mail server is down - and adds the log line that makes the cause recoverable from
the server instead of from a customer.
"""

from django.core import mail
from django.core.mail.backends.base import BaseEmailBackend
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from hrcloudpay.email_backend import send_mail_logging_failure

REGISTER_URL = '/api/auth/register/'
LOGGER = 'hrcloudpay.email_backend'

VALID_REGISTRATION = {
    'company_name': 'Northwind Logistics',
    'country': 'NG',
    'company_email': 'accounts@northwind.example',
    'username': 'northwind-owner',
    'email': 'owner@northwind.example',
    'password': 'Str0ngPass-2026',
}


class _RefusingBackend(BaseEmailBackend):
    """An SMTP server that is not there - the production failure, reproduced."""

    def send_messages(self, email_messages):
        raise ConnectionRefusedError(111, 'Connection refused')


class SendMailLoggingFailureTests(TestCase):
    def test_a_successful_send_returns_the_count(self):
        sent = send_mail_logging_failure(
            'Subject', 'Body', 'from@example.com', ['to@example.com'],
        )

        self.assertEqual(sent, 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_a_failure_returns_zero_rather_than_raising(self):
        """The caller must not have to handle an exception to send mail."""
        with override_settings(
                EMAIL_BACKEND='hrcloudpay.tests_email_backend._RefusingBackend'):
            with self.assertLogs(LOGGER, level='ERROR'):
                sent = send_mail_logging_failure(
                    'Subject', 'Body', 'from@example.com', ['to@example.com'],
                )

        self.assertEqual(sent, 0)

    def test_the_failure_is_logged_with_the_recipient_and_the_kind_of_mail(self):
        """A log line naming neither recipient nor purpose is close to useless."""
        with override_settings(
                EMAIL_BACKEND='hrcloudpay.tests_email_backend._RefusingBackend'):
            with self.assertLogs(LOGGER, level='ERROR') as captured:
                send_mail_logging_failure(
                    'Subject', 'Body', 'from@example.com',
                    ['payroll@example.com'], what='company activation',
                )

        record = captured.output[0]
        self.assertIn('company activation', record)
        self.assertIn('payroll@example.com', record)
        # The traceback is the reason for logging rather than swallowing: it names
        # the host that refused, which is the thing that was unknown for an hour.
        self.assertIn('ConnectionRefusedError', record)

    def test_the_password_never_appears_in_the_log(self):
        """The stored secret must not reach a log line."""
        with override_settings(
                EMAIL_BACKEND='hrcloudpay.tests_email_backend._RefusingBackend'):
            with self.assertLogs(LOGGER, level='ERROR') as captured:
                send_mail_logging_failure(
                    'Subject', 'Body', 'from@example.com', ['to@example.com'],
                    smtp_password='hunter2-not-a-real-secret',
                )

        self.assertNotIn('hunter2-not-a-real-secret', ''.join(captured.output))


class RegistrationSurvivesBrokenMailTests(TestCase):
    """A signup must not fail because the mail server is down.

    The company is created and the caller gets 201 - the account exists and the
    user can retry. But the reason the activation mail vanished is written to the
    log, which is the entire point of the exercise.
    """

    def setUp(self):
        self.client = APIClient()

    def test_registration_still_returns_201_when_mail_cannot_be_sent(self):
        with override_settings(
                EMAIL_BACKEND='hrcloudpay.tests_email_backend._RefusingBackend'):
            with self.assertLogs(LOGGER, level='ERROR'):
                response = self.client.post(
                    REGISTER_URL, VALID_REGISTRATION, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        # The message promises an email that was never sent. That promise is the
        # bug this whole change is about, so it is asserted here rather than left
        # implicit: if the wording ever changes, this test says so.
        self.assertIn('Check your email', response.data['message'])

    def test_the_company_is_created_even_though_the_mail_was_not(self):
        from accounts.models import Company

        with override_settings(
                EMAIL_BACKEND='hrcloudpay.tests_email_backend._RefusingBackend'):
            with self.assertLogs(LOGGER, level='ERROR'):
                self.client.post(REGISTER_URL, VALID_REGISTRATION, format='json')

        company = Company.objects.filter(email='accounts@northwind.example').first()
        self.assertIsNotNone(company, 'the company must not be rolled back')
        # Still inactive: nothing was delivered, so nothing may claim otherwise.
        self.assertFalse(company.is_active)

    def test_the_refusal_is_named_in_the_log(self):
        with override_settings(
                EMAIL_BACKEND='hrcloudpay.tests_email_backend._RefusingBackend'):
            with self.assertLogs(LOGGER, level='ERROR') as captured:
                self.client.post(REGISTER_URL, VALID_REGISTRATION, format='json')

        record = ''.join(captured.output)
        self.assertIn('company activation', record)
        self.assertIn('accounts@northwind.example', record)