import json
import base64
import urllib.error
import urllib.request
import uuid
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

from django.db import transaction
from django.utils import timezone
from django.conf import settings

from .billing import PLAN_PRICES
from .platform_models import PaymentProviderConfig, PaymentPlan, PaymentTransaction, Subscription, BillingInvoice
from .secrets import decrypt_secret, clean_secret

FLW_BASE = 'https://api.flutterwave.com/v3'


def _request(path, method='GET', payload=None, secret=''):
    data = None
    headers = {'Authorization': f'Bearer {clean_secret(secret)}', 'Content-Type': 'application/json'}
    if payload is not None:
        data = json.dumps(payload).encode()
    req = urllib.request.Request(f'{FLW_BASE}{path}', data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors='replace')
        raise RuntimeError(f'Flutterwave API error ({exc.code}): {body[:500]}')


def provider_config():
    config = PaymentProviderConfig.objects.filter(provider='flutterwave', enabled=True).first()
    if not config or not config.encrypted_secret_key:
        raise RuntimeError('Flutterwave is not enabled or configured by the platform administrator.')
    return config, decrypt_secret(config.encrypted_secret_key)


def plan_amount(plan, billing_cycle):
    monthly = Decimal(str(PLAN_PRICES[plan])).quantize(Decimal('0.01'))
    if billing_cycle == 'monthly':
        return monthly
    return (monthly * Decimal('10')).quantize(Decimal('0.01'))


def ensure_payment_plan(plan, billing_cycle, currency):
    config, secret = provider_config()
    amount = plan_amount(plan, billing_cycle)
    interval = 'monthly' if billing_cycle == 'monthly' else 'yearly'
    currency = str(currency or 'USD').upper()
    row = PaymentPlan.objects.filter(provider='flutterwave', plan=plan, billing_cycle=billing_cycle, currency=currency, environment=config.environment).first()
    if row and row.external_plan_id:
        return row.external_plan_id
    response = _request('/payment-plans', 'POST', {
        'amount': str(amount),
        'name': f'HRCloudPay {plan.title()} {billing_cycle.title()}',
        'interval': interval,
        'currency': currency,
    }, secret)
    if response.get('status') != 'success':
        raise RuntimeError(response.get('message') or 'Unable to create Flutterwave payment plan.')
    data = response['data']
    try:
        with transaction.atomic():
            row, _ = PaymentPlan.objects.update_or_create(
                provider='flutterwave', plan=plan, billing_cycle=billing_cycle, currency=currency, environment=config.environment,
                defaults={'external_plan_id': str(data['id']), 'amount': amount},
            )
    except Exception:
        row = PaymentPlan.objects.filter(provider='flutterwave', plan=plan, billing_cycle=billing_cycle, currency=currency, environment=config.environment).first()
        if not row:
            raise
    return row.external_plan_id


def initialize_checkout(company, user, plan, billing_cycle='monthly', currency='USD'):
    external_plan_id = ensure_payment_plan(plan, billing_cycle, currency)
    _, secret = provider_config()
    reference = f'HCP-{uuid.uuid4().hex[:24].upper()}'
    amount = plan_amount(plan, billing_cycle)
    currency = str(currency or 'USD').upper()
    callback = f'{settings.FRONTEND_URL}/billing/success'
    payload = {
        'tx_ref': reference,
        'amount': str(amount),
        'currency': currency,
        'redirect_url': callback,
        'payment_plan': int(external_plan_id),
        'customer': {
            'email': user.email or company.email,
            'name': user.get_full_name() or company.name,
        },
        'meta': {
            'company_id': company.id,
            'subscription_id': company.subscription.id,
            'plan': plan,
            'billing_cycle': billing_cycle,
            'internal_reference': reference,
        },
        'customizations': {
            'title': 'HRCloudPay',
            'description': f'{plan.title()} {billing_cycle} subscription',
        },
    }
    response = _request('/payments', 'POST', payload, secret)
    if response.get('status') != 'success':
        raise RuntimeError(response.get('message') or 'Unable to initialize payment.')
    data = response['data']
    with transaction.atomic():
        PaymentTransaction.objects.create(
            company=company, subscription=company.subscription, provider='flutterwave',
            reference=reference, provider_transaction_id='', plan=plan,
            billing_cycle=billing_cycle, amount=amount, currency=currency,
            status='pending', checkout_url=data['link'], metadata={'payment_plan': external_plan_id},
        )
    return {'reference': reference, 'checkout_url': data['link'], 'amount': str(amount), 'currency': currency}


def verify_transaction(transaction_id):
    _, secret = provider_config()
    response = _request(f'/transactions/{transaction_id}/verify', 'GET', secret=secret)
    if response.get('status') != 'success':
        raise RuntimeError(response.get('message') or 'Unable to verify transaction.')
    return response['data']


def activate_from_verified_payment(tx, data):
    # A customer can refresh the Flutterwave callback page. Once this
    # transaction is marked paid, verifying it again must not extend the
    # subscription for another billing period.
    if tx.status == 'paid':
        return True
    status = str(data.get('status', '')).lower()
    reference = data.get('tx_ref') or data.get('reference')
    amount = Decimal(str(data.get('amount', '0')))
    currency = str(data.get('currency', '')).upper()
    amount_matches = abs(amount - tx.amount) <= Decimal('0.01')
    if status != 'successful' or reference != tx.reference or not amount_matches or currency != str(tx.currency or '').upper():
        tx.status = 'failed' if status in ('failed', 'cancelled') else 'pending'
        tx.provider_transaction_id = str(data.get('id') or '')
        tx.save(update_fields=['status', 'provider_transaction_id', 'updated_at'])
        return False
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().get(pk=tx.subscription_id)
        now = timezone.now()
        period = timedelta(days=30 if tx.billing_cycle == 'monthly' else 365)
        tx.status = 'paid'
        tx.provider_transaction_id = str(data.get('id') or '')
        tx.paid_at = now
        tx.save(update_fields=['status', 'provider_transaction_id', 'paid_at', 'updated_at'])
        tx.company.plan = tx.plan
        tx.company.save(update_fields=['plan', 'updated_at'])
        sub.status = 'active'
        sub.provider = 'flutterwave'
        sub.provider_plan_id = str(tx.metadata.get('payment_plan', ''))
        sub.external_subscription_id = str(data.get('subscription_id') or data.get('subscription') or sub.external_subscription_id or data.get('id') or '')
        sub.started_at = sub.started_at or now
        sub.current_period_start = now
        sub.current_period_end = now + period
        sub.renews_at = now + period
        sub.cancelled_at = None
        sub.grace_ends_at = None
        sub.trial_ends_at = None
        sub.cancel_at_period_end = False
        sub.cancellation_reason = ''
        sub.last_payment_at = now
        sub.failed_payment_count = 0
        sub.monthly_price = tx.amount if tx.billing_cycle == 'monthly' else tx.amount / Decimal('10')
        sub.currency = tx.currency
        sub.save()
        BillingInvoice.objects.update_or_create(
            transaction=tx,
            defaults={
                'company': tx.company, 'subscription': sub, 'number': f'INV-{now.strftime("%Y%m%d")}-{tx.reference[-10:]}',
                'plan': tx.plan, 'billing_cycle': tx.billing_cycle, 'amount': tx.amount, 'currency': tx.currency,
                'status': 'paid', 'paid_at': now, 'period_start': sub.current_period_start, 'period_end': sub.current_period_end,
                'metadata': {'provider': tx.provider, 'provider_transaction_id': tx.provider_transaction_id},
            },
        )
    return True


# --- Paddle Billing -----------------------------------------------------------

PADDLE_API_BASE = {'live': 'https://api.paddle.com', 'test': 'https://sandbox-api.paddle.com'}
PADDLE_PRODUCT_NAME = 'HRCloudPay'


def paddle_provider_config():
    config = PaymentProviderConfig.objects.filter(provider='paddle', enabled=True).first()
    if not config or not config.encrypted_secret_key:
        raise RuntimeError('Paddle is not enabled or configured by the platform administrator.')
    secret = clean_secret(decrypt_secret(config.encrypted_secret_key))
    environment = config.environment or 'test'

    # Paddle answers a header it cannot parse with `authentication_malformed`
    # and nothing else - per their error reference it means only that "an
    # Authorization header was sent, but it isn't in a valid format", with no
    # indication which character offended it. Checking the shape here turns an
    # opaque 403 into a sentence naming the problem, for the cost of two string
    # tests made before the request rather than after a failure.
    #
    # Only the first twelve characters are echoed back. The prefix is the part
    # that identifies the credential and the part needed to tell these cases
    # apart; the rest is a secret and must not reach a log or a response body.
    if not secret.startswith('pdl_'):
        raise RuntimeError(
            'The stored Paddle API key does not look like a Paddle API key: it '
            'starts "%s". A Paddle API key begins "pdl_sdbx_apikey_" (sandbox) '
            'or "pdl_live_apikey_" (live). Use the API key from Paddle > '
            'Developer tools > Authentication - not the client-side token, which '
            'starts "ctkn_", and not the webhook secret.'
            % (secret[:12] if secret else '(empty)'))

    # Sandbox and live are entirely separate accounts with separate keys, and a
    # key used against the wrong base URL is rejected. The environment is chosen
    # in a dropdown next to the key, so the two drift apart easily and the
    # resulting error names neither of them.
    if environment == 'test' and 'live' in secret:
        raise RuntimeError(
            'The stored Paddle API key is a live key ("%s...") but this '
            'provider is configured for the sandbox environment. Live keys only '
            'work against %s. Either switch the environment to "live" or store '
            'the sandbox key from the Paddle sandbox dashboard.'
            % (secret[:12], PADDLE_API_BASE['live']))
    if environment == 'live' and 'sdbx' in secret:
        raise RuntimeError(
            'The stored Paddle API key is a sandbox key ("%s...") but this '
            'provider is configured for the live environment. Sandbox keys only '
            'work against %s. Either switch the environment to "test" or store '
            'the live key from your live Paddle dashboard.'
            % (secret[:12], PADDLE_API_BASE['test']))

    return config, secret, PADDLE_API_BASE.get(environment, PADDLE_API_BASE['test'])


def _paddle_request(path, method='GET', payload=None, secret='', base_url=''):
    data = None
    # Trimmed again here, not only on save. Secrets pasted before clean_secret
    # existed are already stored with their trailing newline attached, and this
    # is what lets those credentials start working on the next deploy instead
    # of requiring the operator to re-enter one they had already got right.
    headers = {'Authorization': f'Bearer {clean_secret(secret)}', 'Content-Type': 'application/json'}
    if payload is not None:
        data = json.dumps(payload).encode()
    request = urllib.request.Request(f'{base_url}{path}', data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors='replace')
        raise RuntimeError(f'Paddle API error ({exc.code}): {body[:500]}')


def _paddle_amount_minor(data):
    """Return the paid amount in minor units (cents) from a Paddle transaction."""
    totals = (data.get('details') or {}).get('totals') or {}
    if totals.get('grand_total') is not None:
        return int(Decimal(str(totals['grand_total'])))
    for payment in data.get('payments') or []:
        if payment.get('status') == 'captured' and payment.get('amount') is not None:
            return int(Decimal(str(payment['amount'])))
    return None


def _ensure_paddle_product(secret, base_url):
    try:
        response = _paddle_request('/products?per_page=200', 'GET', secret=secret, base_url=base_url)
        for product in response.get('data') or []:
            if product.get('name') == PADDLE_PRODUCT_NAME and product.get('status') == 'active':
                return product['id']
    except RuntimeError:
        pass
    created = _paddle_request('/products', 'POST', {
        'name': PADDLE_PRODUCT_NAME,
        'tax_category': 'saas',
        'description': 'HRCloudPay subscription',
    }, secret, base_url)
    return created['data']['id']


def ensure_paddle_price(plan, billing_cycle='monthly', currency='USD'):
    config, secret, base_url = paddle_provider_config()
    amount = plan_amount(plan, billing_cycle)
    currency = str(currency or 'USD').upper()
    row = PaymentPlan.objects.filter(provider='paddle', plan=plan, billing_cycle=billing_cycle, currency=currency, environment=config.environment).first()
    if row and row.external_plan_id:
        return row.external_plan_id, amount
    interval = 'month' if billing_cycle == 'monthly' else 'year'
    product_id = _ensure_paddle_product(secret, base_url)
    response = _paddle_request('/prices', 'POST', {
        'description': f'HRCloudPay {plan.title()} · {billing_cycle}',
        'name': f'{plan.title()} {billing_cycle}',
        'product_id': product_id,
        'billing_cycle': {'interval': interval, 'frequency': 1},
        'unit_price': {'amount': str(int((amount * Decimal('100')).to_integral_value())), 'currency_code': currency},
        'quantity': {'minimum': 1, 'maximum': 100},
        'tax_mode': 'account_setting',
        'custom_data': {'hcp_plan': plan, 'hcp_billing_cycle': billing_cycle},
    }, secret, base_url)
    price_id = response['data']['id']
    try:
        with transaction.atomic():
            PaymentPlan.objects.update_or_create(
                provider='paddle', plan=plan, billing_cycle=billing_cycle, currency=currency, environment=config.environment,
                defaults={'external_plan_id': price_id, 'amount': amount},
            )
    except Exception:
        if not PaymentPlan.objects.filter(provider='paddle', plan=plan, billing_cycle=billing_cycle, currency=currency, environment=config.environment).exists():
            raise
    return price_id, amount


def paddle_initialize_checkout(company, user, plan, billing_cycle='monthly', currency='USD'):
    config, secret, base_url = paddle_provider_config()
    price_id, amount = ensure_paddle_price(plan, billing_cycle, currency)
    currency = str(currency or 'USD').upper()
    reference = f'HCP-{uuid.uuid4().hex[:24].upper()}'
    payload = {
        'items': [{'price_id': price_id, 'quantity': 1}],
        'currency_code': currency,
        'custom_data': {
            'company_id': company.id,
            'subscription_id': company.subscription.id,
            'plan': plan,
            'billing_cycle': billing_cycle,
            'internal_reference': reference,
        },
        'collection_mode': 'automatic',
    }
    response = _paddle_request('/transactions', 'POST', payload, secret, base_url)
    data = response.get('data') or {}
    transaction_id = str(data.get('id') or '')
    checkout_url = ((data.get('checkout') or {}).get('url') or '')
    if not transaction_id or not checkout_url:
        raise RuntimeError('Paddle did not return a checkout link for this transaction.')
    with transaction.atomic():
        PaymentTransaction.objects.create(
            company=company, subscription=company.subscription, provider='paddle',
            reference=reference, provider_transaction_id=transaction_id, plan=plan,
            billing_cycle=billing_cycle, amount=amount, currency=currency,
            status='pending', checkout_url=checkout_url, metadata={'price_id': price_id},
        )
    return {'reference': reference, 'checkout_url': checkout_url, 'amount': str(amount), 'currency': currency, 'provider': 'paddle'}


def paddle_verify_transaction(transaction_id):
    _, secret, base_url = paddle_provider_config()
    response = _paddle_request(f'/transactions/{transaction_id}', 'GET', secret=secret, base_url=base_url)
    return response.get('data') or {}


def paddle_activate_from_verified(tx, data):
    # The subscription may be activated by the webhook and by the customer-return
    # verification path. Both must be idempotent: re-verifying a paid transaction
    # must not extend the subscription for another billing period.
    if tx.status == 'paid':
        return True
    status = str(data.get('status', '')).lower()
    if status not in ('completed', 'paid', 'billed'):
        tx.status = 'failed' if status in ('canceled', 'past_due') else 'pending'
        tx.provider_transaction_id = str(data.get('id') or tx.provider_transaction_id or '')
        tx.save(update_fields=['status', 'provider_transaction_id', 'updated_at'])
        return False
    custom_data = data.get('custom_data') or {}
    reference = custom_data.get('internal_reference') or ''
    if reference and reference != tx.reference:
        tx.status = 'failed'
        tx.save(update_fields=['status', 'updated_at'])
        return False
    # Webhook renewals reference the subscription rather than an internal
    # reference; the amount and currency are still verified against the plan.
    amount_minor = _paddle_amount_minor(data)
    currency = str(data.get('currency_code') or '').upper()
    expected_minor = int((tx.amount * Decimal('100')).to_integral_value())
    if amount_minor is None or amount_minor != expected_minor or currency != str(tx.currency or '').upper():
        tx.status = 'pending'
        tx.save(update_fields=['status', 'updated_at'])
        return False
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().get(pk=tx.subscription_id)
        now = timezone.now()
        period = timedelta(days=30 if tx.billing_cycle == 'monthly' else 365)
        tx.status = 'paid'
        tx.provider_transaction_id = str(data.get('id') or tx.provider_transaction_id or '')
        tx.paid_at = now
        tx.save(update_fields=['status', 'provider_transaction_id', 'paid_at', 'updated_at'])
        tx.company.plan = tx.plan
        tx.company.save(update_fields=['plan', 'updated_at'])
        sub.status = 'active'
        sub.provider = 'paddle'
        sub.provider_plan_id = str(tx.metadata.get('price_id', ''))
        sub.external_subscription_id = str(data.get('subscription_id') or data.get('id') or sub.external_subscription_id or '')
        sub.started_at = sub.started_at or now
        sub.current_period_start = now
        sub.current_period_end = now + period
        sub.renews_at = now + period
        sub.cancelled_at = None
        sub.grace_ends_at = None
        sub.trial_ends_at = None
        sub.cancel_at_period_end = False
        sub.cancellation_reason = ''
        sub.last_payment_at = now
        sub.failed_payment_count = 0
        sub.monthly_price = tx.amount if tx.billing_cycle == 'monthly' else tx.amount / Decimal('10')
        sub.currency = tx.currency
        sub.save()
        BillingInvoice.objects.update_or_create(
            transaction=tx,
            defaults={
                'company': tx.company, 'subscription': sub, 'number': f'INV-{now.strftime("%Y%m%d")}-{tx.reference[-10:]}',
                'plan': tx.plan, 'billing_cycle': tx.billing_cycle, 'amount': tx.amount, 'currency': tx.currency,
                'status': 'paid', 'paid_at': now, 'period_start': sub.current_period_start, 'period_end': sub.current_period_end,
                'metadata': {'provider': tx.provider, 'provider_transaction_id': tx.provider_transaction_id},
            },
        )
    return True
from django.utils.dateparse import parse_datetime


# --- PayPal Subscriptions ------------------------------------------------------

PAYPAL_BASES = {
    'test': 'https://api-m.sandbox.paypal.com',
    'live': 'https://api-m.paypal.com',
}


def paypal_provider_config():
    config = PaymentProviderConfig.objects.filter(provider='paypal', enabled=True).first()
    if not config:
        raise RuntimeError('PayPal is not enabled by the platform administrator.')
    client_id = clean_secret(config.public_key)
    client_secret = clean_secret(decrypt_secret(config.encrypted_secret_key)) if config.encrypted_secret_key else ''
    webhook_id = clean_secret(decrypt_secret(config.webhook_secret)) if config.webhook_secret else ''
    missing = [name for name, value in (
        ('client ID', client_id), ('client secret', client_secret), ('webhook ID', webhook_id),
    ) if not value]
    if missing:
        raise RuntimeError('PayPal is enabled but missing its ' + ', '.join(missing) + '.')
    environment = config.environment or 'test'
    base_url = PAYPAL_BASES.get(environment)
    if not base_url:
        raise RuntimeError('PayPal environment must be test or live.')
    return config, client_id, client_secret, base_url


def _paypal_access_token(client_id, client_secret, base_url):
    credentials = base64.b64encode(f'{clean_secret(client_id)}:{clean_secret(client_secret)}'.encode()).decode('ascii')
    request = urllib.request.Request(
        f'{base_url}/v1/oauth2/token',
        data=urlencode({'grant_type': 'client_credentials'}).encode(),
        headers={
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'PayPal OAuth request failed (HTTP {exc.code}).') from None
    token = result.get('access_token')
    if not token:
        raise RuntimeError('PayPal OAuth did not return an access token.')
    return token


def _paypal_request(path, method='GET', payload=None, request_id=''):
    _, client_id, client_secret, base_url = paypal_provider_config()
    access_token = _paypal_access_token(client_id, client_secret, base_url)
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation',
    }
    if request_id:
        headers['PayPal-Request-Id'] = str(request_id)[:100]
    request = urllib.request.Request(f'{base_url}{path}', data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        # Provider response bodies can contain customer and account data. Do not
        # echo them to users or persist them in logs; status is enough to diagnose
        # the configuration/API class without leaking provider payloads.
        raise RuntimeError(f'PayPal API request failed (HTTP {exc.code}).') from None


def _paypal_product_id():
    response = _paypal_request('/v1/catalogs/products?page_size=100&page=1')
    for product in response.get('products') or []:
        if product.get('name') == 'HRCloudPay subscription' and product.get('type') == 'SERVICE':
            if product.get('id'):
                return str(product['id'])
    response = _paypal_request('/v1/catalogs/products', 'POST', {
        'name': 'HRCloudPay subscription',
        'description': 'HRCloudPay SaaS subscription',
        'type': 'SERVICE',
        'category': 'SOFTWARE',
    }, request_id='hcp-paypal-product-v1')
    product_id = str(response.get('id') or '')
    if not product_id:
        raise RuntimeError('PayPal did not return a product ID.')
    return product_id


def ensure_paypal_plan(plan, billing_cycle='monthly', currency='USD'):
    config, _, _, _ = paypal_provider_config()
    amount = plan_amount(plan, billing_cycle)
    currency = str(currency or 'USD').upper()
    if currency != 'USD':
        raise RuntimeError('PayPal subscription billing currently supports USD only.')
    row = PaymentPlan.objects.filter(
        provider='paypal', plan=plan, billing_cycle=billing_cycle,
        currency=currency, environment=config.environment,
    ).first()
    if row and row.external_plan_id and row.amount == amount:
        return row.external_plan_id, amount

    product_id = _paypal_product_id()
    interval_unit = 'MONTH' if billing_cycle == 'monthly' else 'YEAR'
    amount_key = str(amount).replace('.', '')
    suffix = f'{config.environment}-{plan}-{billing_cycle}-{currency}-{amount_key}'
    created = _paypal_request('/v1/billing/plans', 'POST', {
        'product_id': product_id,
        'name': f'HRCloudPay {plan.title()} {billing_cycle.title()}',
        'description': f'{plan.title()} {billing_cycle} subscription',
        'billing_cycles': [{
            'frequency': {'interval_unit': interval_unit, 'interval_count': 1},
            'tenure_type': 'REGULAR',
            'sequence': 1,
            'total_cycles': 0,
            'pricing_scheme': {
                'fixed_price': {'value': str(amount), 'currency_code': currency},
            },
        }],
        'payment_preferences': {
            'auto_bill_outstanding': True,
            'payment_failure_threshold': 3,
        },
    }, request_id=f'hcp-paypal-plan-{suffix}')
    plan_id = str(created.get('id') or '')
    if not plan_id:
        raise RuntimeError('PayPal did not return a subscription plan ID.')
    if str(created.get('status') or '').upper() != 'ACTIVE':
        _paypal_request(
            f'/v1/billing/plans/{plan_id}/activate', 'POST',
            {'reason': 'Activate HRCloudPay subscription plan'},
            request_id=f'hcp-paypal-activate-{suffix}',
        )
    try:
        with transaction.atomic():
            PaymentPlan.objects.update_or_create(
                provider='paypal', plan=plan, billing_cycle=billing_cycle,
                currency=currency, environment=config.environment,
                defaults={'external_plan_id': plan_id, 'amount': amount},
            )
    except Exception:
        saved = PaymentPlan.objects.filter(
            provider='paypal', plan=plan, billing_cycle=billing_cycle,
            currency=currency, environment=config.environment,
        ).first()
        if not saved or saved.amount != amount:
            raise
        return saved.external_plan_id, saved.amount
    return plan_id, amount


def paypal_initialize_checkout(company, user, plan, billing_cycle='monthly', currency='USD'):
    config, _, _, _ = paypal_provider_config()
    currency = str(currency or 'USD').upper()
    if currency != 'USD':
        raise RuntimeError('PayPal subscription billing currently supports USD only.')
    if billing_cycle not in ('monthly', 'annual'):
        raise RuntimeError('Unsupported PayPal billing cycle.')
    external_plan_id, amount = ensure_paypal_plan(plan, billing_cycle, currency)
    reference = f'HCP-{uuid.uuid4().hex[:24].upper()}'
    frontend_url = str(settings.FRONTEND_URL).rstrip('/')
    response = _paypal_request('/v1/billing/subscriptions', 'POST', {
        'plan_id': external_plan_id,
        'custom_id': reference,
        'application_context': {
            'brand_name': 'HRCloudPay',
            'user_action': 'SUBSCRIBE_NOW',
            'shipping_preference': 'NO_SHIPPING',
            'return_url': f'{frontend_url}/billing/success?provider=paypal&reference={reference}',
            'cancel_url': f'{frontend_url}/billing?paypal_cancel=1&reference={reference}',
        },
    }, request_id=f'hcp-paypal-subscription-{reference}')
    subscription_id = str(response.get('id') or '')
    approval_url = next((
        str(link.get('href') or '') for link in response.get('links') or []
        if link.get('rel') in ('approve', 'payer-action') and link.get('href')
    ), '')
    if not subscription_id or not approval_url:
        raise RuntimeError('PayPal did not return a subscription approval link.')
    with transaction.atomic():
        PaymentTransaction.objects.create(
            company=company,
            subscription=company.subscription,
            provider='paypal',
            reference=reference,
            provider_transaction_id=subscription_id,
            plan=plan,
            billing_cycle=billing_cycle,
            amount=amount,
            currency=currency,
            status='pending',
            checkout_url=approval_url,
            metadata={
                'paypal_subscription_id': subscription_id,
                'paypal_plan_id': external_plan_id,
                'environment': config.environment,
            },
        )
    return {
        'reference': reference,
        'checkout_url': approval_url,
        'amount': str(amount),
        'currency': currency,
        'provider': 'paypal',
    }


def _paypal_parse_time(value):
    if not value:
        return None
    parsed = parse_datetime(str(value))
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _paypal_amount_and_currency(payment):
    payment = payment or {}
    amount = payment.get('amount') or payment
    value = amount.get('value') if amount.get('value') is not None else amount.get('total')
    currency = amount.get('currency_code') or amount.get('currency') or payment.get('currency_code') or payment.get('currency')
    try:
        decimal_amount = Decimal(str(value)).quantize(Decimal('0.01'))
    except Exception:
        return None, ''
    return decimal_amount, str(currency or '').upper()


def paypal_verify_subscription(subscription_id):
    subscription_id = str(subscription_id or '')
    if not subscription_id or len(subscription_id) > 150 or any(not (c.isalnum() or c == '-') for c in subscription_id):
        raise RuntimeError('Invalid PayPal subscription ID.')
    return _paypal_request(f'/v1/billing/subscriptions/{subscription_id}')


def paypal_activate_from_verified_subscription(tx, data):
    """Activate a local pending transaction only from a matching paid PayPal subscription."""
    metadata = tx.metadata if isinstance(tx.metadata, dict) else {}
    if tx.provider != 'paypal':
        return False
    config, _, _, _ = paypal_provider_config()
    if metadata.get('environment') and metadata.get('environment') != config.environment:
        return False
    expected_subscription_id = str(metadata.get('paypal_subscription_id') or tx.provider_transaction_id or '')
    subscription_id = str((data or {}).get('id') or '')
    if not expected_subscription_id or subscription_id != expected_subscription_id:
        return False
    if tx.status == 'paid':
        return True
    if str((data or {}).get('custom_id') or '') != tx.reference:
        return False
    expected_plan_id = str(metadata.get('paypal_plan_id') or '')
    if not expected_plan_id or str((data or {}).get('plan_id') or '') != expected_plan_id:
        return False
    if str((data or {}).get('status') or '').upper() != 'ACTIVE':
        return False

    billing_info = (data or {}).get('billing_info') or {}
    last_payment = billing_info.get('last_payment') or {}
    payment_status = str(last_payment.get('status') or '').upper()
    if payment_status and payment_status not in ('COMPLETED', 'SUCCESS'):
        return False
    paid_amount, paid_currency = _paypal_amount_and_currency(last_payment)
    if paid_amount is None or paid_currency != str(tx.currency or '').upper() or paid_amount != tx.amount.quantize(Decimal('0.01')):
        return False
    payment_time = _paypal_parse_time(last_payment.get('time')) or timezone.now()
    next_billing_time = _paypal_parse_time(billing_info.get('next_billing_time'))
    if not next_billing_time or next_billing_time <= payment_time:
        return False

    with transaction.atomic():
        locked_tx = PaymentTransaction.objects.select_for_update().get(pk=tx.pk)
        if locked_tx.status == 'paid':
            return True
        sub = Subscription.objects.select_for_update().get(pk=locked_tx.subscription_id)
        now = timezone.now()
        locked_tx.status = 'paid'
        locked_tx.provider_transaction_id = subscription_id
        locked_tx.paid_at = payment_time
        locked_tx.metadata = {
            **(locked_tx.metadata or {}),
            'paypal_subscription_id': subscription_id,
            'paypal_plan_id': expected_plan_id,
            'paypal_initial_payment_time': payment_time.isoformat(),
        }
        locked_tx.save(update_fields=['status', 'provider_transaction_id', 'paid_at', 'metadata', 'updated_at'])

        locked_tx.company.plan = locked_tx.plan
        locked_tx.company.save(update_fields=['plan', 'updated_at'])
        sub.status = 'active'
        sub.provider = 'paypal'
        sub.provider_plan_id = expected_plan_id
        sub.external_subscription_id = subscription_id
        subscriber = (data or {}).get('subscriber') or {}
        sub.external_customer_id = str(subscriber.get('payer_id') or sub.external_customer_id or '')
        sub.started_at = sub.started_at or payment_time
        sub.current_period_start = payment_time
        sub.current_period_end = next_billing_time
        sub.renews_at = next_billing_time
        sub.cancelled_at = None
        sub.grace_ends_at = None
        sub.trial_ends_at = None
        sub.cancel_at_period_end = False
        sub.cancellation_reason = ''
        sub.last_payment_at = payment_time
        sub.failed_payment_count = 0
        sub.monthly_price = locked_tx.amount if locked_tx.billing_cycle == 'monthly' else (locked_tx.amount / Decimal('10')).quantize(Decimal('0.01'))
        sub.currency = locked_tx.currency
        sub.save()
        BillingInvoice.objects.update_or_create(
            transaction=locked_tx,
            defaults={
                'company': locked_tx.company,
                'subscription': sub,
                'number': f'INV-{payment_time.strftime("%Y%m%d")}-{locked_tx.reference[-10:]}',
                'plan': locked_tx.plan,
                'billing_cycle': locked_tx.billing_cycle,
                'amount': locked_tx.amount,
                'currency': locked_tx.currency,
                'status': 'paid',
                'paid_at': payment_time,
                'period_start': payment_time,
                'period_end': next_billing_time,
                'metadata': {'provider': 'paypal', 'provider_transaction_id': subscription_id},
            },
        )
    return True


def paypal_pause_recurring_billing(subscription_id, reason='Paused by company administrator'):
    """Pause PayPal renewals while preserving the customer's paid access locally.

    PayPal's ``suspend`` endpoint pauses a subscription immediately and can be
    reversed with ``activate``.  HRCloudPay keeps the already-paid period
    available, then its normal subscription gate restricts access at
    ``renews_at``.  Naming the operation after its provider-side effect avoids
    presenting it as a future-dated cancellation that PayPal has not scheduled.
    """
    subscription_id = str(subscription_id or '')
    if not subscription_id:
        raise RuntimeError('PayPal subscription ID is missing.')
    if len(subscription_id) > 150 or any(not (c.isalnum() or c == '-') for c in subscription_id):
        raise RuntimeError('Invalid PayPal subscription ID.')
    return _paypal_request(
        f'/v1/billing/subscriptions/{subscription_id}/suspend', 'POST',
        {'reason': str(reason or 'Recurring billing paused')[:128]},
        request_id=f'hcp-paypal-suspend-{uuid.uuid4().hex}',
    )


def paypal_reactivate_subscription(subscription_id):
    subscription_id = str(subscription_id or '')
    if not subscription_id:
        raise RuntimeError('PayPal subscription ID is missing.')
    if len(subscription_id) > 150 or any(not (c.isalnum() or c == '-') for c in subscription_id):
        raise RuntimeError('Invalid PayPal subscription ID.')
    return _paypal_request(
        f'/v1/billing/subscriptions/{subscription_id}/activate', 'POST',
        {'reason': 'Company administrator removed scheduled cancellation'},
        request_id=f'hcp-paypal-reactivate-{uuid.uuid4().hex}',
    )


def verify_paypal_webhook_signature(config, headers, event):
    webhook_id = clean_secret(decrypt_secret(config.webhook_secret)) if config.webhook_secret else ''
    if not webhook_id:
        return False
    paypal_headers = {
        'auth_algo': headers.get('PAYPAL-AUTH-ALGO') or '',
        'cert_url': headers.get('PAYPAL-CERT-URL') or '',
        'transmission_id': headers.get('PAYPAL-TRANSMISSION-ID') or '',
        'transmission_sig': headers.get('PAYPAL-TRANSMISSION-SIG') or '',
        'transmission_time': headers.get('PAYPAL-TRANSMISSION-TIME') or '',
    }
    if not all(paypal_headers.values()):
        return False
    response = _paypal_request('/v1/notifications/verify-webhook-signature', 'POST', {
        **paypal_headers,
        'webhook_id': webhook_id,
        'webhook_event': event,
    })
    return str(response.get('verification_status') or '').upper() == 'SUCCESS'


def _paypal_subscription_for_event(subscription_id):
    subscription_id = str(subscription_id or '')
    if not subscription_id:
        return None
    return Subscription.objects.filter(
        provider='paypal', external_subscription_id=subscription_id,
    ).select_related('company').first()


def _paypal_period_for_payment(sub, payment_time, provider_subscription):
    billing_info = (provider_subscription or {}).get('billing_info') or {}
    last_payment = billing_info.get('last_payment') or {}
    provider_last_payment_time = _paypal_parse_time(last_payment.get('time'))
    next_billing_time = _paypal_parse_time(billing_info.get('next_billing_time'))
    # Provider timestamps are authoritative when this webhook describes the
    # subscription's current last payment. Older, delayed events must not use a
    # later cycle's next_billing_time or move the company's period backwards.
    if (provider_last_payment_time and next_billing_time
            and abs((provider_last_payment_time - payment_time).total_seconds()) <= 3600
            and next_billing_time > payment_time):
        return payment_time, next_billing_time, True
    period = timedelta(days=30 if sub.billing_cycle == 'monthly' else 365)
    return payment_time, payment_time + period, False


def _paypal_link_initial_sale(tx, sale_id, payment_time):
    """Attach the initial sale ID to the checkout transaction without extending it twice."""
    metadata = tx.metadata if isinstance(tx.metadata, dict) else {}
    if metadata.get('paypal_initial_sale_id') == sale_id:
        return True
    initial_time = _paypal_parse_time(metadata.get('paypal_initial_payment_time')) or tx.paid_at
    if not initial_time or abs((initial_time - payment_time).total_seconds()) > 48 * 3600:
        return False
    if PaymentTransaction.objects.filter(provider='paypal', provider_transaction_id=sale_id).exclude(pk=tx.pk).exists():
        return True
    tx.provider_transaction_id = sale_id
    tx.metadata = {**metadata, 'paypal_subscription_id': metadata.get('paypal_subscription_id') or tx.subscription.external_subscription_id, 'paypal_initial_sale_id': sale_id}
    tx.save(update_fields=['provider_transaction_id', 'metadata', 'updated_at'])
    invoice = BillingInvoice.objects.filter(transaction=tx).first()
    if invoice:
        invoice.metadata = {**(invoice.metadata or {}), 'provider_transaction_id': sale_id}
        invoice.save(update_fields=['metadata'])
    return True


def _paypal_process_completed_sale(resource, event_id):
    sale_id = str((resource or {}).get('id') or '')
    subscription_id = str((resource or {}).get('billing_agreement_id') or (resource or {}).get('subscription_id') or '')
    if not sale_id or not subscription_id:
        return False
    payment_time = _paypal_parse_time((resource or {}).get('create_time')) or timezone.now()
    existing_sale = PaymentTransaction.objects.filter(provider='paypal', provider_transaction_id=sale_id).first()
    if existing_sale:
        return existing_sale.status == 'paid'

    initial_tx = PaymentTransaction.objects.filter(
        provider='paypal', provider_transaction_id=subscription_id,
    ).select_related('subscription', 'company').first()
    if initial_tx and initial_tx.status == 'pending':
        verified_subscription = paypal_verify_subscription(subscription_id)
        if not paypal_activate_from_verified_subscription(initial_tx, verified_subscription):
            return False
        initial_tx.refresh_from_db()
        return _paypal_link_initial_sale(initial_tx, sale_id, payment_time)
    if initial_tx and initial_tx.status == 'paid':
        if _paypal_link_initial_sale(initial_tx, sale_id, payment_time):
            return True

    sub = _paypal_subscription_for_event(subscription_id)
    if not sub:
        return False
    provider_subscription = paypal_verify_subscription(subscription_id)
    if str(provider_subscription.get('id') or '') != subscription_id:
        return False
    if str(provider_subscription.get('plan_id') or '') != str(sub.provider_plan_id or ''):
        return False
    if str(provider_subscription.get('status') or '').upper() not in ('ACTIVE', 'SUSPENDED', 'CANCELLED'):
        return False

    paid_amount, paid_currency = _paypal_amount_and_currency(resource)
    expected_amount = sub.monthly_price if sub.billing_cycle == 'monthly' else (sub.monthly_price * Decimal('10')).quantize(Decimal('0.01'))
    if paid_amount is None or paid_amount != expected_amount.quantize(Decimal('0.01')) or paid_currency != str(sub.currency or '').upper():
        return False

    with transaction.atomic():
        locked_sub = Subscription.objects.select_for_update().select_related('company').get(pk=sub.pk)
        existing_sale = PaymentTransaction.objects.select_for_update().filter(
            provider='paypal', provider_transaction_id=sale_id,
        ).first()
        if existing_sale:
            return existing_sale.status == 'paid'
        reference = f'HCP-PAYPAL-{sale_id}'
        tx = PaymentTransaction.objects.create(
            company=locked_sub.company,
            subscription=locked_sub,
            provider='paypal',
            reference=reference,
            provider_transaction_id=sale_id,
            plan=locked_sub.company.plan,
            billing_cycle=locked_sub.billing_cycle,
            amount=paid_amount,
            currency=paid_currency,
            status='paid',
            paid_at=payment_time,
            metadata={
                'recurring': True,
                'paypal_subscription_id': subscription_id,
                'paypal_event_id': event_id,
            },
        )
        period_start, period_end, authoritative = _paypal_period_for_payment(locked_sub, payment_time, provider_subscription)
        if not authoritative and locked_sub.last_payment_at and payment_time < locked_sub.last_payment_at:
            # The invoice remains recorded, but an older delayed event cannot
            # roll the active subscription period back.
            pass
        else:
            locked_sub.status = 'active'
            locked_sub.current_period_start = period_start
            locked_sub.current_period_end = period_end
            locked_sub.renews_at = period_end
            locked_sub.last_payment_at = payment_time
            locked_sub.grace_ends_at = None
            locked_sub.failed_payment_count = 0
            locked_sub.save(update_fields=[
                'status', 'current_period_start', 'current_period_end', 'renews_at',
                'last_payment_at', 'grace_ends_at', 'failed_payment_count', 'updated_at',
            ])
        BillingInvoice.objects.create(
            company=locked_sub.company,
            subscription=locked_sub,
            transaction=tx,
            number=f'INV-{payment_time.strftime("%Y%m%d")}-{reference[-10:]}',
            plan=locked_sub.company.plan,
            billing_cycle=locked_sub.billing_cycle,
            amount=paid_amount,
            currency=paid_currency,
            status='paid',
            paid_at=payment_time,
            period_start=period_start,
            period_end=period_end,
            metadata={'provider': 'paypal', 'provider_transaction_id': sale_id},
        )
    return True


def _paypal_mark_payment_failed(subscription_id, event_time=None):
    sub = _paypal_subscription_for_event(subscription_id)
    if not sub:
        pending = PaymentTransaction.objects.filter(
            provider='paypal', provider_transaction_id=subscription_id, status='pending',
        ).select_related('subscription').first()
        if pending:
            pending.status = 'failed'
            pending.save(update_fields=['status', 'updated_at'])
            return True
        return False
    failed_at = _paypal_parse_time(event_time)
    if failed_at and sub.last_payment_at and sub.last_payment_at >= failed_at:
        return True
    provider_data = paypal_verify_subscription(subscription_id)
    if str(provider_data.get('id') or '') != subscription_id:
        return False
    provider_status = str(provider_data.get('status') or '').upper()
    if provider_status in ('CANCELLED', 'EXPIRED'):
        return True
    billing_info = provider_data.get('billing_info') or {}
    last_payment = billing_info.get('last_payment') or {}
    provider_last_payment_at = _paypal_parse_time(last_payment.get('time'))
    if failed_at and provider_last_payment_at and provider_last_payment_at >= failed_at:
        return True
    if (not failed_at and sub.last_payment_at and provider_last_payment_at
            and provider_last_payment_at > sub.last_payment_at):
        return True
    sub.status = 'past_due'
    sub.grace_ends_at = timezone.now() + timedelta(days=7)
    sub.failed_payment_count = (sub.failed_payment_count or 0) + 1
    sub.save(update_fields=['status', 'grace_ends_at', 'failed_payment_count', 'updated_at'])
    return True


def _paypal_sync_subscription_status(subscription_id, event_type):
    sub = _paypal_subscription_for_event(subscription_id)
    if not sub:
        return False
    provider_data = paypal_verify_subscription(subscription_id)
    if str(provider_data.get('id') or '') != subscription_id:
        return False
    status = str(provider_data.get('status') or '').upper()
    if status == 'ACTIVE':
        # Do not activate an unpaid checkout from a status notification alone.
        if sub.status in ('active', 'past_due') and sub.provider == 'paypal':
            sub.status = 'active'
            sub.grace_ends_at = None
            sub.failed_payment_count = 0
            sub.save(update_fields=['status', 'grace_ends_at', 'failed_payment_count', 'updated_at'])
        return sub.status == 'active'
    if status == 'SUSPENDED':
        if sub.cancel_at_period_end:
            return True
        sub.status = 'past_due'
        sub.grace_ends_at = timezone.now() + timedelta(days=7)
        sub.save(update_fields=['status', 'grace_ends_at', 'updated_at'])
        return True
    if status in ('CANCELLED', 'EXPIRED'):
        sub.status = 'cancelled' if status == 'CANCELLED' else 'expired'
        sub.cancel_at_period_end = False
        sub.cancelled_at = sub.cancelled_at or timezone.now()
        sub.grace_ends_at = sub.current_period_end or sub.renews_at
        sub.save(update_fields=['status', 'cancel_at_period_end', 'cancelled_at', 'grace_ends_at', 'updated_at'])
        return True
    return False


def process_paypal_webhook_event(event_type, resource, event_id='', event_time=None):
    event_type = str(event_type or '').upper()
    resource = resource or {}
    if event_type == 'PAYMENT.SALE.COMPLETED':
        return _paypal_process_completed_sale(resource, event_id)
    if event_type == 'BILLING.SUBSCRIPTION.PAYMENT.FAILED':
        subscription_id = str(resource.get('billing_agreement_id') or resource.get('subscription_id') or resource.get('id') or '')
    else:
        subscription_id = str(resource.get('id') or resource.get('billing_agreement_id') or resource.get('subscription_id') or '')
    if event_type in ('BILLING.SUBSCRIPTION.ACTIVATED', 'BILLING.SUBSCRIPTION.RE-ACTIVATED'):
        pending = PaymentTransaction.objects.filter(
            provider='paypal', provider_transaction_id=subscription_id, status='pending',
        ).select_related('subscription').first()
        if pending:
            verified_subscription = paypal_verify_subscription(subscription_id)
            return paypal_activate_from_verified_subscription(pending, verified_subscription)
        return _paypal_sync_subscription_status(subscription_id, event_type)
    if event_type in ('BILLING.SUBSCRIPTION.PAYMENT.FAILED', 'BILLING.SUBSCRIPTION.SUSPENDED'):
        if event_type == 'BILLING.SUBSCRIPTION.SUSPENDED':
            sub = _paypal_subscription_for_event(subscription_id)
            if sub and sub.cancel_at_period_end:
                return True
        return _paypal_mark_payment_failed(subscription_id, event_time)
    if event_type == 'BILLING.SUBSCRIPTION.CANCELLED':
        return _paypal_sync_subscription_status(subscription_id, event_type)
    if event_type == 'BILLING.SUBSCRIPTION.EXPIRED':
        return _paypal_sync_subscription_status(subscription_id, event_type)
    return None
