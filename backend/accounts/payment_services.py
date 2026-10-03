import json
import urllib.error
import urllib.request
import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.conf import settings

from .billing import PLAN_PRICES
from .platform_models import PaymentProviderConfig, PaymentPlan, PaymentTransaction, Subscription, BillingInvoice
from .secrets import decrypt_secret

FLW_BASE = 'https://api.flutterwave.com/v3'


def _request(path, method='GET', payload=None, secret=''):
    data = None
    headers = {'Authorization': f'Bearer {secret}', 'Content-Type': 'application/json'}
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
    row = PaymentPlan.objects.filter(provider='flutterwave', plan=plan, billing_cycle=billing_cycle, currency=currency).first()
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
                provider='flutterwave', plan=plan, billing_cycle=billing_cycle, currency=currency,
                defaults={'external_plan_id': str(data['id']), 'amount': amount},
            )
    except Exception:
        row = PaymentPlan.objects.filter(provider='flutterwave', plan=plan, billing_cycle=billing_cycle, currency=currency).first()
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
    return config, decrypt_secret(config.encrypted_secret_key), PADDLE_API_BASE.get(config.environment or 'test', PADDLE_API_BASE['test'])


def _paddle_request(path, method='GET', payload=None, secret='', base_url=''):
    data = None
    headers = {'Authorization': f'Bearer {secret}', 'Content-Type': 'application/json'}
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
    row = PaymentPlan.objects.filter(provider='paddle', plan=plan, billing_cycle=billing_cycle, currency=currency).first()
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
                provider='paddle', plan=plan, billing_cycle=billing_cycle, currency=currency,
                defaults={'external_plan_id': price_id, 'amount': amount},
            )
    except Exception:
        if not PaymentPlan.objects.filter(provider='paddle', plan=plan, billing_cycle=billing_cycle, currency=currency).exists():
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
