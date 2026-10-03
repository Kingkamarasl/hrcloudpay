import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import EmployeePicker from '../components/EmployeePicker';
import FeatureUnavailable from '../components/FeatureUnavailable';
import { useFeatures } from '../context/FeatureContext';

export default function LeaveAccrual() {
  const { isEnabled, loading: flagsLoading } = useFeatures();
  // Two independent flags, not one OR: with accruals on and encashment off the
  // page used to render the encashment form anyway, so the form was filled in
  // and thrown away on submit.
  const accrualsOn = isEnabled('leave_accruals');
  const encashmentOn = isEnabled('leave_encashment');

  const [policies, setPolicies] = useState([]);
  const [balances, setBalances] = useState([]);
  const [encashments, setEncashments] = useState([]);
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');
  const [polForm, setPolForm] = useState({ leave_type: 'annual', days_per_year: '21' });
  const [encForm, setEncForm] = useState({ employee_id: '', leave_type: 'annual', days: '1' });

  async function load() {
    // allSettled, not all: the encashment endpoint is gated by a different flag
    // from the other two, and its 403 used to reject the whole batch and blank
    // the accrual policy and balances too.
    const [p, b, e] = await Promise.allSettled([
      api.get('/leave/accrual-policies/'),
      api.get('/leave/balances/'),
      api.get('/leave/encashments/'),
    ]);
    if (p.status === 'fulfilled') setPolicies(p.value || []);
    if (b.status === 'fulfilled') setBalances(b.value || []);
    if (e.status === 'fulfilled') setEncashments(e.value || []);
  }
  useEffect(() => { load(); }, []);

  // A 403 is the flag being off, which the section note already explains.
  function reportError(err) {
    if (err?.status === 403 || err?.status === 401) return;
    setError(err?.message || 'Something went wrong');
  }

  async function savePolicy(ev) {
    ev.preventDefault();
    try {
      await api.post('/leave/accrual-policies/', polForm);
      setMsg('Policy saved'); load();
    } catch (err) { reportError(err); }
  }
  async function runAccrual() {
    try {
      const r = await api.post('/leave/accrue/', {});
      setMsg(`Accrued balances updated: ${r.updated_balances}`);
      load();
    } catch (err) { reportError(err); }
  }
  async function encash(ev) {
    ev.preventDefault();
    try {
      const r = await api.post('/leave/encashments/', { ...encForm, employee_id: Number(encForm.employee_id) });
      setMsg(`Encashment recorded: ${r.amount}`);
      load();
    } catch (err) { reportError(err); }
  }

  if (!flagsLoading && !accrualsOn && !encashmentOn) {
    return (
      <div className="workspace-page">
        <FeatureUnavailable
          featureKey="leave_accruals"
          title="Accruals and encashment"
          backTo="/leave"
          backLabel="Back to requests"
        />
      </div>
    );
  }
  return (
    <div className="workspace-page">
      <section className="welcome-row">
        <div>
          <div className="eyebrow">LEAVE</div>
          <h1>Accruals &amp; encashment</h1>
          <p>Configure annual entitlements, run monthly accruals, and cash out balances when allowed.</p>
        </div>
        <Link className="btn btn-secondary" to="/leave">Back to requests</Link>
      </section>
      {error && <div className="alert alert-error">{error}</div>}
      {msg && <div className="alert alert-success">{msg}</div>}

      <section className="panel form-panel">
        <h2>Accrual policy</h2>
        <form onSubmit={savePolicy} className="form-grid two">
          <div>
            <label>Leave type</label>
            <select value={polForm.leave_type} onChange={(e) => setPolForm({ ...polForm, leave_type: e.target.value })}>
              <option value="annual">Annual</option>
              <option value="sick">Sick</option>
              <option value="other">Other</option>
            </select>
          </div>
          <div><label>Days per year</label><input value={polForm.days_per_year} onChange={(e) => setPolForm({ ...polForm, days_per_year: e.target.value })} /></div>
          <div className="form-action">
            <button type="submit" className="btn btn-primary">Save policy</button>
            <button type="button" className="btn btn-secondary" onClick={runAccrual}>Run monthly accrual</button>
          </div>
        </form>
        <ul>{policies.map((p) => <li key={p.id}>{p.leave_type}: {p.days_per_year} days/year (~{p.monthly_accrual}/mo)</li>)}</ul>
      </section>

      <section className="panel table-panel">
        <h2>Balances</h2>
        <div className="table-wrap">
          <table className="modern-table">
            <thead><tr><th>Employee</th><th>Type</th><th>Days</th></tr></thead>
            <tbody>{balances.map((b, i) => <tr key={i}><td>{b.employee}</td><td>{b.leave_type}</td><td>{b.balance_days}</td></tr>)}</tbody>
          </table>
        </div>
      </section>

      <section className="panel form-panel">
        <h2>Encashment</h2>
        <form onSubmit={encash} className="form-grid two">
          <div>
            <label>Employee (ID no / code / name)</label>
            <EmployeePicker value={encForm.employee_id} required onChange={(id) => setEncForm({ ...encForm, employee_id: id })} />
          </div>
          <div><label>Days</label><input value={encForm.days} onChange={(e) => setEncForm({ ...encForm, days: e.target.value })} /></div>
          <div className="form-action"><button type="submit" className="btn btn-primary">Approve encashment</button></div>
        </form>
        <div className="table-wrap">
          <table className="modern-table">
            <thead><tr><th>Employee</th><th>Days</th><th>Amount</th><th>Status</th></tr></thead>
            <tbody>{encashments.map((e) => <tr key={e.id}><td>{e.employee}</td><td>{e.days}</td><td>{e.amount}</td><td>{e.status}</td></tr>)}</tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
