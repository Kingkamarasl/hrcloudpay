import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import EmployeePicker from '../components/EmployeePicker';
import FeatureUnavailable from '../components/FeatureUnavailable';
import { useFeatures } from '../context/FeatureContext';

export default function PayrollExtras() {
  const { isEnabled, loading: flagsLoading } = useFeatures();
  // Each section carries its own flag. This used to be a single OR across both,
  // so with overtime on and advances off the page still rendered the advances
  // form, and the user only discovered the difference by submitting it and
  // reading a 403.
  const overtimeOn = isEnabled('payroll_overtime');
  const advancesOn = isEnabled('payroll_salary_advances');

  const [entries, setEntries] = useState([]);
  const [advances, setAdvances] = useState([]);
  const [holidays, setHolidays] = useState([]);
  const [holForm, setHolForm] = useState({ date: '', name: '' });
  const [rules, setRules] = useState(null);
  const [error, setError] = useState('');
  const [otForm, setOtForm] = useState({ employee_id: '', work_date: '', hours: '2', day_type: 'weekday', notes: '' });
  const [advForm, setAdvForm] = useState({ employee_id: '', amount: '', installment_amount: '', reason: '' });

  // A 403 from these endpoints is the flag being off, which each section note
  // already states far more clearly than an error banner would. Anything else -
  // a 500, a dropped connection - is still worth showing.
  function reportError(err) {
    if (err?.status === 403 || err?.status === 401) return;
    setError(err?.message || 'Something went wrong');
  }

  async function load() {
    // Settled rather than all: these four endpoints are gated by two
    // independent flags, and one 403 used to reject the whole Promise.all and
    // blank the page - including the sections whose flags were on.
    const [ot, adv, rule, hol] = await Promise.allSettled([
      api.get('/payroll/overtime/entries/'),
      api.get('/payroll/advances/'),
      api.get('/payroll/overtime/rules/'),
      api.get('/payroll/holidays/'),
    ]);
    if (ot.status === 'fulfilled') setEntries(ot.value || []);
    if (adv.status === 'fulfilled') setAdvances(adv.value || []);
    if (rule.status === 'fulfilled') setRules(rule.value);
    if (hol.status === 'fulfilled' && Array.isArray(hol.value)) setHolidays(hol.value);
  }

  useEffect(() => { load(); }, []);

  async function saveRules(e) {
    e.preventDefault();
    try {
      const fd = new FormData(e.target);
      await api.put('/payroll/overtime/rules/', {
        weekday_multiplier: fd.get('weekday_multiplier'),
        weekend_multiplier: fd.get('weekend_multiplier'),
        holiday_multiplier: fd.get('holiday_multiplier'),
        standard_hours_per_month: fd.get('standard_hours_per_month'),
      });
      load();
    } catch (err) { reportError(err); }
  }

  async function addOt(e) {
    e.preventDefault();
    try {
      await api.post('/payroll/overtime/entries/', { ...otForm, employee_id: Number(otForm.employee_id) });
      setOtForm({ employee_id: '', work_date: '', hours: '2', day_type: 'weekday', notes: '' });
      load();
    } catch (err) { reportError(err); }
  }

  async function addAdv(e) {
    e.preventDefault();
    try {
      await api.post('/payroll/advances/', {
        ...advForm,
        employee_id: Number(advForm.employee_id),
        amount: advForm.amount,
        installment_amount: advForm.installment_amount || advForm.amount,
      });
      setAdvForm({ employee_id: '', amount: '', installment_amount: '', reason: '' });
      load();
    } catch (err) { reportError(err); }
  }

  async function addHoliday(e) {
    e.preventDefault();
    try {
      await api.post('/payroll/holidays/', holForm);
      setHolForm({ date: '', name: '' });
      load();
    } catch (err) { reportError(err); }
  }

  const errorBanner = error ? <div className="alert alert-error">{error}</div> : null;

  const header = (
    <div className="page-header">
      <div>
        <div className="eyebrow">PAYROLL</div>
        <h1>Overtime &amp; salary advances</h1>
        <p>Record overtime by labour-rule day type and salary advances recovered on the next payroll runs.</p>
      </div>
      <Link className="btn btn-secondary" to="/payroll">Back to runs</Link>
    </div>
  );

  if (!flagsLoading && !overtimeOn && !advancesOn) {
    return (
      <div className="page">
        {header}
        <FeatureUnavailable
          featureKey="payroll_overtime"
          title="Overtime &amp; salary advances"
          backTo="/payroll"
          backLabel="Back to runs"
        />
      </div>
    );
  }

  return (
    <div className="page">
      {header}
      {errorBanner}

      {overtimeOn ? (
        <>
          <div className="card" style={{ marginBottom: '1.25rem' }}>
            <h3>Overtime rules (multipliers)</h3>
            {rules && (
              <form onSubmit={saveRules} className="form-row" style={{ flexWrap: 'wrap', gap: '0.75rem' }}>
                <label>Weekday <input name="weekday_multiplier" defaultValue={rules.weekday_multiplier} /></label>
                <label>Weekend <input name="weekend_multiplier" defaultValue={rules.weekend_multiplier} /></label>
                <label>Holiday <input name="holiday_multiplier" defaultValue={rules.holiday_multiplier} /></label>
                <label>Hours / month <input name="standard_hours_per_month" defaultValue={rules.standard_hours_per_month} /></label>
                <button className="btn btn-primary compact" type="submit">Save rules</button>
              </form>
            )}
          </div>

          <div className="card" style={{ marginBottom: '1.25rem' }}>
            <h3>Log overtime</h3>
            <form onSubmit={addOt} className="form-row" style={{ flexWrap: 'wrap', gap: '0.75rem' }}>
              <label>Employee (ID no / code / name)
                <EmployeePicker value={otForm.employee_id} required onChange={(id) => setOtForm({ ...otForm, employee_id: id })} />
              </label>
              <label>Date <input type="date" value={otForm.work_date} onChange={(e) => setOtForm({ ...otForm, work_date: e.target.value })} required /></label>
              <label>Hours <input value={otForm.hours} onChange={(e) => setOtForm({ ...otForm, hours: e.target.value })} /></label>
              <label>Day type
                <select value={otForm.day_type} onChange={(e) => setOtForm({ ...otForm, day_type: e.target.value })}>
                  <option value="weekday">Weekday</option>
                  <option value="weekend">Weekend</option>
                  <option value="holiday">Holiday</option>
                </select>
              </label>
              <button className="btn btn-primary compact" type="submit">Add</button>
            </form>
            <div className="table-wrap" style={{ marginTop: '1rem' }}>
              <table className="modern-table">
                <thead><tr><th>Employee</th><th>Date</th><th>Hours</th><th>Type</th><th>Amount</th><th>Run</th></tr></thead>
                <tbody>
                  {entries.map((e) => (
                    <tr key={e.id}><td>{e.employee}</td><td>{e.work_date}</td><td>{e.hours}</td><td>{e.day_type}</td><td>{e.amount}</td><td>{e.payroll_run_id || 'â€”'}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card" style={{ marginBottom: '1.25rem' }}>
            <h3>Public holidays</h3>
            <p style={{ fontSize: '0.9rem', color: 'var(--text-muted)' }}>Used to auto-classify overtime as holiday rates when day type is left blank.</p>
            <form onSubmit={addHoliday} className="form-row" style={{ flexWrap: 'wrap', gap: '0.75rem' }}>
              <label>Date <input type="date" value={holForm.date} onChange={(e) => setHolForm({ ...holForm, date: e.target.value })} required /></label>
              <label>Name <input value={holForm.name} onChange={(e) => setHolForm({ ...holForm, name: e.target.value })} required /></label>
              <button className="btn btn-primary compact" type="submit">Add holiday</button>
            </form>
            <ul>{holidays.map((h) => <li key={h.id}>{h.date} â€” {h.name}</li>)}</ul>
          </div>
        </>
      ) : (
        <FeatureUnavailable
          featureKey="payroll_overtime"
          title="Overtime"
          backTo="/payroll"
          backLabel="Back to runs"
        />
      )}

      {advancesOn ? (
        <div className="card">
          <h3>Salary advances</h3>
          <form onSubmit={addAdv} className="form-row" style={{ flexWrap: 'wrap', gap: '0.75rem' }}>
            <label>Employee (ID no / code / name)
              <EmployeePicker value={advForm.employee_id} required onChange={(id) => setAdvForm({ ...advForm, employee_id: id })} />
            </label>
            <label>Amount <input value={advForm.amount} onChange={(e) => setAdvForm({ ...advForm, amount: e.target.value })} required /></label>
            <label>Installment / run <input value={advForm.installment_amount} onChange={(e) => setAdvForm({ ...advForm, installment_amount: e.target.value })} placeholder="Same as amount" /></label>
            <label>Reason <input value={advForm.reason} onChange={(e) => setAdvForm({ ...advForm, reason: e.target.value })} /></label>
            <button className="btn btn-primary compact" type="submit">Grant advance</button>
          </form>
          <div className="table-wrap" style={{ marginTop: '1rem' }}>
            <table className="modern-table">
              <thead><tr><th>Employee</th><th>Amount</th><th>Remaining</th><th>Installment</th><th>Status</th></tr></thead>
              <tbody>
                {advances.map((a) => (
                  <tr key={a.id}><td>{a.employee}</td><td>{a.amount}</td><td>{a.remaining}</td><td>{a.installment_amount}</td><td>{a.status}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <FeatureUnavailable
          featureKey="payroll_salary_advances"
          title="Salary advances"
          backTo="/payroll"
          backLabel="Back to runs"
        />
      )}
    </div>
  );
}
