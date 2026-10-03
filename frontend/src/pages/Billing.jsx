import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import ConfirmModal from '../components/ConfirmModal';
import { PLAN_ORDER, isDowngradeFrom, isUpgradeFrom, planLabel, sortPlans } from '../constants/plans';

// CompanyBillingCancelView answers HTTP 400 for these two states, so the cancel
// control is hidden for them (see backend/accounts/platform.py).
const CANCEL_BLOCKED_STATES = ['cancelled', 'expired'];

// Enterprise checkout is rejected server-side with "Enterprise plans require a
// sales agreement." The backend configures no dedicated sales inbox, so this
// points at the only contact address the project actually has:
// DEFAULT_FROM_EMAIL (backend/hrcloudpay/settings.py, set to this address in
// backend/.env and backend/.env.example).
const SALES_MAILTO = 'mailto:no-reply@hrcloudpay.com';

export default function Billing() {
  const [data, setData] = useState(null);
  const [plans, setPlans] = useState([]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(true);
  const [paying, setPaying] = useState('');
  const [billingCycle, setBillingCycle] = useState('monthly');
  const [invoices, setInvoices] = useState([]);
  const [actionLoading, setActionLoading] = useState(false);
  const [confirming, setConfirming] = useState('');
  const [searchParams] = useSearchParams();
  const requestedPlan = searchParams.get('plan');

  async function load() {
    setLoading(true);
    try {
      const [billing, available, invoiceRows] = await Promise.all([api.get('/auth/billing/'), api.get('/auth/billing/plans/'), api.get('/auth/billing/invoices/')]);
      setData(billing); setPlans(available); setInvoices(invoiceRows || []);
    } catch (err) { setError(err.message || 'Unable to load billing.'); }
    finally { setLoading(false); }
  }

  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (requestedPlan && plans.length && !paying && !searchParams.get('tx_ref') && requestedPlan !== data?.subscription?.plan) {
      const exists = plans.some((p) => p.id === requestedPlan && p.id !== 'enterprise');
      if (exists) checkout(requestedPlan);
    }
  }, [requestedPlan, plans.length, data?.subscription?.plan]); // eslint-disable-line react-hooks/exhaustive-deps

  async function verifyPayment(reference, transactionId) {
    setMessage('Payment completed. Verifying your subscription...');
    setError('');
    try {
      const result = await api.post('/auth/billing/verify/', { reference, transaction_id: transactionId || '' });
      setMessage(result.message || 'Subscription activated.');
      await load();
    } catch (err) { setError(err.message || 'Payment verification failed.'); }
  }

  useEffect(() => {
    const reference = searchParams.get('tx_ref');
    const transactionId = searchParams.get('transaction_id');
    if (reference && transactionId) { verifyPayment(reference, transactionId); return; }
    // Paddle's hosted checkout redirects back to /billing/success without
    // query parameters; the reference saved before the redirect lets us verify.
    const pending = sessionStorage.getItem('hrcloudpay.pending_paddle_reference');
    if (pending && !reference) {
      sessionStorage.removeItem('hrcloudpay.pending_paddle_reference');
      verifyPayment(pending, '');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  async function billingAction(path, body = {}) {
    setActionLoading(true); setError(''); setMessage('');
    try { const result = await api.post(path, body); setMessage(result.message || 'Billing settings updated.'); await load(); return true; }
    catch (err) { setError(err.message || 'Billing action failed.'); return false; }
    finally { setActionLoading(false); }
  }

  // Both endpoints only flip flags on the local Subscription row and never branch
  // on sub.provider, so they behave identically for every enabled provider
  // (paddle, flutterwave, manual). No provider argument is sent and none is read.
  // Cancel posts no body: CompanyBillingCancelView applies its own default reason.
  const cancelSubscription = () => billingAction('/auth/billing/cancel/');
  const reactivateSubscription = () => billingAction('/auth/billing/reactivate/');

  const closeConfirm = useCallback(() => setConfirming(''), []);

  function openCancelConfirm() { setError(''); setMessage(''); setConfirming('cancel'); }

  async function runConfirmedAction() {
    if (confirming === 'cancel') await cancelSubscription(); else await reactivateSubscription();
    setConfirming('');
  }

  async function checkout(plan) {
    if (plan === 'enterprise') return;
    setError(''); setMessage(''); setPaying(plan);
    try {
      const result = await api.post('/auth/billing/checkout/', { plan, billing_cycle: billingCycle, currency: 'USD' });
      if (result.provider === 'paddle' && result.reference) {
        sessionStorage.setItem('hrcloudpay.pending_paddle_reference', result.reference);
      }
      window.location.href = result.checkout_url;
    } catch (err) { setError(err.message || 'Unable to start checkout.'); setPaying(''); }
  }

  if (loading) return <div className="page"><div className="card">Loading billing...</div></div>;

  const sub = data?.subscription;
  const state = data?.state;
  const currentIndex = PLAN_ORDER.indexOf(sub?.plan);

  // Cancel is offered only while the backend will accept it, i.e. a subscription
  // exists, no cancellation is already pending, and the status is not terminal.
  const canCancel = !!sub && !sub.cancel_at_period_end && !CANCEL_BLOCKED_STATES.includes(sub.status);
  // Reactivate is only meaningful once a cancellation has actually been scheduled.
  const canReactivate = !!sub && !!sub.cancel_at_period_end;
  // `sub.plan` is a machine id ("professional"), so using it directly put
  // "Cancel the professional plan?" in front of users. Resolve the display name
  // from the plans the backend returned and fall back to the id only if the
  // plan is no longer offered.
  const planName = plans.find((p) => p.id === sub?.plan)?.name || sub?.plan || 'your plan';
  const periodEnd = sub?.renews_at ? new Date(sub.renews_at).toLocaleDateString() : '';
  const untilDate = periodEnd ? ` until ${periodEnd}` : '';
  const cancelConfirmMessage = `Your team keeps full access${untilDate}, when the current billing period ends. You can change your mind any time before then.`;

  return (
    <div className="page">
      <div className="page-header">
        <div><div className="eyebrow">BILLING</div><h1>Subscription & billing</h1><p>Choose a plan, pay securely, and keep HRCloudPay running without manual billing.</p></div>
        <Link className="btn btn-secondary" to="/pricing">View public pricing</Link>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {message && <div className="alert alert-success">{message}</div>}

      <div className="billing-summary-grid">
        <div className="card"><span className="kpi-label">Current plan</span><strong className="kpi-value">{sub?.plan || '—'}</strong><small>{sub?.status || 'No subscription'}</small></div>
        <div className="card"><span className="kpi-label">Billing</span><strong className="kpi-value">{sub ? `${sub.currency} ${sub.monthly_price}` : '—'}</strong><small>{sub?.billing_cycle || '—'}</small></div>
        <div className="card"><span className="kpi-label">Access</span><strong className="kpi-value">{state?.allowed ? 'Active' : 'Restricted'}</strong><small>{state?.reason || '—'}</small></div>
        <div className="card"><span className="kpi-label">Next renewal</span><strong className="kpi-value">{sub?.renews_at ? new Date(sub.renews_at).toLocaleDateString() : '—'}</strong><small>{sub?.provider || '—'}</small></div>
      </div>

      {sub?.cancel_at_period_end && <div className="billing-status-banner warning"><div><strong>Cancellation scheduled</strong><div>Your {planName} plan stays active{untilDate}. You can undo this any time before then.</div></div><button className="btn btn-primary" disabled={actionLoading} onClick={reactivateSubscription}>Keep my plan</button></div>}
      {state?.status === 'past_due' || state?.status === 'grace' ? <div className="billing-status-banner warning"><div><strong>Payment attention required</strong><div>{state?.reason || 'Your subscription needs payment attention.'}</div></div></div> : null}
      {data?.pending_reference && sub?.status !== 'active' ? <div className="billing-status-banner"><div><strong>Paddle payment pending</strong><div>Complete the Paddle checkout to activate your plan. Already paid? Refresh your subscription status below.</div></div><button className="btn btn-secondary" disabled={actionLoading || !!paying} onClick={() => verifyPayment(data.pending_reference, '')}>Check payment status</button></div> : null}

      <section className="billing-plans">
        <div className="section-head"><div><div className="eyebrow">UPGRADE OR RENEW</div><h2>Choose your plan</h2></div><div className="billing-cycle-toggle"><button className={billingCycle === 'monthly' ? 'active' : ''} onClick={() => setBillingCycle('monthly')}>Monthly</button><button className={billingCycle === 'annual' ? 'active' : ''} onClick={() => setBillingCycle('annual')}>Annual · Save 2 months</button></div></div>
        <div className="pricing-grid">
          {sortPlans(plans).map((plan) => {
            const current = plan.id === sub?.plan;
            const lower = isDowngradeFrom(sub?.plan, plan.id);
            return <div className={`pricing-card${plan.id === 'professional' || plan.id === 'scale' ? ' pricing-card-highlight' : ''}`} key={plan.id}>
              <h3>{plan.name}</h3>
              <div className="pricing-amount">{plan.id === 'enterprise' ? 'Custom' : `$${billingCycle === 'annual' ? plan.annual_price : plan.monthly_price}`}<span className="pricing-period">{plan.id === 'enterprise' ? '' : billingCycle === 'annual' ? '/year' : '/month'}</span></div>
              <p className="pricing-blurb">{plan.employee_limit ? `Up to ${plan.employee_limit} employees` : 'Unlimited employees'}</p>
              <ul className="pricing-features"><li>{plan.user_limit ? `${plan.user_limit} active users` : 'Unlimited users'}</li><li>HR + payroll operations</li><li>Secure payment & subscription management</li></ul>
              {plan.id === 'enterprise' ? <a className="btn btn-secondary" href={SALES_MAILTO}>Contact sales</a> : <button className="btn btn-primary" disabled={paying || current || lower} onClick={() => checkout(plan.id)}>{current ? 'Current plan' : lower ? 'Downgrade in portal' : paying === plan.id ? 'Opening checkout...' : 'Choose plan & pay'}</button>}
            </div>;
          })}
        </div>
      </section>

      <section className="card"><div className="section-head"><div><h2>Subscription controls</h2><p>Cancelling keeps your team working until the end of the current billing period.</p></div><div className="billing-actions">{canReactivate && <button className="btn btn-primary" disabled={actionLoading} onClick={reactivateSubscription}>Keep my plan</button>}{canCancel && <button className="btn billing-danger" disabled={actionLoading} onClick={openCancelConfirm}>Cancel subscription</button>}</div></div>{sub?.cancellation_reason && <small className="muted-text">Recorded cancellation reason: {sub.cancellation_reason}</small>}</section>

      <section className="card">
        <div className="section-head"><div><h2>Payment history</h2><p>Every checkout is recorded against your company subscription.</p></div></div>
        <div className="table-wrap"><table className="data-table"><thead><tr><th>Date</th><th>Reference</th><th>Plan</th><th>Amount</th><th>Status</th></tr></thead><tbody>
          {(data?.transactions || []).map((tx) => <tr key={tx.reference}><td>{new Date(tx.created_at).toLocaleString()}</td><td>{tx.reference}</td><td>{tx.plan}</td><td>{tx.currency} {tx.amount}</td><td>{tx.status}</td></tr>)}
        </tbody></table></div>
        {!data?.transactions?.length && <div className="empty-row">No payments yet.</div>}
      </section>

      <section className="card invoice-table"><div className="section-head"><div><h2>Invoices & receipts</h2><p>Paid subscription periods are recorded with an invoice number and payment reference.</p></div></div><div className="table-wrap"><table className="data-table"><thead><tr><th>Invoice</th><th>Period</th><th>Amount</th><th>Status</th><th>Reference</th></tr></thead><tbody>{invoices.map((inv) => <tr key={inv.number}><td>{inv.number}</td><td>{inv.period_start ? new Date(inv.period_start).toLocaleDateString() : '—'} – {inv.period_end ? new Date(inv.period_end).toLocaleDateString() : '—'}</td><td>{inv.currency} {inv.amount}</td><td>{inv.status}</td><td>{inv.reference || '—'}</td></tr>)}</tbody></table></div>{!invoices.length && <div className="empty-row">No invoices yet.</div>}</section>

      <ConfirmModal
        open={confirming === 'cancel'}
        title={`Cancel your ${planName} plan?`}
        message={cancelConfirmMessage}
        confirmLabel="Cancel subscription"
        cancelLabel="Keep my plan"
        danger
        busy={actionLoading}
        onConfirm={runConfirmedAction}
        onCancel={closeConfirm}
      />
    </div>
  );
}
