"""Site-wide SMTP configuration, managed by a platform superuser.

Two properties are worth more than the feature itself:

- **The SMTP password never leaves the server.** GET returns `password_set`, a
  boolean. POST leaves the stored secret alone when no password is supplied, so
  a form that does not re-send the field on every save cannot wipe it. The
  audit row records `password_changed` as a boolean, because an audit trail is
  read by more people than the settings screen.
- **Mail does not silently stop.** With no usable configuration the backend
  delegates to the console rather than raising, so a fresh deployment still
  shows the messages it would have sent. The failure mode being avoided is the
  one where a wrong password is discovered when a customer cannot activate
  their account.
"""
from unittest.mock import patch

from django.core import mail
from django.core.mail.backends.base import BaseEmailBackend
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import AuditLog, Company, User
from accounts.platform_models import EmailConfig

CONFIG_URL = '/api/auth/platform/email-config/'
TEST_URL = '/api/auth/platform/email-config/test/'

PASSWORD = 'StrongPassword123!'
SMTP_PASSWORD = 'smtp-secret-value-9182'


class _RefusingBackend(BaseEmailBackend):
    """A backend that cannot deliver, so the screen must report it.

    Stands in for the misconfigured EMAIL_BACKEND that made this whole
    episode invisible: the stored EmailConfig was perfect throughout, and
    every real send still failed.
    """

    def send_messages(self, email_messages):
        raise OSError('SMTP AUTH failed: bad credentials')


class EmailConfigTestBase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Acme', email='acme@example.com', is_active=True, plan='starter',
        )
        self.root = User.objects.create_superuser(
            username='root', email='root@example.com',
            password=PASSWORD, company=None,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.root)

    def save_config(self, **overrides):
        payload = {
            'host': 'smtp.example.com',
            'port': 587,
            'username': 'mailer@example.com',
            'password': SMTP_PASSWORD,
            'use_tls': True,
            'from_email': 'no-reply@hrcloudpay.com',
            'is_active': True,
        }
        payload.update(overrides)
        return self.client.post(CONFIG_URL, payload, format='json')


class PermissionTests(EmailConfigTestBase):
    def test_a_non_superuser_cannot_read_the_configuration(self):
        """Not merely IsAdminUser: this holds a credential."""
        worker = User.objects.create_user(
            username='hr', email='hr@example.com', password=PASSWORD,
            company=self.company, role='hr', is_staff=True,
        )
        self.client.force_authenticate(worker)

        self.assertEqual(self.client.get(CONFIG_URL).status_code, 403)
        self.assertEqual(self.client.post(CONFIG_URL, {'host': 'evil.test'},
                                          format='json').status_code, 403)

    def test_an_ordinary_tenant_admin_cannot_read_it(self):
        owner = User.objects.create_user(
            username='owner', email='owner@example.com', password=PASSWORD,
            company=self.company, role='owner',
        )
        self.client.force_authenticate(owner)

        self.assertEqual(self.client.get(CONFIG_URL).status_code, 403)

    def test_a_superuser_attached_to_a_tenant_can_still_read_it(self):
        """Platform-level secrets are gated on is_superuser, not on company.

        The reverse trap is the common one: a superuser wrongly given a company
        cannot use the platform's own endpoints. Requiring a null company here
        would lock out a correctly-migrated install instead.
        """
        attached = User.objects.create_superuser(
            username='root2', email='root2@example.com',
            password=PASSWORD, company=self.company,
        )
        self.client.force_authenticate(attached)

        self.assertEqual(self.client.get(CONFIG_URL).status_code, 200)

    def test_the_test_send_endpoint_is_gated_the_same_way(self):
        worker = User.objects.create_user(
            username='hr2', email='hr2@example.com', password=PASSWORD,
            company=self.company, role='hr',
        )
        self.client.force_authenticate(worker)

        self.assertEqual(
            self.client.post(TEST_URL, {'to': 'x@example.com'},
                             format='json').status_code, 403)


class SecretHandlingTests(EmailConfigTestBase):
    def test_the_password_is_never_returned(self):
        self.save_config()

        response = self.client.get(CONFIG_URL)

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertNotIn(SMTP_PASSWORD, body)
        self.assertTrue(response.data['password_set'])

    def test_the_password_is_encrypted_at_rest(self):
        self.save_config()

        config = EmailConfig.objects.first()
        self.assertNotEqual(config.encrypted_password, SMTP_PASSWORD)
        self.assertNotIn(SMTP_PASSWORD, config.encrypted_password)
        # And it still round-trips, which is the part that silently rots.
        self.assertEqual(config.get_password(), SMTP_PASSWORD)

    def test_saving_without_a_password_keeps_the_stored_one(self):
        """The form must not wipe the secret by omitting the field."""
        self.save_config()

        response = self.client.post(
            CONFIG_URL, {'host': 'smtp2.example.com'}, format='json')

        self.assertEqual(response.status_code, 200, response.data)
        config = EmailConfig.objects.first()
        self.assertEqual(config.host, 'smtp2.example.com')
        self.assertEqual(config.get_password(), SMTP_PASSWORD)

    def test_a_blank_password_keeps_the_stored_one(self):
        self.save_config()

        self.client.post(CONFIG_URL, {'password': '   '}, format='json')

        self.assertEqual(EmailConfig.objects.first().get_password(),
                         SMTP_PASSWORD)

    def test_a_new_password_replaces_the_old_one(self):
        self.save_config()

        self.client.post(CONFIG_URL, {'password': 'rotated-secret'},
                         format='json')

        self.assertEqual(EmailConfig.objects.first().get_password(),
                         'rotated-secret')

    def test_the_audit_row_records_a_boolean_not_the_secret(self):
        self.save_config()

        row = AuditLog.objects.filter(action='platform_email_config').first()
        self.assertIsNotNone(row, 'changing SMTP settings wrote no audit row')
        self.assertTrue(row.metadata['password_changed'])
        self.assertNotIn(SMTP_PASSWORD, str(row.metadata))
        self.assertIsNone(row.company, 'a platform setting must have no company')


class ValidationTests(EmailConfigTestBase):
    def test_tls_and_ssl_together_are_refused(self):
        """smtplib cannot do both, and starttls() on an SSL socket raises."""
        response = self.save_config(use_tls=True, use_ssl=True)

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('use_ssl', response.data['errors'])
        self.assertEqual(EmailConfig.objects.count(), 0)

    def test_a_non_numeric_port_is_refused(self):
        response = self.save_config(port='not-a-port')

        self.assertEqual(response.status_code, 400)
        self.assertIn('port', response.data['errors'])

    def test_an_out_of_range_port_is_refused(self):
        self.assertEqual(self.save_config(port=70000).status_code, 400)
        self.assertEqual(self.save_config(port=0).status_code, 400)

    def test_an_absurd_timeout_is_refused(self):
        response = self.save_config(timeout_seconds=100000)

        self.assertEqual(response.status_code, 400)
        self.assertIn('timeout_seconds', response.data['errors'])

    def test_a_malformed_from_address_is_refused(self):
        response = self.save_config(from_email='not-an-address')

        self.assertEqual(response.status_code, 400)
        self.assertIn('from_email', response.data['errors'])

    def test_activating_without_a_host_is_refused(self):
        response = self.client.post(
            CONFIG_URL, {'is_active': True}, format='json')

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('host', response.data['errors'])

    def test_a_valid_ssl_configuration_is_accepted(self):
        response = self.save_config(use_tls=False, use_ssl=True, port=465)

        self.assertEqual(response.status_code, 200, response.data)
        config = EmailConfig.objects.first()
        self.assertTrue(config.use_ssl)
        self.assertFalse(config.use_tls)

    def test_nothing_is_saved_when_validation_fails(self):
        self.save_config(port='bad')

        self.assertEqual(EmailConfig.objects.count(), 0)


class ConfigurationStateTests(EmailConfigTestBase):
    def test_a_fresh_install_reports_nothing_configured(self):
        response = self.client.get(CONFIG_URL)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['configured'])
        self.assertFalse(response.data['in_use'])
        self.assertFalse(response.data['password_set'])

    def test_configured_but_inactive_is_distinguishable_from_in_use(self):
        """The distinction the settings screen needs to be honest.

        A saved row with the toggle off looks complete on the form while every
        message still goes to the console. `configured` says a row exists;
        `in_use` says the running app will use it.
        """
        self.save_config(is_active=False)

        data = self.client.get(CONFIG_URL).data
        self.assertTrue(data['configured'])
        self.assertFalse(data['in_use'])

    def test_saving_twice_updates_one_row(self):
        self.save_config()
        self.save_config(host='smtp3.example.com')

        self.assertEqual(EmailConfig.objects.count(), 1)
        self.assertEqual(EmailConfig.objects.first().host,
                         'smtp3.example.com')

    def test_the_editor_is_recorded(self):
        self.save_config()

        self.assertEqual(EmailConfig.objects.first().updated_by, self.root)


class BackendRoutingTests(EmailConfigTestBase):
    """Which backend actually runs, and what it does when unconfigured."""

    def test_with_no_config_the_backend_falls_back_to_the_console(self):
        from hrcloudpay.email_backend import PlatformEmailBackend

        self.assertIsNone(PlatformEmailBackend._load_config())

        # The console backend prints rather than raising, so this is the
        # behaviour a fresh deployment must keep.
        sent = PlatformEmailBackend().send_messages([
            mail.EmailMessage('Subject', 'Body', 'from@example.com',
                              ['to@example.com']),
        ])
        self.assertEqual(sent, 1)

    def test_an_inactive_config_is_not_used(self):
        self.save_config(is_active=False)

        from hrcloudpay.email_backend import PlatformEmailBackend

        self.assertIsNone(PlatformEmailBackend._load_config())

    def test_an_active_config_is_used(self):
        self.save_config()

        from hrcloudpay.email_backend import PlatformEmailBackend

        self.assertIsNotNone(PlatformEmailBackend._load_config())

    def test_an_undecryptable_secret_raises_rather_than_being_swallowed(self):
        """Silently losing mail behind a broken credential is the worst outcome."""
        self.save_config()
        config = EmailConfig.objects.first()
        config.encrypted_password = 'not-a-fernet-token'
        config.save(update_fields=['encrypted_password'])

        from hrcloudpay.email_backend import PlatformEmailBackend

        with self.assertRaises(ValueError):
            PlatformEmailBackend().send_messages([
                mail.EmailMessage('Subject', 'Body', 'from@example.com',
                                  ['to@example.com']),
            ])

    def test_the_backend_is_selectable_and_passes_the_stored_settings(self):
        """Proves the backend is actually wired to the stored configuration.

        Deliberately not written through `send_mail`: Django's test runner
        replaces EMAIL_BACKEND with locmem before any test runs, so `send_mail`
        never reaches this backend and an assertion about it would pass
        vacuously. Selecting it with override_settings is what actually
        exercises the wiring.
        """
        self.save_config(port=2525)

        captured = {}

        def fake_send_messages(self, messages):
            captured['count'] = len(messages)
            return len(messages)

        with override_settings(
                EMAIL_BACKEND='hrcloudpay.email_backend.PlatformEmailBackend'):
            connection = mail.get_connection(fail_silently=False)
            self.assertEqual(connection.__class__.__name__,
                             'PlatformEmailBackend')
            with patch('django.core.mail.backends.smtp.EmailBackend.send_messages',
                       new=fake_send_messages):
                sent = connection.send_messages([
                    mail.EmailMessage('Subject', 'Body',
                                      'no-reply@hrcloudpay.com',
                                      ['to@example.com']),
                ])

        self.assertEqual(sent, 1)
        self.assertEqual(captured['count'], 1)

    def test_the_stored_settings_reach_djangos_smtp_backend(self):
        """The values themselves, not just that some backend ran."""
        self.save_config(port=2525, username='mailer@example.com')

        captured = {}

        def capture_init(self, **kwargs):
            captured.update(kwargs)

        def capture_send(self, messages):
            captured['count'] = len(messages)
            return len(messages)

        with patch('django.core.mail.backends.smtp.EmailBackend.__init__',
                   new=capture_init):
            with patch('django.core.mail.backends.smtp.EmailBackend.send_messages',
                       new=capture_send):
                from hrcloudpay.email_backend import PlatformEmailBackend

                PlatformEmailBackend(fail_silently=False).send_messages([
                    mail.EmailMessage('Subject', 'Body',
                                      'no-reply@hrcloudpay.com',
                                      ['to@example.com']),
                ])

        self.assertEqual(captured.get('host'), 'smtp.example.com')
        self.assertEqual(captured.get('port'), 2525)
        self.assertEqual(captured.get('username'), 'mailer@example.com')
        self.assertEqual(captured.get('password'), SMTP_PASSWORD)
        self.assertTrue(captured.get('use_tls'))
        self.assertFalse(captured.get('use_ssl'))
        self.assertEqual(captured.get('timeout'), 30)

    def test_the_configured_from_address_replaces_the_site_default(self):
        """An admin-chosen sender, without overriding a per-message one."""
        self.save_config(from_email='mail@hrcloudpay.com')

        captured = {}

        def capture_send(self, messages):
            captured['from'] = [m.from_email for m in messages]
            return len(messages)

        with patch('django.core.mail.backends.smtp.EmailBackend.send_messages',
                   new=capture_send):
            from hrcloudpay.email_backend import PlatformEmailBackend

            PlatformEmailBackend().send_messages([
                mail.EmailMessage('S', 'B', None, ['to@example.com']),
            ])

        self.assertEqual(captured.get('from'), ['mail@hrcloudpay.com'])

    def test_a_per_message_sender_is_not_overridden(self):
        self.save_config(from_email='mail@hrcloudpay.com')

        captured = {}

        def capture_send(self, messages):
            captured['from'] = [m.from_email for m in messages]
            return len(messages)

        with patch('django.core.mail.backends.smtp.EmailBackend.send_messages',
                   new=capture_send):
            from hrcloudpay.email_backend import PlatformEmailBackend

            PlatformEmailBackend().send_messages([
                mail.EmailMessage('S', 'B', 'payroll@hrcloudpay.com',
                                  ['to@example.com']),
            ])

        self.assertEqual(captured.get('from'), ['payroll@hrcloudpay.com'])


class TestSendTests(EmailConfigTestBase):
    def test_sending_before_configuration_is_refused_with_advice(self):
        response = self.client.post(TEST_URL, {'to': 'x@example.com'},
                                    format='json')

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('not active', response.data['detail'])

    def test_a_missing_recipient_is_refused(self):
        self.save_config()

        response = self.client.post(TEST_URL, {'to': 'nonsense'},
                                    format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('to', response.data['errors'])

    def test_a_successful_send_is_audited(self):
        self.save_config()

        with override_settings(
                EMAIL_BACKEND='hrcloudpay.email_backend.PlatformEmailBackend'
        ), patch('hrcloudpay.email_backend.PlatformEmailBackend.send_messages',
                 return_value=1):
            response = self.client.post(
                TEST_URL, {'to': 'ops@example.com'}, format='json')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['success'])

        row = AuditLog.objects.filter(action='platform_email_test').first()
        self.assertIsNotNone(row, 'a test send wrote no audit row')
        self.assertTrue(row.metadata['success'])
        self.assertNotIn(SMTP_PASSWORD, str(row.metadata))

    def test_the_screen_exercises_the_backend_activation_mail_uses(self):
        """The property whose absence let a broken deployment pass here.

        This screen used to build PlatformEmailBackend directly, so it
        proved the stored credentials worked and said nothing about whether
        the application's own mail path worked. A deployment where every
        activation send was refused by localhost:25 still showed green here,
        which is precisely how the misconfiguration survived so long.

        The screen now sends through settings.EMAIL_BACKEND, so a broken
        backend fails this screen instead of hiding behind a valid config.
        """
        self.save_config()

        with override_settings(
                EMAIL_BACKEND=(
                    'accounts.tests_platform_email_config._RefusingBackend')
        ):
            response = self.client.post(
                TEST_URL, {'to': 'ops@example.com'}, format='json')

        self.assertEqual(response.status_code, 503, response.data)

    def test_the_screen_sends_from_the_configured_address(self):
        """The sender comes from EmailConfig, not the site-wide default.

        The view passes DEFAULT_FROM_EMAIL and lets the backend substitute the
        configured sender, which is the same substitution activation mail
        relies on. Pinned here so the two cannot drift apart.
        """
        self.save_config(from_email='mail@hrcloudpay.com')

        captured = {}

        def capture(self, messages):
            captured['from'] = [message.from_email for message in messages]
            return len(messages)

        with override_settings(
                EMAIL_BACKEND='hrcloudpay.email_backend.PlatformEmailBackend'
        ), patch('django.core.mail.backends.smtp.EmailBackend.send_messages',
                 new=capture):
            response = self.client.post(
                TEST_URL, {'to': 'ops@example.com'}, format='json')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(captured['from'], ['mail@hrcloudpay.com'])

    def test_a_failed_send_is_audited_and_reported(self):
        """A wrong password must surface here, not when a customer waits."""
        self.save_config()

        with override_settings(
                EMAIL_BACKEND=(
                    'accounts.tests_platform_email_config._RefusingBackend')
        ):
            response = self.client.post(
                TEST_URL, {'to': 'ops@example.com'}, format='json')

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.data['success'])
        self.assertIn('bad credentials', response.data['detail'])

        row = AuditLog.objects.filter(action='platform_email_test').first()
        self.assertFalse(row.metadata['success'])
        # The SMTP response is useful and carries no credential; the password
        # must not have leaked into it.
        self.assertNotIn(SMTP_PASSWORD, str(row.metadata))