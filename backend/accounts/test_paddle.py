"""
Regression tests for the Paddle Billing payment gateway integration.

All Paddle API calls are mocked - no real network access. The webhook
tests exercise the real HMAC signature verification against locally
computed signatures.
"""
import hashlib
import hmac
import json
import time
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import Company, User
from accounts.platform_models import (
    BillingInvoice, PaymentEvent, PaymentPlan, PaymentProviderConfig,
    PaymentTransaction, Subscription,
)
from accounts.secrets import encrypt_secret

WEBHOOK_URL = '/api/auth/payments/webhook/paddle/'
CHECKOUT_URL = '/api/auth/billing/checkout/'
VERIFY_URL = '/api/auth/billing/verify/'
BILLING_URL = '/api/auth/billing/'
PROVIDERS_URL = '/api/auth/platform/payment-providers/'


def make_company(name, email, plan='starter', sub_status='trial'):
    company = Company.objects.create(name=name, email=email, is_active=True, plan=plan)
    Subscription.objects.create(
        company=company, status=sub_status, billing_cycle='monthly',
        trial_ends_at=timezone.now() + timedelta(days=14),
    )
    return company


def make_owner(company, username='owner@example.com'):
    return User.objects.create_user(
        username=username, email=username, password='StrongPassword123!',
        company=company, role='owner',
    )


def enable_paddle(environment='test', with_webhook_secret=True):
    config = PaymentProviderConfig.objects.get_or_create(provider='paddle')[0]
    config.enabled = True
    config.environment = environment
    config.encrypted_secret_key = encrypt_secret('pdl_test_secret')
    config.webhook_secret = encrypt_secret('whsec_paddle_test') if with_webhook_secret else ''
    config.configured_at = timezone.now()
    config.save()
    return config


def sign_paddle_webhook(payload, secret='whsec_paddle_test', ts=None):
    body = json.dumps(payload)
    ts = str(int(time.time())) if ts is None else str(ts)
    signature = f"ts={ts};h1={hmac.new(secret.encode(), f'{ts}:{body}'.encode(), hashlib.sha256).hexdigest()}"
    return body, signature


def completed_data(reference, transaction_id='txn_01hcp_completed_abc', subscription_id='sub_01hcp_sub_abc',
                   amount_cents='4900', currency='USD', status='completed'):
    return {
        'id': transaction_id,
        'status': status,
        'customer_id': 'cus_01hcp_customer_abc',
        'custom_data': {'company_id': 999, 'internal_reference': reference},
        'currency_code': currency,
        'collection_mode': 'automatic',
        'subscription_id': subscription_id,
        'items': [{'price_id': 'pri_01hcp_price_abc', 'quantity': 1,
                   'price': {'id': 'pri_01hcp_price_abc'}}],
        'details': {'totals': {'grand_total': amount_cents, 'grand_total_tax': '0',
                               'subtotal': amount_cents, 'tax': '0', 'discount': '0',
                               'currency_code': currency}},
        'payments': [{'id': 'pay_01hcp_payment_abc', 'status': 'captured',
                      'amount': amount_cents}],
        'checkout': {'url': 'https://checkout.paddle.com/example?_ptxn=txn_01hcp_completed_abc'},
        'created_at': '2026-01-01T00:00:00Z', 'updated_at': '2026-01-01T00:00:10Z',
    }


def completed_webhook(reference, **kwargs):
    return {
        'event_id': 'evt_01hcp_webhook_event_abc',
        'event_type': 'transaction.completed',
        'occurred_at': '2026-01-01T00:00:12Z',
        'notification_id': 'ntf_01hcp_webhook_notif_abc',
        'data': completed_data(reference, **kwargs),
    }


class PaddleServiceTests(TestCase):
    """Unit tests for payment_services.paddle_* against a mocked API."""

    def setUp(self):
        self.company = make_company('Acme', 'acme@example.com')
        self.user = make_owner(self.company)
        self.config = enable_paddle()

    def _mock_api(self, transaction_checkout_url='https://checkout.paddle.com/acme?_ptxn=txn_create_1'):
        def handler(path, method='GET', payload=None, secret='', base_url=''):
            if path.startswith('/products') and method == 'GET':
                return {'data': []}
            if path == '/products' and method == 'POST':
                return {'data': {'id': 'pro_01hcp_product_1'}}
            if path == '/prices' and method == 'POST':
                return {'data': {'id': 'pri_01hcp_price_1', 'status': 'active'}}
            if path == '/transactions' and method == 'POST':
                return {'data': {
                    'id': 'txn_create_1',
                    'status': 'draft',
                    'checkout': {'url': transaction_checkout_url},
                    'custom_data': (payload or {}).get('custom_data', {}),
                }}
            if path.startswith('/transactions/') and method == 'GET':
                return {'data': {'id': 'txn_verify_1', 'status': 'completed'}}
            raise AssertionError(f'unexpected API call {method} {path}')
        return handler

    def test_paddle_provider_config_raises_when_disabled(self):
        PaymentProviderConfig.objects.filter(provider='paddle').update(enabled=False)
        from accounts.payment_services import paddle_provider_config
        with self.assertRaises(RuntimeError):
            paddle_provider_config()

    def test_paddle_environment_selects_base_url(self):
        from accounts import payment_services
        calls = []
        def handler(path, method='GET', payload=None, secret='', base_url=''):
            calls.append(base_url)
            if path.startswith('/products') and method == 'GET':
                return {'data': []}
            if path == '/products' and method == 'POST':
                return {'data': {'id': 'pro_x'}}
            if path == '/prices' and method == 'POST':
                return {'data': {'id': 'pri_x'}}
            if path == '/transactions' and method == 'POST':
                return {'data': {'id': 'txn_x', 'checkout': {'url': 'https://checkout.paddle.com/x?_ptxn=txn_x'}}}
            raise AssertionError(path)
        with patch.object(payment_services, '_paddle_request', side_effect=handler):
            payment_services.paddle_initialize_checkout(self.company, self.user, 'business')
        self.assertEqual(calls[0], 'https://sandbox-api.paddle.com')
        self.config.environment = 'live'
        self.config.save()
        with patch.object(payment_services, '_paddle_request', side_effect=handler):
            payment_services.paddle_initialize_checkout(self.company, self.user, 'business')
        self.assertEqual(calls[-1], 'https://api.paddle.com')

    def test_initialize_checkout_creates_pending_transaction(self):
        from accounts import payment_services
        with patch.object(payment_services, '_paddle_request', side_effect=self._mock_api()) as mock:
            result = payment_services.paddle_initialize_checkout(self.company, self.user, 'business', 'monthly', 'USD')
        self.assertEqual(result['provider'], 'paddle')
        self.assertEqual(result['checkout_url'], 'https://checkout.paddle.com/acme?_ptxn=txn_create_1')
        self.assertTrue(result['reference'].startswith('HCP-'))
        tx = PaymentTransaction.objects.get(reference=result['reference'])
        self.assertEqual(tx.provider, 'paddle')
        self.assertEqual(tx.provider_transaction_id, 'txn_create_1')
        self.assertEqual(tx.status, 'pending')
        self.assertEqual(tx.plan, 'business')
        self.assertEqual(tx.amount, Decimal('49.00'))
        self.assertEqual(tx.currency, 'USD')
        self.assertEqual(tx.metadata['price_id'], 'pri_01hcp_price_1')
        # The POST /transactions payload uses automatic collection, the
        # recurring price, and carries our internal reference.
        calls = [c for c in mock.call_args_list if c.args[0] == '/transactions']
        payload = calls[0].args[2]
        self.assertEqual(payload['collection_mode'], 'automatic')
        self.assertEqual(payload['items'], [{'price_id': 'pri_01hcp_price_1', 'quantity': 1}])
        self.assertEqual(payload['currency_code'], 'USD')
        self.assertEqual(payload['custom_data']['internal_reference'], result['reference'])
        self.assertEqual(payload['custom_data']['company_id'], self.company.id)

    def test_initialize_checkout_price_payload_uses_cents_and_interval(self):
        from accounts import payment_services
        price_payloads = []
        def handler(path, method='GET', payload=None, secret='', base_url=''):
            if path.startswith('/products') and method == 'GET':
                return {'data': [{'id': 'pro_existing', 'name': 'HRCloudPay', 'status': 'active'}]}
            if path == '/prices' and method == 'POST':
                price_payloads.append(payload)
                return {'data': {'id': 'pri_x'}}
            if path == '/transactions' and method == 'POST':
                return {'data': {'id': 'txn_x', 'checkout': {'url': 'https://checkout.paddle.com/x?_ptxn=txn_x'}}}
            raise AssertionError(path)
        with patch.object(payment_services, '_paddle_request', side_effect=handler):
            payment_services.paddle_initialize_checkout(self.company, self.user, 'professional', 'annual', 'USD')
        payload = price_payloads[0]
        self.assertEqual(payload['product_id'], 'pro_existing')
        self.assertEqual(payload['billing_cycle'], {'interval': 'year', 'frequency': 1})
        # 99.00 monthly x 10 = 990.00 -> 99000 minor units
        self.assertEqual(payload['unit_price'], {'amount': '99000', 'currency_code': 'USD'})
        self.assertEqual(payload['tax_mode'], 'account_setting')

    def test_price_cached_in_payment_plan(self):
        from accounts import payment_services
        with patch.object(payment_services, '_paddle_request', side_effect=self._mock_api()) as mock:
            first, _ = payment_services.ensure_paddle_price('business', 'monthly', 'USD')
            second, _ = payment_services.ensure_paddle_price('business', 'monthly', 'USD')
        self.assertEqual(first, second)
        price_calls = [c for c in mock.call_args_list if c.args[0] == '/prices' and c.args[1] == 'POST']
        self.assertEqual(len(price_calls), 1)
        row = PaymentPlan.objects.get(provider='paddle', plan='business', billing_cycle='monthly', currency='USD')
        self.assertEqual(row.external_plan_id, 'pri_01hcp_price_1')
        self.assertEqual(row.amount, Decimal('49.00'))

    def test_activate_happy_path(self):
        from accounts import payment_services
        tx = PaymentTransaction.objects.create(
            company=self.company, subscription=self.company.subscription, provider='paddle',
            reference='HCP-ACTIVATE-1', provider_transaction_id='txn_01hcp_completed_abc',
            plan='business', billing_cycle='monthly', amount=Decimal('49.00'), currency='USD',
            status='pending', metadata={'price_id': 'pri_01hcp_price_abc'},
        )
        data = completed_data('HCP-ACTIVATE-1')
        ok = payment_services.paddle_activate_from_verified(tx, data)
        self.assertTrue(ok)
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'paid')
        self.assertEqual(tx.paid_at is not None, True)
        sub = self.company.subscription
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.provider, 'paddle')
        self.assertEqual(sub.external_subscription_id, 'sub_01hcp_sub_abc')
        self.assertEqual(sub.provider_plan_id, 'pri_01hcp_price_abc')
        self.assertEqual(self.company.plan, 'business')
        self.assertEqual(sub.monthly_price, Decimal('49.00'))
        self.assertTrue(BillingInvoice.objects.filter(transaction=tx, status='paid').exists())

    def test_activate_is_idempotent(self):
        from accounts import payment_services
        tx = PaymentTransaction.objects.create(
            company=self.company, subscription=self.company.subscription, provider='paddle',
            reference='HCP-IDEMPOTENT', provider_transaction_id='txn_x',
            plan='business', billing_cycle='monthly', amount=Decimal('49.00'), currency='USD',
            status='paid', paid_at=timezone.now(),
        )
        sub = self.company.subscription
        sub.status = 'active'; sub.renews_at = timezone.now() + timedelta(days=30); sub.save()
        original_renews_at = sub.renews_at
        ok = payment_services.paddle_activate_from_verified(tx, completed_data('HCP-IDEMPOTENT'))
        self.assertTrue(ok)
        sub.refresh_from_db()
        self.assertEqual(sub.renews_at, original_renews_at)

    def test_activate_amount_mismatch_keeps_subscription_pending(self):
        from accounts import payment_services
        tx = PaymentTransaction.objects.create(
            company=self.company, subscription=self.company.subscription, provider='paddle',
            reference='HCP-AMOUNT', provider_transaction_id='txn_x',
            plan='business', billing_cycle='monthly', amount=Decimal('49.00'), currency='USD',
            status='pending',
        )
        data = completed_data('HCP-AMOUNT', amount_cents='1234')
        ok = payment_services.paddle_activate_from_verified(tx, data)
        self.assertFalse(ok)
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'pending')
        self.assertEqual(self.company.subscription.status, 'trial')

    def test_activate_currency_mismatch(self):
        from accounts import payment_services
        tx = PaymentTransaction.objects.create(
            company=self.company, subscription=self.company.subscription, provider='paddle',
            reference='HCP-CUR', provider_transaction_id='txn_x',
            plan='business', billing_cycle='monthly', amount=Decimal('49.00'), currency='USD',
            status='pending',
        )
        ok = payment_services.paddle_activate_from_verified(tx, completed_data('HCP-CUR', currency='EUR'))
        self.assertFalse(ok)

    def test_activate_reference_mismatch_is_failed(self):
        from accounts import payment_services
        tx = PaymentTransaction.objects.create(
            company=self.company, subscription=self.company.subscription, provider='paddle',
            reference='HCP-REAL', provider_transaction_id='txn_x',
            plan='business', billing_cycle='monthly', amount=Decimal('49.00'), currency='USD',
            status='pending',
        )
        ok = payment_services.paddle_activate_from_verified(tx, completed_data('HCP-OTHER'))
        self.assertFalse(ok)
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'failed')

    def test_activate_canceled_status_marks_failed(self):
        from accounts import payment_services
        tx = PaymentTransaction.objects.create(
            company=self.company, subscription=self.company.subscription, provider='paddle',
            reference='HCP-CANCEL', provider_transaction_id='txn_x',
            plan='business', billing_cycle='monthly', amount=Decimal('49.00'), currency='USD',
            status='pending',
        )
        ok = payment_services.paddle_activate_from_verified(tx, completed_data('HCP-CANCEL', status='canceled'))
        self.assertFalse(ok)
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'failed')

    def test_activate_draft_status_keeps_pending(self):
        from accounts import payment_services
        tx = PaymentTransaction.objects.create(
            company=self.company, subscription=self.company.subscription, provider='paddle',
            reference='HCP-DRAFT', provider_transaction_id='txn_x',
            plan='business', billing_cycle='monthly', amount=Decimal('49.00'), currency='USD',
            status='pending',
        )
        ok = payment_services.paddle_activate_from_verified(tx, completed_data('HCP-DRAFT', status='draft'))
        self.assertFalse(ok)
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'pending')


class PaddleCheckoutViewTests(TestCase):
    """API tests for checkout/verify provider dispatch (mocked services)."""

    def setUp(self):
        self.company = make_company('Beta Co', 'beta@example.com')
        self.user = make_owner(self.company)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.token = Token.objects.create(user=self.user)

    def test_checkout_defaults_to_paddle_when_enabled(self):
        enable_paddle()
        with patch('accounts.payment_services.paddle_initialize_checkout', return_value={
            'reference': 'HCP-PADDLE-1', 'checkout_url': 'https://checkout.paddle.com/x?_ptxn=txn_1',
            'amount': '49.00', 'currency': 'USD',
        }) as paddle_init, \
             patch('accounts.payment_services.initialize_checkout') as flw_init:
            response = self.client.post(CHECKOUT_URL, {'plan': 'business', 'billing_cycle': 'monthly'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['provider'], 'paddle')
        paddle_init.assert_called_once()
        flw_init.assert_not_called()

    def test_checkout_explicit_paddle_and_flutterwave(self):
        enable_paddle()
        PaymentProviderConfig.objects.get_or_create(provider='flutterwave', defaults={
            'enabled': True, 'environment': 'test',
            'encrypted_secret_key': encrypt_secret('flw_secret'),
        })
        with patch('accounts.payment_services.paddle_initialize_checkout', return_value={
            'reference': 'HCP-P1', 'checkout_url': 'https://checkout.paddle.com/x?_ptxn=t', 'amount': '49.00', 'currency': 'USD',
        }), patch('accounts.payment_services.initialize_checkout', return_value={
            'reference': 'HCP-F1', 'checkout_url': 'https://checkout.flutterwave.com/f', 'amount': '49.00', 'currency': 'USD',
        }):
            paddle_resp = self.client.post(CHECKOUT_URL, {'plan': 'business', 'provider': 'paddle'}, format='json')
            flw_resp = self.client.post(CHECKOUT_URL, {'plan': 'business', 'provider': 'flutterwave'}, format='json')
        self.assertEqual(paddle_resp.data['provider'], 'paddle')
        self.assertEqual(flw_resp.data['provider'], 'flutterwave')

    def test_checkout_defaults_to_flutterwave_when_paddle_disabled(self):
        PaymentProviderConfig.objects.get_or_create(provider='flutterwave', defaults={
            'enabled': True, 'environment': 'test',
            'encrypted_secret_key': encrypt_secret('flw_secret'),
        })
        with patch('accounts.payment_services.paddle_initialize_checkout') as paddle_init, \
             patch('accounts.payment_services.initialize_checkout', return_value={
                 'reference': 'HCP-F2', 'checkout_url': 'https://checkout.flutterwave.com/f', 'amount': '49.00', 'currency': 'USD',
             }) as flw_init:
            response = self.client.post(CHECKOUT_URL, {'plan': 'business'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['provider'], 'flutterwave')
        flw_init.assert_called_once()
        paddle_init.assert_not_called()

    def test_checkout_no_provider_enabled_returns_400(self):
        response = self.client.post(CHECKOUT_URL, {'plan': 'business'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('No payment provider is enabled', response.data['detail'])

    def test_checkout_unknown_provider_returns_400(self):
        enable_paddle()
        response = self.client.post(CHECKOUT_URL, {'plan': 'business', 'provider': 'paystack'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_checkout_paddle_disabled_explicit_returns_400(self):
        response = self.client.post(CHECKOUT_URL, {'plan': 'business', 'provider': 'paddle'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('Paddle is not enabled', response.data['detail'])

    def test_verify_without_transaction_id_uses_provider_transaction_id(self):
        enable_paddle()
        tx = PaymentTransaction.objects.create(
            company=self.company, subscription=self.company.subscription, provider='paddle',
            reference='HCP-VERIFY', provider_transaction_id='txn_verify_target',
            plan='business', billing_cycle='monthly', amount=Decimal('49.00'), currency='USD',
            status='pending', checkout_url='https://checkout.paddle.com/x?_ptxn=txn_verify_target',
        )
        with patch('accounts.payment_services.paddle_verify_transaction', return_value={
            'id': 'txn_verify_target', 'status': 'completed',
            'custom_data': {'internal_reference': 'HCP-VERIFY'},
            'currency_code': 'USD',
            'details': {'totals': {'grand_total': '4900'}},
        }) as verify_mock, \
             patch('accounts.payment_services.paddle_activate_from_verified', return_value=True):
            response = self.client.post(VERIFY_URL, {'reference': 'HCP-VERIFY'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        verify_mock.assert_called_once_with('txn_verify_target')
        tx.refresh_from_db()

    def test_verify_flutterwave_without_transaction_id_returns_400(self):
        PaymentTransaction.objects.create(
            company=self.company, subscription=self.company.subscription, provider='flutterwave',
            reference='HCP-FLW', provider_transaction_id='',
            plan='business', billing_cycle='monthly', amount=Decimal('49.00'), currency='USD',
            status='pending', checkout_url='https://checkout.flutterwave.com/f',
        )
        response = self.client.post(VERIFY_URL, {'reference': 'HCP-FLW'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['detail'], 'transaction_id is required.')

    def test_verify_unknown_reference_returns_404(self):
        response = self.client.post(VERIFY_URL, {'reference': 'HCP-NOPE', 'transaction_id': 'x'}, format='json')
        self.assertEqual(response.status_code, 404)

    def test_pending_reference_exposed_in_billing_view(self):
        enable_paddle()
        PaymentTransaction.objects.create(
            company=self.company, subscription=self.company.subscription, provider='paddle',
            reference='HCP-PENDING', provider_transaction_id='txn_pending',
            plan='business', billing_cycle='monthly', amount=Decimal('49.00'), currency='USD',
            status='pending', checkout_url='https://checkout.paddle.com/x?_ptxn=txn_pending',
        )
        response = self.client.get(BILLING_URL)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['pending_reference'], 'HCP-PENDING')
        # Once paid (e.g. by the webhook) the pending reference disappears.
        PaymentTransaction.objects.filter(reference='HCP-PENDING').update(status='paid')
        response = self.client.get(BILLING_URL)
        self.assertIsNone(response.data['pending_reference'])


class PaddleWebhookTests(TestCase):
    """Webhook signature verification + event handling (no auth, no network)."""

    def setUp(self):
        self.company = make_company('Gamma Co', 'gamma@example.com', plan='business')
        self.user = make_owner(self.company)
        self.client = APIClient()
        enable_paddle()

    def _post(self, payload, secret='whsec_paddle_test', ts=None, signature=None):
        body, computed = sign_paddle_webhook(payload, secret, ts)
        if signature is None:
            signature = computed
        headers = {'HTTP_PADDLE_SIGNATURE': signature, 'HTTP_PADDLE_EVENT_ID': payload.get('event_id', '')}
        return self.client.post(WEBHOOK_URL, data=body, content_type='application/json', **headers)

    def _create_pending_tx(self, reference, transaction_id):
        return PaymentTransaction.objects.create(
            company=self.company, subscription=self.company.subscription, provider='paddle',
            reference=reference, provider_transaction_id=transaction_id,
            plan='business', billing_cycle='monthly', amount=Decimal('49.00'), currency='USD',
            status='pending', checkout_url='https://checkout.paddle.com/x?_ptxn=' + transaction_id,
            metadata={'price_id': 'pri_01hcp_price_abc'},
        )

    def test_transaction_completed_activates_subscription(self):
        tx = self._create_pending_tx('HCP-WEBHOOK-1', 'txn_01hcp_completed_abc')
        payload = completed_webhook('HCP-WEBHOOK-1', subscription_id='sub_01hcp_sub_abc')
        response = self._post(payload)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['received'], True)
        tx.refresh_from_db()
        self.assertEqual(tx.status, 'paid')
        sub = self.company.subscription
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.provider, 'paddle')
        self.assertEqual(sub.external_subscription_id, 'sub_01hcp_sub_abc')
        self.assertTrue(BillingInvoice.objects.filter(transaction=tx, status='paid').exists())
        event = PaymentEvent.objects.get(event_id='evt_01hcp_webhook_event_abc')
        self.assertEqual(event.status, 'processed')

    def test_webhook_renewal_creates_transaction_and_activates(self):
        sub = self.company.subscription
        sub.status = 'active'; sub.provider = 'paddle'
        sub.external_subscription_id = 'sub_01hcp_sub_abc'
        sub.renews_at = timezone.now() + timedelta(days=30)
        sub.save()
        payload = completed_webhook(
            'HCP-RENEWAL', transaction_id='txn_01hcp_renewal_abc',
            subscription_id='sub_01hcp_sub_abc',
        )
        response = self._post(payload)
        self.assertEqual(response.status_code, 200, response.data)
        tx = PaymentTransaction.objects.get(provider_transaction_id='txn_01hcp_renewal_abc')
        self.assertEqual(tx.status, 'paid')
        self.assertTrue(tx.metadata.get('recurring'))
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'active')

    def test_duplicate_event_id_is_deduped(self):
        tx = self._create_pending_tx('HCP-DUP', 'txn_01hcp_completed_abc')
        payload = completed_webhook('HCP-DUP')
        first = self._post(payload)
        self.assertEqual(first.status_code, 200, first.data)
        sub = self.company.subscription
        sub.refresh_from_db()
        first_activation_renews = sub.renews_at
        self.assertIsNotNone(first_activation_renews)
        payload['event_id'] = 'evt_01hcp_webhook_event_abc'
        second = self._post(payload)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(second.data['duplicate'], True)
        self.assertEqual(PaymentEvent.objects.filter(event_id='evt_01hcp_webhook_event_abc').count(), 1)
        # The duplicate event must not have extended the subscription again.
        sub.refresh_from_db()
        self.assertEqual(sub.renews_at, first_activation_renews)

    def test_bad_signature_returns_401(self):
        self._create_pending_tx('HCP-BAD', 'txn_01hcp_completed_abc')
        response = self._post(completed_webhook('HCP-BAD'), signature='ts=0;h1=deadbeef')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.company.subscription.status, 'trial')

    def test_stale_timestamp_returns_401(self):
        self._create_pending_tx('HCP-STALE', 'txn_01hcp_completed_abc')
        response = self._post(completed_webhook('HCP-STALE'), ts=int(time.time()) - 4000)
        self.assertEqual(response.status_code, 401)

    def test_missing_webhook_secret_returns_401(self):
        enable_paddle(with_webhook_secret=False)
        self._create_pending_tx('HCP-NOSEC', 'txn_01hcp_completed_abc')
        response = self._post(completed_webhook('HCP-NOSEC'))
        self.assertEqual(response.status_code, 401)

    def test_webhook_when_provider_disabled_returns_404(self):
        PaymentProviderConfig.objects.filter(provider='paddle').update(enabled=False)
        response = self._post(completed_webhook('HCP-DISABLED'))
        self.assertEqual(response.status_code, 404)

    def test_payment_failed_marks_subscription_past_due(self):
        sub = self.company.subscription
        sub.status = 'active'; sub.provider = 'paddle'
        sub.external_subscription_id = 'sub_01hcp_sub_abc'
        sub.save()
        payload = {
            'event_id': 'evt_01hcp_failed_event_1',
            'event_type': 'transaction.payment_failed',
            'occurred_at': '2026-01-05T00:00:00Z',
            'notification_id': 'ntf_01hcp_failed_notif_1',
            'data': {
                'id': 'txn_01hcp_failed_1',
                'subscription_id': 'sub_01hcp_sub_abc',
                'custom_data': {},
                'currency_code': 'USD',
                'payments': [],
            },
        }
        response = self._post(payload)
        self.assertEqual(response.status_code, 200, response.data)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'past_due')
        self.assertEqual(sub.failed_payment_count, 1)
        self.assertTrue(sub.grace_ends_at)

    def test_subscription_past_due_event(self):
        sub = self.company.subscription
        sub.status = 'active'; sub.provider = 'paddle'
        sub.external_subscription_id = 'sub_01hcp_sub_abc'
        sub.save()
        payload = {
            'event_id': 'evt_01hcp_pastdue_event_1',
            'event_type': 'subscription.past_due',
            'occurred_at': '2026-01-06T00:00:00Z',
            'notification_id': 'ntf_01hcp_pastdue_notif_1',
            'data': {'id': 'sub_01hcp_sub_abc', 'status': 'past_due', 'custom_data': {}},
        }
        response = self._post(payload)
        self.assertEqual(response.status_code, 200, response.data)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'past_due')

    def test_subscription_canceled_event(self):
        sub = self.company.subscription
        sub.status = 'active'; sub.provider = 'paddle'
        sub.external_subscription_id = 'sub_01hcp_sub_abc'
        sub.save()
        payload = {
            'event_id': 'evt_01hcp_cancel_event_1',
            'event_type': 'subscription.canceled',
            'occurred_at': '2026-01-07T00:00:00Z',
            'notification_id': 'ntf_01hcp_cancel_notif_1',
            'data': {'id': 'sub_01hcp_sub_abc', 'status': 'canceled', 'custom_data': {}},
        }
        response = self._post(payload)
        self.assertEqual(response.status_code, 200, response.data)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'cancelled')
        self.assertTrue(sub.cancelled_at)

    def test_subscription_activated_event_marks_active(self):
        sub = self.company.subscription
        sub.status = 'trial'; sub.provider = 'paddle'
        sub.external_subscription_id = ''
        sub.save()
        tx = self._create_pending_tx('HCP-ACTV', 'txn_01hcp_completed_actv')
        tx.status = 'paid'
        tx.save(update_fields=['status'])
        payload = {
            'event_id': 'evt_01hcp_active_event_1',
            'event_type': 'subscription.activated',
            'occurred_at': '2026-01-08T00:00:00Z',
            'notification_id': 'ntf_01hcp_active_notif_1',
            'data': {'id': 'sub_01hcp_sub_abc', 'status': 'active', 'custom_data': {'internal_reference': 'HCP-ACTV'}},
        }
        response = self._post(payload)
        self.assertEqual(response.status_code, 200, response.data)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'active')
        self.assertEqual(sub.provider, 'paddle')
        self.assertEqual(sub.external_subscription_id, 'sub_01hcp_sub_abc')

    def test_unsupported_event_is_received_but_unprocessed(self):
        payload = {
            'event_id': 'evt_01hcp_unknown_event_1',
            'event_type': 'transaction.untracked',
            'occurred_at': '2026-01-09T00:00:00Z',
            'notification_id': 'ntf_01hcp_unknown_notif_1',
            'data': {'id': 'txn_01hcp_unknown_1'},
        }
        response = self._post(payload)
        self.assertEqual(response.status_code, 200, response.data)
        event = PaymentEvent.objects.get(event_id='evt_01hcp_unknown_event_1')
        self.assertEqual(event.status, 'received')


class PaddlePaymentProviderConfigTests(TestCase):
    """Platform admin provisioning of the Paddle provider."""

    def setUp(self):
        self.staff = User.objects.create_user(
            username='staff', password='StrongPassword123!', is_staff=True,
        )
        self.super = User.objects.create_superuser(
            username='root', email='root@example.com', password='StrongPassword123!',
        )
        self.client = APIClient()

    def test_providers_list_includes_paddle(self):
        self.client.force_authenticate(self.staff)
        response = self.client.get(PROVIDERS_URL)
        self.assertEqual(response.status_code, 200, response.data)
        providers = {row['provider'] for row in response.data}
        self.assertIn('paddle', providers)
        paddle = next(row for row in response.data if row['provider'] == 'paddle')
        self.assertEqual(paddle['name'], 'Paddle')

    def test_post_requires_superuser(self):
        self.client.force_authenticate(self.staff)
        response = self.client.post(PROVIDERS_URL, {'provider': 'paddle', 'secret_key': 'pdl_sec'}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_post_configures_paddle(self):
        self.client.force_authenticate(self.super)
        response = self.client.post(PROVIDERS_URL, {
            'provider': 'paddle', 'enabled': True, 'environment': 'test',
            'secret_key': 'pdl_live_secret', 'webhook_secret': 'whsec_live',
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        config = PaymentProviderConfig.objects.get(provider='paddle')
        self.assertTrue(config.enabled)
        self.assertEqual(config.environment, 'test')
        self.assertTrue(config.encrypted_secret_key)
        self.assertTrue(config.webhook_secret)

    def test_toggle_requires_secret_before_enabling(self):
        PaymentProviderConfig.objects.create(provider='paddle', enabled=False)
        self.client.force_authenticate(self.super)
        response = self.client.post(PROVIDERS_URL + 'paddle/toggle/', {'enabled': True}, format='json')
        self.assertEqual(response.status_code, 400)
        PaymentProviderConfig.objects.filter(provider='paddle').update(encrypted_secret_key=encrypt_secret('x'))
        response = self.client.post(PROVIDERS_URL + 'paddle/toggle/', {'enabled': True}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(PaymentProviderConfig.objects.get(provider='paddle').enabled)