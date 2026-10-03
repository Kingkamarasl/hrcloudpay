import { useEffect, useState } from 'react';
import { api, downloadFile } from '../api/client';
import Icon from '../components/Icon';

function fmtDate(v) { return v ? new Date(`${v}T00:00:00`).toLocaleDateString() : '—'; }
function statusClass(s, isOverdue) { return s === 'closed' || s === 'submitted' || s === 'filed' ? 'badge-paid' : isOverdue || s === 'overdue' ? 'badge-overdue' : s === 'reviewed' || s === 'approved' || s === 'paid' || s === 'ready' ? 'badge-processed' : 'badge-draft'; }

// English names for every ISO 639 code the backend can send. Names are taken
// from the ISO 639-2 code list, which is where the codes in the registry came
// from in the first place.
//
// A code missing from this map would render as a bare two-letter string in the
// note below, so it is treated as a hard failure rather than falling back.
// `regional.tests_country_registry.LanguageDataTest` reads this map out of this
// file and asserts every code any pack declares is present here, which means a
// newly added country cannot introduce an unnamed language unnoticed.
const LANGUAGE_NAMES = {
  af: 'Afrikaans',
  am: 'Amharic',
  ar: 'Arabic',
  en: 'English',
  es: 'Spanish',
  fr: 'French',
  kab: 'Kabyle',
  mg: 'Malagasy',
  nd: 'North Ndebele',
  nr: 'South Ndebele',
  nso: 'Northern Sotho',
  ny: 'Chichewa',
  pt: 'Portuguese',
  rw: 'Kinyarwanda',
  sg: 'Sango',
  sn: 'Shona',
  so: 'Somali',
  ss: 'Swati',
  st: 'Southern Sotho',
  sw: 'Swahili',
  ti: 'Tigrinya',
  tn: 'Tswana',
  ts: 'Tsonga',
  ve: 'Venda',
  xh: 'Xhosa',
  zgh: 'Standard Moroccan Tamazight',
  zu: 'Zulu',
};

// Languages whose presence means the product's English output does not match
// the country's administrative language. Only these get a note: for the others
// the note would either be stating that English is official, which needs no
// warning, or it would raise a problem this build does not attempt to solve.
const NON_ENGLISH_OFFICIAL = new Set(['fr', 'pt', 'ar', 'kab', 'zgh']);

// The note says what is true and no more. HRCloudPay has no translation
// catalogs, no LocaleMiddleware and no gettext calls, so its interface and its
// generated reports are English everywhere - that much is verifiable and is
// what this states. It deliberately does NOT claim the filings themselves are
// in a particular language: Rwanda records French as official while English has
// been the language of instruction since 2008, and a pack that said "filings
// are in French" would be wrong there. It also does not warn about
// right-to-left layout for the ten Arabic-script countries, because that is a
// known gap rather than a resolved one.
function languageNote(languages) {
  const names = (languages || [])
    .filter((code) => NON_ENGLISH_OFFICIAL.has(code))
    .map((code) => LANGUAGE_NAMES[code])
    .filter(Boolean);
  if (!names.length) return null;
  const isPlural = names.length > 1;
  return (
    `${isPlural ? names.join(' and ') : names[0]} `
    + `${isPlural ? 'are official languages' : 'is an official language'} of your country. `
    + 'HRCloudPay\'s interface and the reports it generates are in English, so you '
    + 'will need to file with the authority in the statutory language yourself.'
  );
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function StatutoryCompliance() {
  const [dashboard, setDashboard] = useState(null);
  const [calendar, setCalendar] = useState(null);
  const [filings, setFilings] = useState([]);
  const [reports, setReports] = useState([]);
  const [packs, setPacks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [generating, setGenerating] = useState(false);
  const [period, setPeriod] = useState({ start: '', end: '' });
  const [paymentModal, setPaymentModal] = useState(null);
  const [paymentForm, setPaymentForm] = useState({ method: '', transaction_reference: '', receipt_reference: '' });
  const [submitModal, setSubmitModal] = useState(null);
  const [submitRef, setSubmitRef] = useState('');
  const [selected, setSelected] = useState([]);
  const [bulkReviewing, setBulkReviewing] = useState(false);

  function toggleSelect(id) {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  async function bulkReviewSelected() {
    if (!selected.length) { setError('Select at least one filing to review.'); return; }
    setBulkReviewing(true);
    setError('');
    try {
      const res = await api.post('/regional/filings/bulk-review/', { ids: selected });
      if (res.skipped?.length) setError(`Reviewed ${res.reviewed}; skipped ${res.skipped.length}.`);
      setSelected([]);
      await load();
    } catch (e) { setError(e.message); } finally { setBulkReviewing(false); }
  }

  async function load() {
    setLoading(true);
    setError('');
    try {
      const results = await Promise.allSettled([
        api.get('/regional/compliance-dashboard/?days=30'),
        api.get('/regional/filing-calendar/?days=120'),
        api.get('/regional/filings/'),
        api.get('/regional/statutory-reports/'),
        api.get('/regional/compliance-packs/'),
      ]);
      const [d, c, f, r, p] = results;
      if (d.status === 'fulfilled') setDashboard(d.value);
      if (c.status === 'fulfilled') setCalendar(c.value);
      if (f.status === 'fulfilled') setFilings(f.value || []);
      if (r.status === 'fulfilled') setReports(r.value?.reports || []);
      if (p.status === 'fulfilled') setPacks(p.value || []);
      const failed = results.find((x) => x.status === 'rejected');
      if (failed) setError(failed.reason?.message || 'Some compliance data failed to load.');
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { load(); }, []);

  async function generate(e) {
    e.preventDefault();
    setGenerating(true);
    setError('');
    try {
      await api.post('/regional/filings/generate/', { period_start: period.start, period_end: period.end });
      await load();
    } catch (e) { setError(e.message); } finally { setGenerating(false); }
  }

  async function downloadReport(code) {
    if (!period.start || !period.end) { setError('Select a payroll period first.'); return; }
    try {
      const r = await downloadFile(`/regional/statutory-reports/${code}/export/?period_start=${period.start}&period_end=${period.end}`);
      saveBlob(r.blob, `${code}-${period.end}.xlsx`);
    } catch (e) { setError(e.message); }
  }

  async function downloadCsv(id) {
    try {
      const r = await downloadFile(`/regional/filings/${id}/export/`);
      saveBlob(r.blob, `filing-${id}.csv`);
    } catch (e) { setError(e.message); }
  }

  async function reviewFiling(id) { try { await api.post(`/regional/filings/${id}/review/`, {}); await load(); } catch (e) { setError(e.message); } }
  async function approveFiling(id) { try { await api.post(`/regional/filings/${id}/approve/`, {}); await load(); } catch (e) { setError(e.message); } }

  function openPayment(filing) {
    setPaymentModal(filing);
    setPaymentForm({ method: '', transaction_reference: '', receipt_reference: '' });
  }

  async function confirmPayment(e) {
    e.preventDefault();
    if (!paymentModal) return;
    if (!paymentForm.method.trim() || !paymentForm.transaction_reference.trim()) {
      setError('Payment method and transaction reference are required.');
      return;
    }
    try {
      await api.post(`/regional/filings/${paymentModal.id}/payment/`, {
        amount: paymentModal.amount,
        method: paymentForm.method.trim(),
        transaction_reference: paymentForm.transaction_reference.trim(),
        receipt_reference: paymentForm.receipt_reference.trim(),
      });
      setPaymentModal(null);
      await load();
    } catch (e) { setError(e.message); }
  }

  function openSubmit(filing) {
    setSubmitModal(filing);
    setSubmitRef('');
  }

  async function confirmSubmit(e) {
    e.preventDefault();
    if (!submitModal || !submitRef.trim()) {
      setError('Submission reference is required.');
      return;
    }
    try {
      await api.post(`/regional/filings/${submitModal.id}/submit/`, { submission_reference: submitRef.trim() });
      setSubmitModal(null);
      await load();
    } catch (e) { setError(e.message); }
  }

  async function closeFiling(id) { try { await api.post(`/regional/filings/${id}/close/`, {}); await load(); } catch (e) { setError(e.message); } }

  if (loading) return <div className="page-loading">Loading statutory compliance…</div>;
  // Country name and window size come from the filing-calendar response rather
  // than a second copy of the country list kept in the frontend.
  const countryName = calendar?.country_name || calendar?.country || 'this country';
  // Built from the pack's own language data, not a per-country hardcoded note,
  // so the 39 countries added on 2026-10-02 are covered without 39 new strings
  // that could each drift from the backend.
  const languageWarning = languageNote(calendar?.official_languages);
  return (
    <div className="page-shell">
      <section className="page-header"><div><div className="eyebrow">STATUTORY COMPLIANCE</div><h1>Payroll filings & deadlines</h1><p>Country-aware filing calendar, payroll-period obligations and reviewable statutory exports.</p></div></section>
      {error && <div className="alert error-alert">{error}</div>}
      {dashboard?.configured && (
        <section className="dash-grid">
          {[[dashboard.summary?.open_filings, 'Open filings'], [dashboard.summary?.overdue_filings, 'Overdue'], [dashboard.summary?.filed_filings, 'Filed'], [dashboard.summary?.mismatches, 'Reconciliation mismatches']].map(([v, l]) => (
            <div className="metric-card" key={l}><div className="metric-value">{v ?? 0}</div><div className="metric-label">{l}</div></div>
          ))}
          <div className="metric-card"><div className="metric-value">{dashboard.summary?.open_amount ?? '0.00'}</div><div className="metric-label">Open statutory amount</div></div>
          <div className="metric-card"><div className="metric-value">{dashboard.summary?.overdue_amount ?? '0.00'}</div><div className="metric-label">Overdue amount</div></div>
        </section>
      )}
      <div className="dash-grid">
        <section className="panel">
          <div className="panel-head"><div><h2>Upcoming deadlines</h2><p>{calendar?.country || '—'} · next 120 days</p></div></div>
          {languageWarning && (
            <div className="alert alert-warning">
              <strong>Filings are not in English.</strong> {languageWarning}
            </div>
          )}
          {calendar?.filings?.length ? (
            <div className="activity-list">{calendar.filings.map((x, i) => (
              <div className="activity-row" key={`${x.rule_code}-${i}`}><div className="activity-icon"><Icon name="calendar" size={16} /></div><div><strong>{x.name}</strong><small>{x.authority} · {x.frequency} · due {fmtDate(x.due_date)}</small></div>{x.source_reference && <a className="text-link" href={x.source_reference} target="_blank" rel="noreferrer">Source</a>}</div>
            ))}</div>
          ) : calendar?.configured === false ? <div className="empty-state"><strong>No country set up</strong><p>Choose your country in Country setup to see the statutory deadlines that apply to it.</p></div>
          : calendar?.calendar_status === 'unverified' ? <div className="empty-state"><strong>No verified filing calendar for this country</strong><p>HRCloudPay has not verified {countryName} statutory filing deadlines yet, so this calendar is empty because the data is missing, not because you have nothing due. Statutory deadlines come from the revenue and social security authorities directly - track them at the source until they are added.</p></div>
          : <div className="empty-state"><strong>No deadlines in this window</strong><p>Deadlines exist for this country but none fall in the next {calendar?.days ?? 120} days. Widen the window on the API if you expected one.</p></div>}
        </section>
        <section className="panel">
          <div className="panel-head"><div><h2>Generate filing obligations</h2><p>Creates reviewable obligations for a completed payroll period.</p></div></div>
          <form className="form-panel" onSubmit={generate}>
            <div className="form-row">
              <div><label htmlFor="sp-start">Period start</label><input id="sp-start" type="date" required value={period.start} onChange={(e) => setPeriod({ ...period, start: e.target.value })} /></div>
              <div><label htmlFor="sp-end">Period end</label><input id="sp-end" type="date" required value={period.end} onChange={(e) => setPeriod({ ...period, end: e.target.value })} /></div>
            </div>
            <button className="btn btn-primary compact" disabled={generating}>{generating ? 'Generating…' : 'Generate obligations'}</button>
          </form>
        </section>
      </div>
      <section className="panel">
        <div className="panel-head"><div><div className="eyebrow">AUTHORITY REPORTS</div><h2>Country statutory reports</h2><p>Generate country-specific Excel schedules from the selected payroll period.</p></div></div>
        <div className="dash-grid" style={{ marginTop: 12 }}>{reports.map((r) => (
          <div className="panel" key={r.code}><div className="panel-head"><div><strong>{r.name}</strong><small>{r.authority} · {r.format.toUpperCase()}</small></div></div><button className="btn btn-secondary compact" onClick={() => downloadReport(r.code)}>Export Excel</button></div>
        ))}</div>
        {!reports.length && <div className="empty-state">No statutory reports are configured for this country.</div>}
      </section>
      <section className="panel">
        <div className="panel-head"><div><div className="eyebrow">COMPLIANCE PACKS</div><h2>Payroll compliance packs</h2><p>Approved and paid payroll runs are prepared as country-specific filing workspaces.</p></div></div>
        <div className="table-wrap"><table className="data-table"><thead><tr><th>Payroll period</th><th>Country</th><th>Payroll</th><th>Filings</th><th>Reports</th><th>Status</th><th>Actions</th></tr></thead><tbody>{packs.map((p) => (
          <tr key={p.id}><td>{fmtDate(p.period_start)} – {fmtDate(p.period_end)}</td><td>{p.country_code}</td><td>{p.payroll_status}</td><td>{p.filing_count}</td><td>{p.report_count}</td><td><span className={`badge ${p.status === 'submitted' ? 'badge-paid' : p.status === 'ready' ? 'badge-processed' : 'badge-draft'}`}>{p.status}</span></td><td className="table-actions"><button className="btn btn-secondary compact" onClick={async () => { try { const r = await downloadFile(`/regional/compliance-packs/${p.id}/export/`); saveBlob(r.blob, `hrcloudpay-compliance-pack-${p.country_code}-${p.period_end}.zip`); } catch (e) { setError(e.message); } }}>Download pack</button>{p.status === 'ready' && <button className="btn btn-primary compact" onClick={async () => { try { await api.post(`/regional/compliance-packs/${p.id}/submit/`, {}); await load(); } catch (e) { setError(e.message); } }}>Mark submitted</button>}</td></tr>
        ))}{!packs.length && <tr><td colSpan="7" className="empty-row">No compliance packs yet. Approve a completed payroll run to prepare one automatically.</td></tr>}</tbody></table></div>
      </section>
      {dashboard?.configured && (
        <section className="panel">
          <div className="panel-head"><div><div className="eyebrow">RECONCILIATION</div><h2>Payroll vs statutory obligations</h2><p>Every generated obligation is checked against the payroll run that produced it.</p></div></div>
          <div className="table-wrap"><table className="data-table"><thead><tr><th>Obligation</th><th>Period</th><th>Recorded</th><th>Expected</th><th>Variance</th><th>Status</th></tr></thead><tbody>{(dashboard.reconciliation || []).map((x) => (
            <tr key={x.filing_id}><td><strong>{x.name}</strong><small>{x.code}</small></td><td>{fmtDate(x.period_start)} – {fmtDate(x.period_end)}</td><td>{x.recorded_amount}</td><td>{x.expected_amount}</td><td>{x.variance}</td><td><span className={`badge ${x.status === 'matched' ? 'badge-paid' : 'badge-overdue'}`}>{x.status}</span></td></tr>
          ))}{!dashboard.reconciliation?.length && <tr><td colSpan="6" className="empty-row">No payroll-linked obligations to reconcile yet.</td></tr>}</tbody></table></div>
        </section>
      )}
      <section className="panel">
        <div className="panel-head"><div><div className="eyebrow">FILING REGISTER</div><h2>Generated statutory filings</h2><p>Review status, due dates and generic payroll exports before filing with the authority.</p></div><div><button className="btn btn-primary compact" onClick={bulkReviewSelected} disabled={bulkReviewing || !selected.length}>{bulkReviewing ? 'Reviewing…' : `Review selected (${selected.length})`}</button></div></div>
        <div className="table-wrap"><table className="data-table"><thead><tr><th><span className="sr-only">Select</span></th><th>Obligation</th><th>Period</th><th>Due</th><th>Amount</th><th>Status</th><th>Actions</th></tr></thead><tbody>{filings.map((f) => {
          const terminal = ['submitted', 'closed', 'filed'].includes(f.status);
          const selectable = !f.reviewed_at && !terminal;
          return (
            <tr key={f.id}><td>{selectable ? <input type="checkbox" aria-label={`Select filing ${f.id}`} checked={selected.includes(f.id)} onChange={() => toggleSelect(f.id)} /> : null}</td><td><strong>{f.rule_name}</strong><small>{f.authority}</small></td><td>{fmtDate(f.period_start)} – {fmtDate(f.period_end)}</td><td>{fmtDate(f.due_date)}</td><td>{f.amount}</td><td><span className={`badge ${statusClass(f.status, f.is_overdue)}`}>{f.is_overdue ? `${f.status} · overdue` : f.status}</span></td><td className="table-actions"><button className="btn btn-secondary compact" onClick={() => downloadCsv(f.id)}>CSV</button>{!f.reviewed_at && !terminal && <button className="btn btn-primary compact" onClick={() => reviewFiling(f.id)}>Review</button>}{f.status === 'reviewed' && !f.approved_at && <button className="btn btn-primary compact" onClick={() => approveFiling(f.id)}>Approve</button>}{f.status === 'approved' && !f.payment_record && <button className="btn btn-primary compact" onClick={() => openPayment(f)}>Record payment</button>}{f.status === 'paid' && f.payment_record && <button className="btn btn-primary compact" onClick={() => openSubmit(f)}>Submit</button>}{(f.status === 'submitted' || f.status === 'filed') && <button className="btn btn-secondary compact" onClick={() => closeFiling(f.id)}>Close</button>}</td></tr>
          );
        })}{!filings.length && <tr><td colSpan="7" className="empty-row">No filings generated yet.</td></tr>}</tbody></table></div>
        <div className="empty-state" style={{ marginTop: 16 }}><small>Country reports are structured for authority review and mapping. Exact portal-upload templates are only used where the current official schema has been verified.</small></div>
      </section>

      {paymentModal && (
        <div className="modal-overlay" role="dialog" aria-modal="true" onClick={() => setPaymentModal(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head"><h3>Record payment · {paymentModal.rule_name}</h3><button className="btn-close" aria-label="Close payment dialog" onClick={() => setPaymentModal(null)}>×</button></div>
            <form onSubmit={confirmPayment} className="form-panel">
              <p>Amount due: <strong>{paymentModal.amount}</strong> (must match exactly).</p>
              <div><label htmlFor="pay-method">Payment method</label><input id="pay-method" required value={paymentForm.method} onChange={(e) => setPaymentForm({ ...paymentForm, method: e.target.value })} placeholder="bank_transfer" /></div>
              <div><label htmlFor="pay-tx">Transaction reference</label><input id="pay-tx" required value={paymentForm.transaction_reference} onChange={(e) => setPaymentForm({ ...paymentForm, transaction_reference: e.target.value })} placeholder="PAY-..." /></div>
              <div><label htmlFor="pay-receipt">Receipt reference (optional)</label><input id="pay-receipt" value={paymentForm.receipt_reference} onChange={(e) => setPaymentForm({ ...paymentForm, receipt_reference: e.target.value })} placeholder="REC-..." /></div>
              <div className="form-action"><button type="submit" className="btn btn-primary compact">Confirm payment</button></div>
            </form>
          </div>
        </div>
      )}

      {submitModal && (
        <div className="modal-overlay" role="dialog" aria-modal="true" onClick={() => setSubmitModal(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head"><h3>Submit filing · {submitModal.rule_name}</h3><button className="btn-close" aria-label="Close submit dialog" onClick={() => setSubmitModal(null)}>×</button></div>
            <form onSubmit={confirmSubmit} className="form-panel">
              <div><label htmlFor="submit-ref">Authority submission reference</label><input id="submit-ref" required value={submitRef} onChange={(e) => setSubmitRef(e.target.value)} placeholder="AUTH-..." /></div>
              <div className="form-action"><button type="submit" className="btn btn-primary compact">Confirm submission</button></div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
