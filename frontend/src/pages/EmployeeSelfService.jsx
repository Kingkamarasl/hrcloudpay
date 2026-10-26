import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { api, downloadFile } from '../api/client';
import Icon from '../components/Icon';
import EmptyState from '../components/EmptyState';
import { money } from '../utils/money';

const unwrap = (value) => value?.results ?? value ?? [];
const dateLabel = (value) => value ? new Date(`${value}T00:00:00`).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—';

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

function SelfServiceShell({ eyebrow, title, description, children, error }) {
  return (
    <div className="workspace-page employee-self-service">
      <section className="welcome-row">
        <div>
          <div className="eyebrow">{eyebrow}</div>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
        <Link className="btn btn-secondary compact" to="/my-workspace">Back to workspace</Link>
      </section>
      {error && <div className="alert alert-error" role="alert">{error}</div>}
      {children}
    </div>
  );
}

function useSelfService(path, transform = (value) => value) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    api.get(path).then((value) => active && setData(transform(value))).catch((err) => active && setError(err.message || 'Unable to load this page.'));
    return () => { active = false; };
  }, [path]);
  return { data, error, loading: data === null && !error };
}

export function EmployeeMyProfile() {
  const { data: profile, error, loading } = useSelfService('/employees/employees/my-profile/');
  if (loading) return <SelfServiceShell eyebrow="MY PROFILE" title="My profile" description="Your employee record and contact details." error=""><div className="page-loading">Loading your profile…</div></SelfServiceShell>;
  return <SelfServiceShell eyebrow="MY PROFILE" title="My profile" description="Review the employee information held for your account." error={error}>
    {profile && <div className="profile-content-grid">
      <section className="panel"><div className="panel-head"><div><h2>Personal information</h2><p>Contact your HR team if anything needs to change.</p></div></div><div className="detail-grid">
        <div><span>Full name</span><strong>{profile.full_name}</strong></div><div><span>Employee ID</span><strong>{profile.employee_code || '—'}</strong></div>
        <div><span>Email</span><strong>{profile.email || '—'}</strong></div><div><span>Phone</span><strong>{profile.phone || '—'}</strong></div>
        <div><span>Job title</span><strong>{profile.job_title || '—'}</strong></div><div><span>Department</span><strong>{profile.effective_department || profile.department || '—'}</strong></div>
        <div><span>Hire date</span><strong>{dateLabel(profile.hire_date)}</strong></div><div><span>Status</span><strong>{profile.employment_status || '—'}</strong></div>
      </div></section>
      <section className="panel"><div className="panel-head"><div><h2>Self-service</h2><p>Quick links to the information you use most.</p></div></div><div className="activity-list">
        <Link className="activity-row" to="/my-payslips"><div className="activity-icon"><Icon name="wallet" size={16} /></div><div><strong>My payslips</strong><small>View and download payroll statements</small></div></Link>
        <Link className="activity-row" to="/my-attendance"><div className="activity-icon"><Icon name="clock" size={16} /></div><div><strong>My attendance</strong><small>Review your recorded time</small></div></Link>
        <Link className="activity-row" to="/my-leave"><div className="activity-icon"><Icon name="calendar" size={16} /></div><div><strong>My leave</strong><small>Submit and track requests</small></div></Link>
        <Link className="activity-row" to="/my-documents"><div className="activity-icon"><Icon name="file" size={16} /></div><div><strong>My documents</strong><small>Access documents shared with you</small></div></Link>
      </div></section>
    </div>}
  </SelfServiceShell>;
}

export function EmployeeMyPayslips() {
  const { data: payslips, error, loading } = useSelfService('/payroll/payslips/', unwrap);
  const [downloading, setDownloading] = useState(null);
  async function download(id) { setDownloading(id); try { const { blob } = await downloadFile(`/payroll/payslips/${id}/?download=pdf&copy=employee`); saveBlob(blob, `payslip-${id}.pdf`); } catch (err) { /* The page remains usable; the API error is surfaced by the next load. */ } finally { setDownloading(null); } }
  return <SelfServiceShell eyebrow="MY PAYROLL" title="My payslips" description="Your payroll statements, available after each payroll run is processed." error={error}>
    {loading ? <div className="page-loading">Loading your payslips…</div> : payslips?.length ? <section className="panel table-panel"><div className="table-wrap"><table className="modern-table"><thead><tr><th>Pay period</th><th>Gross pay</th><th>Deductions</th><th>Net pay</th><th>Payment</th><th /></tr></thead><tbody>{payslips.map((slip) => <tr key={slip.id}><td>{dateLabel(slip.payroll_period_start)} → {dateLabel(slip.payroll_period_end)}</td><td>{money(slip.gross_salary)}</td><td>{money((Number(slip.tax_amount || 0) + Number(slip.total_contributions || 0) + Number(slip.total_other_deductions || 0)))}</td><td><strong>{money(slip.net_salary)}</strong></td><td>{slip.paid_at ? 'Paid' : 'Processed'}</td><td><button type="button" className="btn-link" disabled={downloading === slip.id} onClick={() => download(slip.id)}>{downloading === slip.id ? 'Preparing…' : 'Download PDF'}</button></td></tr>)}</tbody></table></div></section> : <EmptyState icon="wallet" title="No payslips yet" description="Your payslips will appear here after payroll is processed." />}
  </SelfServiceShell>;
}

export function EmployeeMyAttendance() {
  const { data: records, error, loading } = useSelfService('/attendance/records/', unwrap);
  return <SelfServiceShell eyebrow="MY TIME" title="My attendance" description="Review the attendance records associated with your employee profile." error={error}>
    {loading ? <div className="page-loading">Loading your attendance…</div> : records?.length ? <section className="panel table-panel"><div className="table-wrap"><table className="modern-table"><thead><tr><th>Date</th><th>Status</th><th>Clock in</th><th>Clock out</th><th>Worked</th></tr></thead><tbody>{records.map((item) => <tr key={item.id}><td>{dateLabel(item.date)}</td><td><span className={`badge badge-${item.status}`}>{item.status}</span></td><td>{item.check_in || '—'}</td><td>{item.check_out || '—'}</td><td>{item.worked_minutes == null ? '—' : `${Math.floor(item.worked_minutes / 60)}h ${item.worked_minutes % 60}m`}</td></tr>)}</tbody></table></div></section> : <EmptyState icon="clock" title="No attendance records" description="Your attendance history will appear here." />}
  </SelfServiceShell>;
}

export function EmployeeMyLeave() {
  const { data, error, loading } = useSelfService('/leave/requests/', unwrap);
  const [employeeId, setEmployeeId] = useState(null);
  const [form, setForm] = useState({ leave_type: 'annual', start_date: '', end_date: '', reason: '' });
  const [submitError, setSubmitError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  useEffect(() => { api.get('/employees/employees/my-profile/').then((profile) => setEmployeeId(profile.id)).catch(() => {}); }, []);
  async function submit(event) {
    event.preventDefault();
    setSubmitting(true);
    setSubmitError('');
    try {
      await api.post('/leave/requests/', { ...form, employee: employeeId });
      window.location.reload();
    } catch (err) {
      setSubmitError(err.message || 'Could not submit your leave request.');
      setSubmitting(false);
    }
  }
  return <SelfServiceShell eyebrow="MY TIME OFF" title="My leave" description="Submit and track your leave requests from one place." error={error}>
    <section className="panel"><div className="panel-head"><div><h2>Submit a leave request</h2><p>Send a request to your manager for review.</p></div></div>{submitError && <div className="alert alert-error" role="alert">{submitError}</div>}<form onSubmit={submit}><div className="form-row"><div><label>Leave type</label><select value={form.leave_type} onChange={(event) => setForm({ ...form, leave_type: event.target.value })}><option value="annual">Annual</option><option value="sick">Sick</option><option value="maternity">Maternity</option><option value="paternity">Paternity</option><option value="unpaid">Unpaid</option><option value="other">Other</option></select></div><div><label>Start date</label><input required type="date" value={form.start_date} onChange={(event) => setForm({ ...form, start_date: event.target.value })} /></div><div><label>End date</label><input required type="date" value={form.end_date} onChange={(event) => setForm({ ...form, end_date: event.target.value })} /></div></div><label>Reason</label><input value={form.reason} onChange={(event) => setForm({ ...form, reason: event.target.value })} placeholder="Optional note for the reviewer" /><button className="btn btn-primary compact" type="submit" disabled={!employeeId || submitting}>{submitting ? 'Submitting…' : 'Submit request'}</button></form></section>
    {loading ? <div className="page-loading">Loading your leave…</div> : data?.length ? <section className="panel table-panel"><div className="table-wrap"><table className="modern-table"><thead><tr><th>Type</th><th>Dates</th><th>Days</th><th>Status</th><th>Reason</th></tr></thead><tbody>{data.map((item) => <tr key={item.id}><td>{item.leave_type || 'Leave'}</td><td>{dateLabel(item.start_date)} → {dateLabel(item.end_date)}</td><td>{item.days_requested ?? '—'}</td><td><span className={`badge badge-${item.status}`}>{item.status}</span></td><td>{item.reason || '—'}</td></tr>)}</tbody></table></div></section> : <EmptyState icon="calendar" title="No leave requests" description="Submit a leave request when you need time away." actionLabel="Submit leave" actionTo="/leave" />}
  </SelfServiceShell>;
}

export function EmployeeMyDocuments() {
  const { data: documents, error, loading } = useSelfService('/employees/documents/', unwrap);
  return <SelfServiceShell eyebrow="MY RECORDS" title="My documents" description="Documents shared with your employee record." error={error}>
    {loading ? <div className="page-loading">Loading your documents…</div> : documents?.length ? <section className="panel"><div className="activity-list">{documents.map((doc) => <div className="activity-row" key={doc.id}><div className="activity-icon"><Icon name="file" size={16} /></div><div><strong>{doc.title || doc.document_type_label || 'Document'}</strong><small>{doc.document_type_label || doc.document_type} · Added {dateLabel(String(doc.created_at || '').slice(0, 10))}{doc.expiry_date ? ` · Expires ${dateLabel(doc.expiry_date)}` : ''}</small></div>{doc.document && <a className="btn-link" href={doc.document} target="_blank" rel="noreferrer">Open</a>}</div>)}</div></section> : <EmptyState icon="file" title="No documents yet" description="Documents shared with you by HR will appear here." />}
  </SelfServiceShell>;
}
