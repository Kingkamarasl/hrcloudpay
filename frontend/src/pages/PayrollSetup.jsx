import { useEffect, useState } from 'react';
import { api } from '../api/client';

const emptyBracket = () => ({ min_amount: '', max_amount: '', rate: '' });
const emptyContribution = () => ({ name: '', is_percentage: true, employee_rate: '', employer_rate: '' });

export default function PayrollSetup() {
  const [currency, setCurrency] = useState('USD');
  const [payFrequency, setPayFrequency] = useState('monthly');
  const [taxEnabled, setTaxEnabled] = useState(true);
  const [brackets, setBrackets] = useState([emptyBracket()]);
  const [contributions, setContributions] = useState([emptyContribution()]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    api
      .get('/payroll/config/')
      .then((data) => {
        setCurrency(data.currency);
        setPayFrequency(data.pay_frequency);
        setTaxEnabled(data.tax_calculation_enabled);
        if (data.tax_brackets?.length) setBrackets(data.tax_brackets);
        if (data.contributions?.length) setContributions(data.contributions);
      })
      .catch(() => {
        // no config yet - that's fine, this IS the onboarding form
      })
      .finally(() => setLoading(false));
  }, []);

  function updateBracket(index, field, value) {
    setBrackets((rows) => rows.map((row, i) => (i === index ? { ...row, [field]: value } : row)));
  }

  function updateContribution(index, field, value) {
    setContributions((rows) => rows.map((row, i) => (i === index ? { ...row, [field]: value } : row)));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setMessage('');
    setSaving(true);
    try {
      const payload = {
        currency,
        pay_frequency: payFrequency,
        tax_calculation_enabled: taxEnabled,
        tax_brackets: brackets
          .filter((b) => b.min_amount !== '' && b.rate !== '')
          .map((b) => ({
            min_amount: b.min_amount,
            max_amount: b.max_amount === '' ? null : b.max_amount,
            rate: b.rate,
          })),
        contributions: contributions
          .filter((c) => c.name.trim() !== '')
          .map((c) => ({
            name: c.name,
            is_percentage: c.is_percentage,
            employee_rate: c.employee_rate || 0,
            employer_rate: c.employer_rate || 0,
          })),
      };
      await api.post('/payroll/config/', payload);
      setMessage('Payroll settings saved. You can now run payroll for your employees.');
    } catch (err) {
      setError(err.message || 'Failed to save payroll settings');
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <p>Loading payroll setup...</p>;

  return (
    <div>
      <h1>Payroll Setup</h1>
      <p className="page-subtitle">
        Since tax and deduction rules differ by country, tell us how your business handles payroll
        and we'll apply it automatically whenever you run payroll.
      </p>

      {error && <div className="alert alert-error">{error}</div>}
      {message && <div className="alert alert-success">{message}</div>}

      <form onSubmit={handleSubmit} className="card">
        <h2>General</h2>
        <div className="form-row">
          <div>
            <label>Currency code</label>
            <input value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} placeholder="e.g. GNF, NGN, KES, GHS" required />
          </div>
          <div>
            <label>Pay frequency</label>
            <select value={payFrequency} onChange={(e) => setPayFrequency(e.target.value)}>
              <option value="monthly">Monthly</option>
              <option value="biweekly">Bi-weekly</option>
              <option value="weekly">Weekly</option>
            </select>
          </div>
        </div>
        <label className="checkbox-label">
          <input type="checkbox" checked={taxEnabled} onChange={(e) => setTaxEnabled(e.target.checked)} />
          Apply income tax calculation
        </label>

        <h2>Income tax brackets</h2>
        <p className="hint">Add each bracket of your country's progressive income tax. Leave the top bracket's "up to" blank for open-ended.</p>
        {brackets.map((bracket, i) => (
          <div className="form-row" key={i}>
            <div>
              <label>From</label>
              <input
                type="number"
                value={bracket.min_amount}
                onChange={(e) => updateBracket(i, 'min_amount', e.target.value)}
              />
            </div>
            <div>
              <label>Up to (blank = no limit)</label>
              <input
                type="number"
                value={bracket.max_amount ?? ''}
                onChange={(e) => updateBracket(i, 'max_amount', e.target.value)}
              />
            </div>
            <div>
              <label>Rate (%)</label>
              <input
                type="number"
                step="0.01"
                value={bracket.rate}
                onChange={(e) => updateBracket(i, 'rate', e.target.value)}
              />
            </div>
          </div>
        ))}
        <button type="button" className="btn-link" onClick={() => setBrackets((b) => [...b, emptyBracket()])}>
          + Add another bracket
        </button>

        <h2>Statutory contributions</h2>
        <p className="hint">e.g. social security, pension, health insurance - whatever your country requires.</p>
        {contributions.map((c, i) => (
          <div className="form-row" key={i}>
            <div>
              <label>Name</label>
              <input value={c.name} onChange={(e) => updateContribution(i, 'name', e.target.value)} placeholder="e.g. Social Security" />
            </div>
            <div>
              <label>Type</label>
              <select
                value={c.is_percentage ? 'percentage' : 'flat'}
                onChange={(e) => updateContribution(i, 'is_percentage', e.target.value === 'percentage')}
              >
                <option value="percentage">% of gross salary</option>
                <option value="flat">Flat amount</option>
              </select>
            </div>
            <div>
              <label>Employee share</label>
              <input type="number" step="0.01" value={c.employee_rate} onChange={(e) => updateContribution(i, 'employee_rate', e.target.value)} />
            </div>
            <div>
              <label>Employer share</label>
              <input type="number" step="0.01" value={c.employer_rate} onChange={(e) => updateContribution(i, 'employer_rate', e.target.value)} />
            </div>
          </div>
        ))}
        <button type="button" className="btn-link" onClick={() => setContributions((c) => [...c, emptyContribution()])}>
          + Add another contribution
        </button>

        <button className="btn btn-primary" type="submit" disabled={saving} style={{ marginTop: '1.5rem' }}>
          {saving ? 'Saving...' : 'Save payroll settings'}
        </button>
      </form>
    </div>
  );
}
