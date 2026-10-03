# Milestone 54 — Production Billing & Subscriptions

## Goal

Turn the existing billing foundation into a production-oriented SaaS subscription workflow while keeping payment-provider credentials under Platform Admin control.

## Delivered

- Subscription lifecycle metadata: current billing period, renewal date, cancellation-at-period-end, cancellation reason, last payment, and failed-payment count.
- Company billing controls for owners/admins: schedule cancellation and reactivate before renewal.
- Centralized provider configuration remains Platform Admin-only.
- Flutterwave checkout and server-side transaction verification remain the source of truth for paid activation.
- Payment webhooks remain signature-verified and idempotent through `PaymentEvent`.
- Failed recurring charges move subscriptions to `past_due` and start the configured grace period.
- Successful payments reset failed-payment counters and update the current billing period.
- Paid subscription transactions create immutable billing invoice records with invoice numbers and payment references.
- Company billing UI now shows cancellation state, payment attention, subscription controls, payment history, and invoices/receipts metadata.
- Uniqueness and tenant ownership remain enforced by the database and company-scoped querysets.

## API additions

- `POST /api/auth/billing/cancel/`
- `POST /api/auth/billing/reactivate/`
- `GET /api/auth/billing/invoices/`

## Important provider behavior

The current cancellation control records a customer cancellation intent at period end. Provider-specific subscription cancellation APIs should be added only when the corresponding provider's production contract and webhook lifecycle are verified. This avoids falsely claiming that an external recurring subscription has been cancelled when only the HRCloudPay state has changed.

## Platform Admin

Payment credentials, webhook secrets, provider environment, and provider enable/disable state continue to be managed centrally. Company users never receive provider secrets.

## Migration

Run:

```bash
cd backend
python manage.py migrate
```

## Validation

Run backend compilation/checks and the frontend production build in the normal development environment:

```bash
python -m compileall -q backend/accounts
python manage.py check
cd ../frontend
npm ci
npm run build
```
