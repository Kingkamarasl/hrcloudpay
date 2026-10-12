"""Pasted payment credentials, and the newline that comes with them.

Enabling Paddle returned:

    Paddle API error (403): {"error":{"type":"request_error",
    "code":"authentication_malformed","detail":"Authentication header
    included, but incorrectly formatted."}}

The credential was not malformed. It was correct, wrapped in whitespace that
nothing in the stack removed. The key is typed into a password field by a person
copying it out of a dashboard, the browser submits the paste verbatim - trailing
newline, and on Windows the carriage return with it - and:

    encrypt_secret stored it byte-for-byte
    decrypt_secret returned it byte-for-byte
    f'Bearer {secret}' put "pdl_xxx\\r\\n" in the header

Paddle's `authentication_malformed` is an accurate and unhelpful error, because
it describes the header rather than the cause. These tests pin the cause.
"""

from unittest.mock import patch

from django.test import TestCase

from accounts import secrets
from accounts.payment_services import paddle_provider_config
from accounts.platform_models import PaymentProviderConfig

# Deliberately not shaped like a real key. Paddle's documented example key
# matches the credential pattern that GitHub's push protection scans for, and
# using it here made `git push` fail on a repository rule violation - correctly,
# because a string that is indistinguishable from a live credential should not
# be committed, even a fake one. These keep the prefixes the code checks for
# while being impossible to mistake for the real thing.
KEY = 'pdl_sdbx_apikey_examplekeynotreal'
LIVE_KEY = 'pdl_live_apikey_examplekeynotreal'


class CleanSecretTests(TestCase):
    """The normalisation itself, independent of any provider."""

    def test_a_plain_key_is_untouched(self):
        self.assertEqual(secrets.clean_secret(KEY), KEY)

    def test_a_trailing_newline_is_removed(self):
        """The failure. A paste from a .env file or a terminal lands here."""
        self.assertEqual(secrets.clean_secret(KEY + '\n'), KEY)

    def test_a_windows_carriage_return_is_removed(self):
        self.assertEqual(secrets.clean_secret(KEY + '\r\n'), KEY)

    def test_surrounding_whitespace_is_removed(self):
        self.assertEqual(secrets.clean_secret('  \t' + KEY + '  \n'), KEY)

    def test_a_duplicated_bearer_prefix_is_removed(self):
        """Copying the whole header rather than the token.

        Without this the request goes out as `Bearer Bearer pdl_...`, which Paddle
        rejects with the identical error.
        """
        self.assertEqual(secrets.clean_secret('Bearer ' + KEY), KEY)
        self.assertEqual(secrets.clean_secret('bearer ' + KEY), KEY)
        self.assertEqual(secrets.clean_secret('BEARER ' + KEY), KEY)

    def test_a_key_that_legitimately_contains_bearer_survives(self):
        """Only a leading scheme is stripped, never one inside the token."""
        self.assertEqual(secrets.clean_secret('pdl_bearer_test'), 'pdl_bearer_test')

    def test_empty_input_stays_empty(self):
        self.assertEqual(secrets.clean_secret(''), '')
        self.assertEqual(secrets.clean_secret(None), '')

    def test_the_key_is_never_sent_with_whitespace(self):
        """The property that matters, asserted on the header itself."""
        for dirty in (KEY + '\n', '  ' + KEY + '\r\n', 'Bearer ' + KEY + '\n'):
            header = f'Bearer {secrets.clean_secret(dirty)}'
            self.assertEqual(header, 'Bearer ' + KEY)


class PaddleSecretShapeTests(TestCase):
    """An opaque 403 is worse than a sentence saying what is wrong."""

    def setUp(self):
        self.config = PaymentProviderConfig.objects.create(
            provider='paddle', enabled=True, environment='test',
            encrypted_secret_key=secrets.encrypt_secret(KEY),
        )

    def test_a_correct_key_is_accepted(self):
        _, secret, base = paddle_provider_config()
        self.assertEqual(secret, KEY)
        self.assertEqual(base, 'https://sandbox-api.paddle.com')

    def test_a_key_stored_with_a_trailing_newline_still_works(self):
        """The case that matters most for the operator who already saved one.

        They do not have to find and re-enter a credential they got right the
        first time - deploying the fix is enough.
        """
        PaymentProviderConfig.objects.filter(pk=self.config.pk).update(
            encrypted_secret_key=secrets.encrypt_secret(KEY + '\r\n'))

        _, secret, _ = paddle_provider_config()
        self.assertEqual(secret, KEY)

    def test_live_environment_selects_the_live_base_url(self):
        PaymentProviderConfig.objects.filter(pk=self.config.pk).update(
            environment='live', encrypted_secret_key=secrets.encrypt_secret(LIVE_KEY))

        _, secret, base = paddle_provider_config()
        self.assertEqual(secret, LIVE_KEY)
        self.assertEqual(base, 'https://api.paddle.com')

    def test_a_live_key_is_not_rejected_for_lacking_the_sandbox_marker(self):
        """Both key shapes begin `pdl_`, so neither is rejected on shape."""
        for candidate in (KEY, LIVE_KEY,
                          'pdl_apikey_01hztvfnkcvbfk2htqvcynxjvc'):  # legacy
            PaymentProviderConfig.objects.filter(pk=self.config.pk).update(
                environment='live' if 'live' in candidate else 'test',
                encrypted_secret_key=secrets.encrypt_secret(candidate))
            _, secret, _ = paddle_provider_config()
            self.assertEqual(secret, candidate)


class PaddleEnvironmentMismatchTests(TestCase):
    """Sandbox and live are separate accounts with separate keys.

    The environment is a dropdown sitting next to the key, so the two drift
    apart easily, and Paddle's rejection names neither of them. These are the
    two combinations that can be selected and that Paddle will refuse.
    """

    def setUp(self):
        self.config = PaymentProviderConfig.objects.create(
            provider='paddle', enabled=True, environment='test',
            encrypted_secret_key=secrets.encrypt_secret(KEY),
        )

    def _expect(self, environment, secret, *expected):
        PaymentProviderConfig.objects.filter(pk=self.config.pk).update(
            environment=environment, encrypted_secret_key=secrets.encrypt_secret(secret))
        with self.assertRaises(RuntimeError) as caught:
            paddle_provider_config()
        for fragment in expected:
            self.assertIn(fragment, str(caught.exception))

    def test_a_live_key_with_the_sandbox_selected_is_explained(self):
        self._expect('test', LIVE_KEY, 'live key', 'sandbox environment',
                     'https://api.paddle.com')

    def test_a_sandbox_key_with_live_selected_is_explained(self):
        self._expect('live', KEY, 'sandbox key', 'live environment',
                     'https://sandbox-api.paddle.com')

    def test_the_mismatch_error_never_echoes_the_secret(self):
        PaymentProviderConfig.objects.filter(pk=self.config.pk).update(
            environment='test', encrypted_secret_key=secrets.encrypt_secret(LIVE_KEY))
        with self.assertRaises(RuntimeError) as caught:
            paddle_provider_config()
        message = str(caught.exception)
        self.assertIn(LIVE_KEY[:12], message, 'the prefix is needed to diagnose it')
        self.assertNotIn(LIVE_KEY[12:], message,
                         'anything past the identifying prefix is secret')

    def test_the_wrong_credential_is_named_rather_than_403ing(self):
        """The client-side token and the webhook secret both fail here.

        Both sit on the same Paddle screen as the API key and neither is `pdl_` -
        a client-side token starts `ctkn_`. The error says which credential is
        expected instead of surfacing Paddle's authentication_malformed.
        """
        for wrong in ('ctkn_abc123client', 'nws_abc123secret'):
            PaymentProviderConfig.objects.filter(pk=self.config.pk).update(
                encrypted_secret_key=secrets.encrypt_secret(wrong))
            with self.assertRaises(RuntimeError) as caught:
                paddle_provider_config()
            message = str(caught.exception)
            self.assertIn('does not look like a Paddle API key', message)
            self.assertIn('pdl_', message)
            self.assertNotIn(wrong[5:], message,
                             'the full credential must never appear in an error')

    def test_an_empty_secret_is_reported_before_a_request_is_made(self):
        PaymentProviderConfig.objects.filter(pk=self.config.pk).update(
            encrypted_secret_key=secrets.encrypt_secret('   \n'))

        with self.assertRaises(RuntimeError) as caught:
            paddle_provider_config()
        self.assertIn('does not look like a Paddle API key', str(caught.exception))


class SavePathTests(TestCase):
    """Trimming only on the way out would still leave a dirty row in the
    database, and every other reader of that column would keep seeing it."""

    def _save(self, secret):
        from rest_framework.test import APIClient

        from accounts.models import Company, User
        company = Company.objects.create(
            name='Northwind', email='o@northwind.example', is_active=True,
            plan='starter')
        root = User.objects.create_superuser(
            username='root', email='root@example.com',
            password='Str0ngPass-2026!', company=None)
        client = APIClient()
        client.force_authenticate(root)
        return client.post('/api/auth/platform/payment-providers/', {
            'provider': 'paddle', 'enabled': True, 'environment': 'test',
            'secret_key': secret, 'webhook_secret': secret,
        }, format='json')

    def test_a_pasted_key_is_stored_trimmed(self):
        response = self._save(KEY + '\r\n')
        self.assertEqual(response.status_code, 200, response.data)

        row = PaymentProviderConfig.objects.get(provider='paddle')
        self.assertEqual(secrets.decrypt_secret(row.encrypted_secret_key), KEY)

    def test_the_webhook_secret_is_stored_trimmed_too(self):
        self._save(KEY + '\r\n')

        row = PaymentProviderConfig.objects.get(provider='paddle')
        self.assertEqual(secrets.decrypt_secret(row.webhook_secret), KEY)


class HeaderTests(TestCase):
    """The last place it could go wrong, checked through the real function."""

    def _header_for(self, secret):
        captured = {}

        class FakeResponse:
            def read(self):
                return b'{"data": []}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout=None):
            captured.update(request.header_items())
            return FakeResponse()

        with patch('urllib.request.urlopen', fake_urlopen):
            from accounts.payment_services import _paddle_request
            _paddle_request('/products', 'GET', secret=secret,
                            base_url='https://sandbox-api.paddle.com')
        return dict(captured)

    def test_the_authorisation_header_has_no_trailing_whitespace(self):
        header = self._header_for(KEY + '\r\n')
        self.assertEqual(header['Authorization'], 'Bearer ' + KEY)

    def test_the_authorisation_header_never_doubles_the_scheme(self):
        header = self._header_for('Bearer ' + KEY + '\n')
        self.assertEqual(header['Authorization'], 'Bearer ' + KEY)