"""PayPal subscription checkout and webhook regressions; all remote calls are mocked."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Company, User
from accounts.platform_models import (
    BillingInvoice, PaymentEvent, PaymentPlan, PaymentProviderConfig,
    PaymentTransaction, Subscription,
)
from accounts.secrets import encrypt_secret, decrypt_secret

WEBHOOK_URL = '/api/auth/payments/webhook/paypal/'
CHECKOUT_URL = '/api/auth/billing/checkout/'
VERIFY_URL = '/api/auth/billing/verify/'
PROVIDERS_URL = '/api/auth/platform/payment-providers/'


def make_company(name='Acme', email='owner@acme.example', plan='business'):
    company = Company.objects.create(name=name, email=email, is_active=True, plan=plan)
    sub = Subscription.objects.create(
        company=company,
        status='trial',
        billing_cycle='monthly',
        currency='USD',
        monthly_price=Decimal('49.00'),
    )
    user = User.objects.create_user(
        username=email, email=email, password='StrongPassword123!',
        company=company, role='owner',
    )
    return company, sub, user


def enable_paypal(environment='test', with_webhook_id=True):
    config, _ = PaymentProviderConfig.objects.get_or_create(provider='paypal')
    config.enabled = True
    config.environment = environment
    config.public_key = 'paypal-client-id-example'
    config.encrypted_secret_key = encrypt_secret('paypal-client-secret-example')
    config.webhook_secret = encrypt_secret('paypal-webhook-id-example') if with_webhook_id else ''
    config.save()
    return config


def verified_subscription(subscription_id, reference, plan_id='P-PLAN-1', amount='49.00', currency='USD', status='ACTIVE'):
    paid_at = timezone.now() - timedelta(minutes=3)
    next_billing = timezone.now() + timedelta(days=27)
    return {
        'id': subscription_id,
        'status': status,
        'plan_id': plan_id,
        'custom_id': reference,
        'subscriber': {'payer_id': 'PAYER-123'},
        'billing_info': {
            'last_payment': {
                'amount': {'value': amount, 'currency_code': currency},
                'time': paid_at.isoformat(),
                'status': 'COMPLETED',
            },
            'next_billing_time': next_billing.isoformat(),
        },
    }


class PayPalPlanAndCheckoutTests(TestCase):
    def setUp(self):
        enable_paypal()
        self.company, self.sub, self.owner = make_company()

    def test_monthly_and_annual_checkout_create_hosted_subscription_and_pending_ledger_row(self):
        calls = []

        def api(path, method='GET', payload=None, request_id=''):
            calls.append((path, method, payload, request_id))
            if path.startswith('/v1/catalogs/products?'):
                return {'products': []}
            if path == '/v1/catalogs/products' and method == 'POST':
                return {'id': 'PROD-1'}
            if path == '/v1/billing/plans' and method == 'POST':
                return {'id': 'P-PLAN-1', 'status': 'ACTIVE'}
            if path == '/v1/billing/subscriptions' and method == 'POST':
                return {
                    'id': 'I-SUBSCRIPTION-1',
                    'links': [{'rel': 'approve', 'href': 'https://www.sandbox.paypal.com/checkoutnow?token=I-SUBSCRIPTION-1'}],
                }
            raise AssertionError(f'unexpected {method} {path}')

        from accounts import payment_services
        with patch.object(payment_services, '_paypal_request', side_effect=api):
            result = payment_services.paypal_initialize_checkout(self.company, self.owner, 'business', 'annual', 'USD')

        self.assertEqual(result['provider'], 'paypal')
        self.assertEqual(result['amount'], '490.00')
        self.assertEqual(result['checkout_url'], 'https://www.sandbox.paypal.com/checkoutnow?token=I-SUBSCRIPTION-1')
        tx = PaymentTransaction.objects.get(reference=result['reference'])
        self.assertEqual(tx.provider, 'paypal')
        self.assertEqual(tx.provider_transaction_id, 'I-SUBSCRIPTION-1')
        self.assertEqual(tx.status, 'pending')
        self.assertEqual(tx.billing_cycle, 'annual')
        plan_call = next(call for call in calls if call[0] == '/v1/billing/plans')
        cycle = plan_call[2]['billing_cycles'][0]
        self.assertEqual(cycle['frequency'], {'interval_unit': 'YEAR', 'interval_count': 1})
        self.assertEqual(cycle['pricing_scheme']['fixed_price'], {'value': '490.00', 'currency_code': 'USD'})
        sub_call = next(call for call in calls if call[0] == '/v1/billing/subscriptions')
        self.assertEqual(sub_call[2]['custom_id'], result['reference'])
        self.assertEqual(sub_call[2]['plan_id'], 'P-PLAN-1')
        self.assertIn('reference=' + result['reference'], sub_call[2]['application_context']['return_url'])
        row = PaymentPlan.objects.get(provider='paypal', plan='business', billing_cycle='annual', currency='USD', environment='test')
        self.assertEqual(row.external_plan_id, 'P-PLAN-1')

    def test_sandbox_and_live_plans_are_cached_separately(self):
        from accounts import payment_services
        created_plan_ids = iter(['P-TEST', 'P-LIVE'])

        def api(path, method='GET', payload=None, request_id=''):
            if path.startswith('/v1/catalogs/products?'):
                return {'products': [{'id': 'PROD-1', 'name': 'HRCloudPay subscription', 'type': 'SERVICE'}]}
            if path == '/v1/billing/plans' and method == 'POST':
                return {'id': next(created_plan_ids), 'status': 'ACTIVE'}
            raise AssertionError(f'unexpected {method} {path}')

        with patch.object(payment_services, '_paypal_request', side_effect=api):
            self.assertEqual(payment_services.ensure_paypal_plan('business', 'monthly', 'USD')[0], 'P-TEST')
            PaymentProviderConfig.objects.filter(provider='paypal').update(environment='live')
            self.assertEqual(payment_services.ensure_paypal_plan('business', 'monthly', 'USD')[0], 'P-LIVE')
        self.assertEqual(set(PaymentPlan.objects.filter(provider='paypal').values_list('environment', flat=True)), {'test', 'live'})

    def test_non_usd_paypal_checkout_is_rejected(self):
        client = APIClient()
        client.force_authenticate(self.owner)
        response = client.post(CHECKOUT_URL, {'plan': 'business', 'billing_cycle': 'monthly', 'currency': 'EUR', 'provider': 'paypal'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('USD only', response.data['detail'])

    def test_missing_webhook_id_prevents_paypal_from_being_enabled(self):
        config = enable_paypal(with_webhook_id=False)
        config.enabled = False
        config.save(update_fields=['enabled'])
        client = APIClient()
        admin = User.objects.create_superuser(username='root', email='root@example.com', password='StrongPassword123!')
        client.force_authenticate(admin)
        response = client.post(PROVIDERS_URL, {
            'provider': 'paypal', 'enabled': True, 'environment': 'test',
            'public_key': config.public_key, 'secret_key': 'paypal-client-secret-example',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('webhook ID', response.data['detail'])
        config.refresh_from_db()
        self.assertFalse(config.enabled)
        self.assertEqual(decrypt_secret(config.encrypted_secret_key), 'paypal-client-secret-example')


class PayPalApprovalTests(TestCase):
    def setUp(self):
        enable_paypal()
        self.company, self.sub, self.owner = make_company()
        self.tx = PaymentTransaction.objects.create(
            company=self.company,
            subscription=self.sub,
            provider='paypal',
            reference='HCP-PAYPAL-TEST-1',
            provider_transaction_id='I-SUBSCRIPTION-1',
            plan='business',
            billing_cycle='monthly',
            amount=Decimal('49.00'),
            currency='USD',
            status='pending',
            metadata={'paypal_subscription_id': 'I-SUBSCRIPTION-1', 'paypal_plan_id': 'P-PLAN-1', 'environment': 'test'},
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def test_server_verification_activates_only_matching_paid_subscription(self):
        from accounts import payment_services
        data = verified_subscription('I-SUBSCRIPTION-1', self.tx.reference)
        with patch.object(payment_services, 'paypal_verify_subscription', return_value=data):
            response = self.client.post(VERIFY_URL, {'reference': self.tx.reference, 'transaction_id': 'I-SUBSCRIPTION-1'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, 'paid')
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.provider, 'paypal')
        self.assertEqual(self.sub.external_subscription_id, 'I-SUBSCRIPTION-1')
        self.assertEqual(self.sub.status, 'active')
        self.assertEqual(self.sub.monthly_price, Decimal('49.00'))
        self.assertEqual(BillingInvoice.objects.filter(transaction=self.tx, status='paid').count(), 1)

    def test_wrong_plan_amount_currency_or_custom_reference_never_activates(self):
        from accounts import payment_services
        invalid_responses = [
            verified_subscription('I-SUBSCRIPTION-1', self.tx.reference, plan_id='P-OTHER'),
            verified_subscription('I-SUBSCRIPTION-1', self.tx.reference, amount='48.99'),
            verified_subscription('I-SUBSCRIPTION-1', self.tx.reference, currency='EUR'),
            verified_subscription('I-SUBSCRIPTION-1', 'HCP-OTHER'),
            verified_subscription('I-SUBSCRIPTION-1', self.tx.reference, status='APPROVAL_PENDING'),
        ]
        pending_payment = verified_subscription('I-SUBSCRIPTION-1', self.tx.reference)
        pending_payment['billing_info']['last_payment']['status'] = 'PENDING'
        invalid_responses.append(pending_payment)
        for data in invalid_responses:
            with patch.object(payment_services, 'paypal_verify_subscription', return_value=data):
                response = self.client.post(VERIFY_URL, {'reference': self.tx.reference, 'transaction_id': 'I-SUBSCRIPTION-1'}, format='json')
            self.assertEqual(response.status_code, 400, response.data)
            self.sub.refresh_from_db()
            self.assertEqual(self.sub.status, 'trial')
            self.assertFalse(BillingInvoice.objects.filter(transaction=self.tx).exists())

    def test_company_cannot_verify_another_tenants_paypal_reference(self):
        second_company, second_sub, _ = make_company('Other Co', 'owner@other.example')
        other_tx = PaymentTransaction.objects.create(
            company=second_company, subscription=second_sub, provider='paypal',
            reference='HCP-PAYPAL-OTHER', provider_transaction_id='I-OTHER',
            plan='business', billing_cycle='monthly', amount=Decimal('49.00'),
            currency='USD', status='pending',
        )
        response = self.client.post(VERIFY_URL, {'reference': other_tx.reference, 'transaction_id': other_tx.provider_transaction_id}, format='json')
        self.assertEqual(response.status_code, 404)

    def test_reverification_is_idempotent_and_does_not_extend_the_period(self):
        from accounts import payment_services
        data = verified_subscription('I-SUBSCRIPTION-1', self.tx.reference)
        with patch.object(payment_services, 'paypal_verify_subscription', return_value=data):
            first = self.client.post(VERIFY_URL, {'reference': self.tx.reference}, format='json')
            self.sub.refresh_from_db()
            period_end = self.sub.current_period_end
            second = self.client.post(VERIFY_URL, {'reference': self.tx.reference}, format='json')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.current_period_end, period_end)
        self.assertEqual(BillingInvoice.objects.filter(transaction=self.tx).count(), 1)


class PayPalWebhookTests(TestCase):
    def setUp(self):
        enable_paypal()
        self.company, self.sub, self.owner = make_company()
        self.tx = PaymentTransaction.objects.create(
            company=self.company, subscription=self.sub, provider='paypal',
            reference='HCP-PAYPAL-WEBHOOK-1', provider_transaction_id='I-SUBSCRIPTION-1',
            plan='business', billing_cycle='monthly', amount=Decimal('49.00'),
            currency='USD', status='pending',
            metadata={'paypal_subscription_id': 'I-SUBSCRIPTION-1', 'paypal_plan_id': 'P-PLAN-1', 'environment': 'test'},
        )
        self.client = APIClient()

    def _post(self, payload):
        return self.client.post(
            WEBHOOK_URL, payload, format='json',
            HTTP_PAYPAL_AUTH_ALGO='SHA256withRSA',
            HTTP_PAYPAL_CERT_URL='https://api.paypal.com/certs/example',
            HTTP_PAYPAL_TRANSMISSION_ID='transmission-id-example',
            HTTP_PAYPAL_TRANSMISSION_SIG='signature-example',
            HTTP_PAYPAL_TRANSMISSION_TIME=timezone.now().isoformat(),
        )

    def test_bad_signature_is_rejected_without_recording_event(self):
        from accounts import payment_services
        payload = {'id': 'WH-EVENT-1', 'event_type': 'PAYMENT.SALE.COMPLETED', 'resource': {'id': 'SALE-1'}}
        with patch.object(payment_services, 'verify_paypal_webhook_signature', return_value=False):
            response = self._post(payload)
        self.assertEqual(response.status_code, 401)
        self.assertFalse(PaymentEvent.objects.filter(event_id='paypal:WH-EVENT-1').exists())

    def test_transient_processing_failure_returns_retryable_response(self):
        from accounts import payment_services
        payload = {'id': 'WH-RETRY-1', 'event_type': 'UNSUPPORTED.EVENT', 'resource': {}}
        with patch.object(payment_services, 'verify_paypal_webhook_signature', return_value=True), \
             patch.object(payment_services, 'process_paypal_webhook_event', side_effect=[RuntimeError('temporary API outage'), None]):
            first = self._post(payload)
            event = PaymentEvent.objects.get(event_id='paypal:WH-RETRY-1')
            self.assertEqual(event.status, 'verification_failed')
            retry = self._post(payload)
        self.assertEqual(first.status_code, 503)
        self.assertEqual(retry.status_code, 200)
        event.refresh_from_db()
        self.assertEqual(event.status, 'received')

    def test_initial_sale_event_is_signed_verified_and_idempotent(self):
        from accounts import payment_services
        payment_time = timezone.now() - timedelta(minutes=3)
        subscription_data = verified_subscription('I-SUBSCRIPTION-1', self.tx.reference)
        subscription_data['billing_info']['last_payment']['time'] = payment_time.isoformat()
        payload = {
            'id': 'WH-EVENT-1',
            'event_type': 'PAYMENT.SALE.COMPLETED',
            'resource': {
                'id': 'SALE-INITIAL-1',
                'billing_agreement_id': 'I-SUBSCRIPTION-1',
                'amount': {'total': '49.00', 'currency': 'USD'},
                'create_time': payment_time.isoformat(),
                'subscriber': {'email_address': 'private@buyer.example'},
            },
        }
        with patch.object(payment_services, 'verify_paypal_webhook_signature', return_value=True), \
             patch.object(payment_services, 'paypal_verify_subscription', return_value=subscription_data):
            first = self._post(payload)
            duplicate = self._post(payload)
            second_event_same_payment = self._post({**payload, 'id': 'WH-EVENT-2'})
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(duplicate.data.get('duplicate'), True)
        self.assertEqual(second_event_same_payment.status_code, 200, second_event_same_payment.data)
        self.assertEqual(PaymentTransaction.objects.filter(provider='paypal', status='paid').count(), 1)
        self.assertEqual(BillingInvoice.objects.filter(transaction__provider='paypal').count(), 1)
        event = PaymentEvent.objects.get(event_id='paypal:WH-EVENT-1')
        self.assertNotIn('subscriber', event.payload['resource'])
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, 'active')

    def test_recurring_completed_sale_creates_one_transaction_and_invoice(self):
        from accounts import payment_services
        now = timezone.now()
        self.tx.status = 'paid'
        self.tx.provider_transaction_id = 'SALE-INITIAL-1'
        self.tx.paid_at = now - timedelta(days=30)
        self.tx.save(update_fields=['status', 'provider_transaction_id', 'paid_at'])
        self.sub.provider = 'paypal'
        self.sub.status = 'active'
        self.sub.provider_plan_id = 'P-PLAN-1'
        self.sub.external_subscription_id = 'I-SUBSCRIPTION-1'
        self.sub.monthly_price = Decimal('49.00')
        self.sub.currency = 'USD'
        self.sub.last_payment_at = now - timedelta(days=30)
        self.sub.current_period_end = now
        self.sub.save()
        payment_time = now + timedelta(minutes=1)
        provider_data = {
            'id': 'I-SUBSCRIPTION-1', 'status': 'ACTIVE', 'plan_id': 'P-PLAN-1',
            'billing_info': {
                'last_payment': {'time': payment_time.isoformat(), 'amount': {'value': '49.00', 'currency_code': 'USD'}},
                'next_billing_time': (payment_time + timedelta(days=30)).isoformat(),
            },
        }
        payload = {
            'id': 'WH-RENEWAL-1', 'event_type': 'PAYMENT.SALE.COMPLETED',
            'resource': {
                'id': 'SALE-RENEWAL-1', 'billing_agreement_id': 'I-SUBSCRIPTION-1',
                'amount': {'total': '49.00', 'currency': 'USD'}, 'create_time': payment_time.isoformat(),
            },
        }
        with patch.object(payment_services, 'verify_paypal_webhook_signature', return_value=True), \
             patch.object(payment_services, 'paypal_verify_subscription', return_value=provider_data):
            first = self._post(payload)
            second = self._post({**payload, 'id': 'WH-RENEWAL-2'})
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        renewal = PaymentTransaction.objects.get(provider_transaction_id='SALE-RENEWAL-1')
        self.assertEqual(renewal.status, 'paid')
        self.assertTrue(renewal.metadata['recurring'])
        self.assertEqual(BillingInvoice.objects.filter(transaction=renewal).count(), 1)
        self.assertEqual(PaymentTransaction.objects.filter(provider_transaction_id='SALE-RENEWAL-1').count(), 1)

    def test_delayed_payment_failure_does_not_override_a_newer_paypal_payment(self):
        from accounts import payment_services
        now = timezone.now()
        self.sub.provider = 'paypal'
        self.sub.status = 'active'
        self.sub.external_subscription_id = 'I-SUBSCRIPTION-1'
        self.sub.last_payment_at = now - timedelta(days=30)
        self.sub.failed_payment_count = 0
        self.sub.save()
        provider_data = {
            'id': 'I-SUBSCRIPTION-1', 'status': 'ACTIVE',
            'billing_info': {'last_payment': {'time': now.isoformat()}},
        }
        payload = {
            'id': 'WH-OLD-FAILURE',
            'event_type': 'BILLING.SUBSCRIPTION.PAYMENT.FAILED',
            'create_time': (now - timedelta(days=1)).isoformat(),
            'resource': {'id': 'I-SUBSCRIPTION-1'},
        }
        with patch.object(payment_services, 'verify_paypal_webhook_signature', return_value=True), \
             patch.object(payment_services, 'paypal_verify_subscription', return_value=provider_data):
            response = self._post(payload)
        self.assertEqual(response.status_code, 200, response.data)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, 'active')
        self.assertEqual(self.sub.failed_payment_count, 0)

    def test_current_payment_failure_marks_subscription_past_due(self):
        from accounts import payment_services
        now = timezone.now()
        self.sub.provider = 'paypal'
        self.sub.status = 'active'
        self.sub.external_subscription_id = 'I-SUBSCRIPTION-1'
        self.sub.last_payment_at = now - timedelta(days=30)
        self.sub.save()
        provider_data = {
            'id': 'I-SUBSCRIPTION-1', 'status': 'ACTIVE',
            'billing_info': {'last_payment': {'time': (now - timedelta(days=30)).isoformat()}},
        }
        payload = {
            'id': 'WH-CURRENT-FAILURE',
            'event_type': 'BILLING.SUBSCRIPTION.PAYMENT.FAILED',
            'create_time': now.isoformat(),
            'resource': {'id': 'I-SUBSCRIPTION-1'},
        }
        with patch.object(payment_services, 'verify_paypal_webhook_signature', return_value=True), \
             patch.object(payment_services, 'paypal_verify_subscription', return_value=provider_data):
            response = self._post(payload)
        self.assertEqual(response.status_code, 200, response.data)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, 'past_due')
        self.assertEqual(self.sub.failed_payment_count, 1)

    def test_subscription_id_is_not_used_as_a_fallback_webhook_event_id(self):
        from accounts import payment_services
        payload = {'event_type': 'BILLING.SUBSCRIPTION.ACTIVATED', 'resource': {'id': 'I-SUBSCRIPTION-1'}}
        with patch.object(payment_services, 'verify_paypal_webhook_signature', return_value=True):
            response = self._post(payload)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PaymentEvent.objects.exists())


class PayPalCancellationTests(TestCase):
    def setUp(self):
        enable_paypal()
        self.company, self.sub, self.owner = make_company()
        self.sub.provider = 'paypal'
        self.sub.external_subscription_id = 'I-SUBSCRIPTION-1'
        self.sub.status = 'active'
        self.sub.current_period_end = timezone.now() + timedelta(days=20)
        self.sub.save()
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def test_cancellation_pauses_paypal_recurring_billing_before_setting_local_flag(self):
        from accounts import payment_services
        with patch.object(payment_services, 'paypal_pause_recurring_billing') as pause:
            response = self.client.post('/api/auth/billing/cancel/', {'reason': 'No longer needed'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        pause.assert_called_once_with('I-SUBSCRIPTION-1', 'No longer needed')
        self.assertIn('paused', response.data['message'].lower())
        self.assertEqual(response.data['subscription']['cancellation_mode'], 'paused')
        self.sub.refresh_from_db()
        self.assertTrue(self.sub.cancel_at_period_end)
        self.assertEqual(self.sub.status, 'active')

    def test_failed_paypal_cancellation_leaves_local_subscription_unchanged(self):
        from accounts import payment_services
        with patch.object(payment_services, 'paypal_pause_recurring_billing', side_effect=RuntimeError('provider unavailable')):
            response = self.client.post('/api/auth/billing/cancel/', {}, format='json')
        self.assertEqual(response.status_code, 502)
        self.sub.refresh_from_db()
        self.assertFalse(self.sub.cancel_at_period_end)

    def test_reactivation_calls_paypal_before_clearing_local_flag(self):
        from accounts import payment_services
        self.sub.cancel_at_period_end = True
        self.sub.cancellation_reason = 'scheduled'
        self.sub.save()
        with patch.object(payment_services, 'paypal_reactivate_subscription') as reactivate:
            response = self.client.post('/api/auth/billing/reactivate/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        reactivate.assert_called_once_with('I-SUBSCRIPTION-1')
        self.sub.refresh_from_db()
        self.assertFalse(self.sub.cancel_at_period_end)
