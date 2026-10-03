import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, downloadFile } from '../api/client';
import { withStepUp } from '../api/stepUp';
import Icon from '../components/Icon';
import { useFeatures } from '../context/FeatureContext';
import { money, sumMoney } from '../utils/money';

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function Payroll() {
  const { isEnabled } = useFeatures();
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [periodStart, setPeriodStart] = useState('');
  const [periodEnd, setPeriodEnd] = useState('');
  const [error, setError] = useState('');
  const [msg, setMsg] = useState('');
  const [processingId, setProcessingId] = useState(null);
  const [expandedRun, setExpandedRun] = useState(null);
  const [paymentReference, setPaymentReference] = useState('');
  const [compareA, setCompareA] = useState('');
  const [compareB, setCompareB] = useState('');
  const [compareResult, setCompareResult] = useState(null);
  const [payslipFilter, setPayslipFilter] = useState('');
  const [approvingId, setApprovingId] = useState(null);
  const [pendingGaps, setPendingGaps] = useState(null);

  function load() {
    setLoading(true);
    api.get('/payroll/runs/')
      .then((data) => setRuns(data.results ?? data))
      .catch((err) => setError(err.message || 'Failed to load payroll runs.'))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  const overview = useMemo(() => {
    const slips = runs.flatMap((r) => r.payslips || []);
    return {
      runs: runs.length,
      active: runs.filter((r) => r.status === 'processed' || r.status === 'approved').length,
      paid: runs.filter((r) => r.status === 'paid').length,
      net: sumMoney(slips, ['net_salary']),
    };
  }, [runs]);

  async function createRun(e) {
    e.preventDefault(); setError('');
    try {
      await api.post('/payroll/runs/', { period_start: periodStart, period_end: periodEnd });
      setPeriodStart(''); setPeriodEnd(''); load();
    } catch (err) { setError(err.message || 'Failed to create payroll run.'); }
  }
  async function processRun(id) {
    setError(''); setProcessingId(id);
    try { await api.post(`/payroll/runs/${id}/process/`, {}); load(); }
    catch (err) { setError(err.message || 'Failed to process payroll.'); }
    finally { setProcessingId(null); }
  }
  // A run can be calculated but not trustworthy: statutory income tax may have
  // been impossible to apply, in which case the backend refuses approval with a
  // 409 and this modal is the only way forward. Confirming is a deliberate act,
  // which is why the copy names the country and the date rather than saying
  // "are you sure?".
  function GapAcknowledgeModal({ gaps, run, onCancel, onConfirm, busy }) {
    return (
      <div className="modal-backdrop" role="dialog" aria-modal="true">
        <div className="modal-card">
          <h3>Approve payroll with unverified statutory tax?</h3>
          <p className="modal-note">
            This payroll for {run.period_start} to {run.period_end} could not have
            statutory income tax applied. The tax figures below came from this
            payroll's own tax brackets and have not been checked against the
            {gaps.map((g) => ` ${g.country_name}`).join(', ')} tax rules in force on {gaps[0].as_of}.
          </p>
          <ul className="gap-list">
            {gaps.map((g) => <li key={`${g.code}-${g.as_of}`}>{g.message}</li>)}
          </ul>
          <p className="modal-note">
            Approving means accepting responsibility for the tax figures as
            calculated. The acknowledgement, with your name and the time, is
            written to the audit log.
          </p>
          <div className="modal-actions">
            <button className="btn btn-secondary" onClick={onCancel} disabled={busy}>Cancel</button>
            <button className="btn btn-danger" onClick={onConfirm} disabled={busy}>
              {busy ? 'Approving…' : 'Approve and acknowledge'}
            </button>
          </div>
        </div>
      </div>
    );
  }

  async function approveRun(id, acknowledge = false) {
    setError(''); setApprovingId(id);
    // Approving a run moves real money, so the backend requires a fresh MFA
    // challenge; withStepUp prompts for the code and replays the request.
    //
    // `acknowledge` carries the explicit sign-off for a run whose statutory tax
    // could not be verified. It is never set implicitly: the user has to have
    // read the warning and confirmed it, because this is the record that a
    // person accepted an unverified tax result on the company's behalf.
    try {
      const body = acknowledge ? { acknowledge_compliance_gaps: 'true' } : {};
      await withStepUp(() => api.post(`/payroll/runs/${id}/approve/`, body));
      setPendingGaps(null); load();
    }
    catch (err) {
      // The backend refuses approval while statutory tax is unverified. Rather
      // than showing "Failed to approve payroll", surface the actual finding
      // and put the acknowledgement in front of the user.
      const data = err.data;
      if (err.status === 409 && data && data.compliance_gaps) {
        setPendingGaps({ runId: id, run: runs.find((r) => r.id === id), gaps: data.compliance_gaps });
      } else {
        setError(err.message || 'Failed to approve payroll.');
      }
    }
    finally { setApprovingId(null); }
  }
  async function payRun(id) {
    setError('');
    try {
      await withStepUp(() => api.post(`/payroll/runs/${id}/pay/`, { payment_method: 'bank_transfer', payment_reference: paymentReference }));
      setPaymentReference(''); load();
    } catch (err) { setError(err.message || 'Failed to record payment.'); }
  }
  async function downloadPayslip(id, copy = 'employee') {
    setError('');
    try {
      const { blob } = await downloadFile(`/payroll/payslips/${id}/?download=pdf&copy=${copy}`);
      saveBlob(blob, `payslip-${id}-${copy}.pdf`);
    } catch (err) {
      setError(err.message || 'Could not download payslip.');
    }
  }
  async function exportPayroll() {
    setError('');
    try {
      const { blob } = await downloadFile('/payroll/export/');
      saveBlob(blob, 'hrcloudpay-payroll.csv');
    } catch (err) {
      setError(err.message || 'Payroll export failed.');
    }
  }

  async function emailPayslips(id) {
    setMsg(''); setError('');
    try {
      const res = await api.post(`/payroll/runs/${id}/email-payslips/`, {});
      const failNote = res.failed?.length ? ` Failed: ${res.failed.map((f) => f.employee).join(', ')}` : '';
      setMsg(`Emailed ${res.sent} payslip(s).${failNote}`);
    } catch (err) { setError(err.message || 'Email failed'); }
  }

  async function downloadBankFile(id) {
    setError('');
    try {
      const { blob } = await downloadFile(`/payroll/runs/${id}/bank-file/`);
      saveBlob(blob, `bank-transfer-run-${id}.csv`);
    } catch (err) { setError(err.message); }
  }

  async function comparePrevious(runId) {
    setCompareResult(null); setError('');
    try {
      const res = await api.get(`/payroll/compare/?previous=1&run_b=${runId}`);
      setCompareResult(res);
      setCompareA(String(res.run_a.run_id));
      setCompareB(String(res.run_b.run_id));
    } catch (err) { setError(err.message || 'Compare failed'); }
  }

  async function runCompare(e) {
    e.preventDefault();
    setCompareResult(null); setError('');
    try {
      const res = await api.get(`/payroll/compare/?run_a=${compareA}&run_b=${compareB}`);
      setCompareResult(res);
    } catch (err) { setError(err.message || 'Compare failed'); }
  }

  return (
    <div className="workspace-page">
      <section className="welcome-row">
        <div>
          <div className="eyebrow">PAYROLL CENTER</div>
          <h1>Payroll runs</h1>
          <p>One-click runs, payslip email, bank transfer file, and period comparison.</p>
        </div>
        <div className="dash-actions">
          <Link to="/payroll-dashboard" className="btn btn-secondary">View analytics</Link>
          {(isEnabled('payroll_overtime') || isEnabled('payroll_salary_advances')) && <Link to="/payroll-extras" className="btn btn-secondary">Overtime &amp; advances</Link>}
          <button className="btn btn-secondary" onClick={exportPayroll}><Icon name="file" size={15} />Export CSV</button>
        </div>
      </section>
      {error && <div className="alert alert-error">{error}</div>}
      {msg && <div className="alert alert-success">{msg}</div>}

      <div className="dash-stats payroll-kpis">
        <div className="dash-stat"><div className="stat-icon"><Icon name="wallet" /></div><div className="stat-copy"><span>Payroll runs</span><strong>{loading ? '—' : overview.runs}</strong><small>All periods</small></div></div>
        <div className="dash-stat"><div className="stat-icon"><Icon name="clock" /></div><div className="stat-copy"><span>In workflow</span><strong>{loading ? '—' : overview.active}</strong><small>Processed or approved</small></div></div>
        <div className="dash-stat"><div className="stat-icon"><Icon name="trend" /></div><div className="stat-copy"><span>Paid runs</span><strong>{loading ? '—' : overview.paid}</strong><small>Completed payments</small></div></div>
        <div className="dash-stat"><div className="stat-icon"><Icon name="wallet" /></div><div className="stat-copy"><span>Net represented</span><strong>{loading ? '—' : money(overview.net)}</strong><small>Across visible payslips</small></div></div>
      </div>

      <section className="panel form-panel">
        <div className="panel-head"><div><h2>Create payroll run</h2><p>Define the pay period, then process in one click.</p></div></div>
        <form onSubmit={createRun}>
          <div className="form-grid two">
            <div><label>Period start</label><input type="date" value={periodStart} onChange={(e) => setPeriodStart(e.target.value)} required /></div>
            <div><label>Period end</label><input type="date" value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} required /></div>
            <div className="form-action"><button className="btn btn-primary" type="submit"><Icon name="wallet" size={15} />Create payroll run</button></div>
          </div>
        </form>
        <div className="helper-callout">
          <Icon name="settings" size={15} />
          <span>Payroll periods are unique per company. Configure your country rules before processing the first run.</span>
          <Link to="/payroll-setup">Open payroll settings <Icon name="arrow" size={13} /></Link>
        </div>
      </section>

      {isEnabled('payroll_compare_runs') && <section className="panel form-panel">
        <div className="panel-head"><div><h2>Compare periods</h2><p>Pick two run IDs to see net pay deltas by employee.</p></div></div>
        <form onSubmit={runCompare} className="form-grid two">
          <div><label>Run A ID</label><input value={compareA} onChange={(e) => setCompareA(e.target.value)} placeholder="e.g. 1" required /></div>
          <div><label>Run B ID</label><input value={compareB} onChange={(e) => setCompareB(e.target.value)} placeholder="e.g. 2" required /></div>
          <div className="form-action"><button type="submit" className="btn btn-secondary">Compare</button></div>
        </form>
        {compareResult && (
          <div className="table-wrap" style={{ marginTop: '1rem' }}>
            <p style={{ fontSize: '0.9rem' }}>
              <strong>A</strong> {compareResult.run_a.period_start} → {compareResult.run_a.period_end} net {money(compareResult.run_a.net)}
              {' · '}
              <strong>B</strong> {compareResult.run_b.period_start} → {compareResult.run_b.period_end} net {money(compareResult.run_b.net)}
            </p>
            <table className="modern-table">
              <thead><tr><th>Employee</th><th>Net A</th><th>Net B</th><th>Δ</th></tr></thead>
              <tbody>
                {compareResult.employees.slice(0, 25).map((r) => (
                  <tr key={r.employee}><td>{r.employee}</td><td>{money(r.net_a)}</td><td>{money(r.net_b)}</td><td>{money(r.delta)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>}

      <section className="panel table-panel">
        <div className="panel-head"><div><h2>Payroll history <span className="count-pill">{runs.length}</span></h2><p>Every period stays visible from draft through payment.</p></div></div>
        <div className="payroll-list">
          {loading ? <div className="empty-state"><strong>Loading payroll history…</strong></div> : runs.map((run) => {
            const slips = run.payslips || [];
            const totals = { gross: sumMoney(slips, ['gross_salary']), tax: sumMoney(slips, ['tax_amount']), net: sumMoney(slips, ['net_salary']) };
            return (
              <article className="payroll-run" key={run.id}>
                <div className="payroll-run-main">
                  <div className="period-icon"><Icon name="calendar" size={17} /></div>
                  <div className="period-copy">
                    <strong>{run.period_start} <span>→</span> {run.period_end}</strong>
                    <small>Run #{run.id} · {slips.length} payslip{slips.length === 1 ? '' : 's'}</small>
                  </div>
                  <span className={`badge badge-${run.status}`}>{run.status}</span>
                </div>
                <div className="payroll-run-metrics">
                  <div><span>Gross</span><strong>{money(totals.gross)}</strong></div>
                  <div><span>Tax</span><strong>{money(totals.tax)}</strong></div>
                  <div><span>Net</span><strong>{money(totals.net)}</strong></div>
                </div>
                {/* Shown on the run itself, not only when approval is attempted,
                    because the whole failure was that a zero tax line looked
                    like a correct one. */}
                {(run.compliance_gaps || []).length > 0 && (
                  <div className="compliance-gap-note">
                    <strong>Statutory tax not verified</strong>
                    <span>{run.compliance_gaps[0].message}</span>
                    {run.status === 'processed' && <small>Approval will ask you to acknowledge this.</small>}
                  </div>
                )}
                <div className="payroll-run-actions">
                  {run.status === 'draft' && <button className="btn btn-primary compact" disabled={processingId === run.id} onClick={() => processRun(run.id)}>{processingId === run.id ? 'Processing…' : 'Run payroll'}</button>}
                  {run.status === 'processed' && (
                    <button className="btn btn-secondary compact" disabled={approvingId === run.id} onClick={() => approveRun(run.id)}>
                      {approvingId === run.id ? 'Approving…' : 'Approve'}
                    </button>
                  )}
                  {run.status === 'approved' && (
                    <>
                      <input className="mini-input" placeholder="Payment reference" value={paymentReference} onChange={(e) => setPaymentReference(e.target.value)} />
                      <button className="btn btn-primary compact" onClick={() => payRun(run.id)}>Mark paid</button>
                    </>
                  )}
                  {slips.length > 0 && <button className="btn-link" onClick={() => setExpandedRun(expandedRun === run.id ? null : run.id)}>{expandedRun === run.id ? 'Hide' : 'View'} payslips</button>}
                  {['processed', 'approved', 'paid'].includes(run.status) && isEnabled('payroll_compare_runs') && (
                  <button className="btn-link" onClick={() => comparePrevious(run.id)}>vs previous</button>
                )}
                  {['processed', 'approved', 'paid'].includes(run.status) && (
                    <>
                      {isEnabled('payroll_email_payslips') && <button className="btn-link" onClick={() => emailPayslips(run.id)}>Email payslips</button>}
                      {isEnabled('payroll_bank_file') && <button className="btn-link" onClick={() => downloadBankFile(run.id)}>Bank file</button>}
                    </>
                  )}
                </div>
                {expandedRun === run.id && (
                  <div style={{ margin: '0.5rem 0' }}>
                    <input
                      placeholder="Filter payslips by name or ID no…"
                      value={payslipFilter}
                      onChange={(e) => setPayslipFilter(e.target.value)}
                      style={{ maxWidth: 280 }}
                    />
                  </div>
                )}
                {expandedRun === run.id && (
                  <div className="table-wrap payslip-table">
                    <table className="modern-table">
                      <thead><tr><th>Employee</th><th>Gross</th><th>Tax</th><th>Contributions</th><th>Net pay</th><th /></tr></thead>
                      <tbody>
                        {slips.filter((p) => {
                          if (!payslipFilter.trim()) return true;
                          const q = payslipFilter.trim().toLowerCase();
                          return (p.employee_name || '').toLowerCase().includes(q)
                            || String(p.employee_id_card_no || '').toLowerCase().includes(q)
                            || String(p.employee_code || '').toLowerCase().includes(q);
                        }).map((p) => (
                          <tr key={p.id}>
                            <td><strong>{p.employee_name}</strong><small style={{display:'block',color:'#64748b'}}>{p.employee_id_card_no || p.employee_code || ''}</small></td>
                            <td>{money(p.gross_salary)}</td>
                            <td>{money(p.tax_amount)}</td>
                            <td>{money(p.total_contributions)}</td>
                            <td><strong>{money(p.net_salary)}</strong></td>
                            <td>
                              <button className="btn-link" onClick={() => downloadPayslip(p.id, 'employee')}>Employee PDF</button>{' '}
                              <button className="btn-link" onClick={() => downloadPayslip(p.id, 'company')}>Company PDF</button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </article>
            );
          })}
          {!loading && runs.length === 0 && (
            <div className="empty-state">
              <div className="empty-icon"><Icon name="wallet" /></div>
              <strong>No payroll runs yet</strong>
              <p>Create your first payroll period above.</p>
            </div>
          )}
        </div>
      </section>

      {pendingGaps && (
        <GapAcknowledgeModal
          gaps={pendingGaps.gaps}
          run={pendingGaps.run}
          busy={approvingId === pendingGaps.runId}
          onCancel={() => setPendingGaps(null)}
          onConfirm={() => approveRun(pendingGaps.runId, true)}
        />
      )}
    </div>
  );
}
