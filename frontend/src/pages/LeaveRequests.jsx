import { useEffect, useMemo, useState } from 'react';
import { api, downloadFile } from '../api/client';
import EmployeePicker from '../components/EmployeePicker';
import Icon from '../components/Icon';
import { useToast } from '../context/ToastContext';

const leaveTypes = {
  annual: 'Annual', sick: 'Sick', maternity: 'Maternity',
  paternity: 'Paternity', unpaid: 'Unpaid', other: 'Other',
};
const breakTypes = {
  short: 'Short break', lunch: 'Lunch break',
  personal: 'Personal break', other: 'Other',
};

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function downloadPdf(path, filename) {
  const { blob } = await downloadFile(path);
  downloadBlob(blob, filename);
}

export default function LeaveRequests() {
  const toast = useToast();
  const [tab, setTab] = useState('leave');
  const [requests, setRequests] = useState([]);
  const [breaks, setBreaks] = useState([]);
  const [listFilter, setListFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [leaveForm, setLeaveForm] = useState({
    employee: '', leave_type: 'annual', start_date: '', end_date: '', reason: '',
  });
  const [breakForm, setBreakForm] = useState({
    employee: '', break_type: 'personal', date: '', start_time: '', end_time: '', reason: '',
  });

  function load() {
    setLoading(true);
    Promise.all([
      api.get('/leave/requests/'),
      api.get('/leave/break-requests/'),
    ])
      .then(([r, b]) => {
        setRequests(r.results ?? r);
        setBreaks(b.results ?? b);
      })
      .catch((err) => setError(err.message || 'Failed to load requests.'))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function submitLeave(e) {
    e.preventDefault();
    setError('');
    try {
      await api.post('/leave/requests/', leaveForm);
      setLeaveForm({ employee: '', leave_type: 'annual', start_date: '', end_date: '', reason: '' });
      toast.success('Leave request submitted');
      load();
    } catch (err) {
      const msg = err.message || 'Failed to submit leave request.';
      setError(msg);
      toast.error(msg);
    }
  }

  async function submitBreak(e) {
    e.preventDefault();
    setError('');
    try {
      await api.post('/leave/break-requests/', breakForm);
      setBreakForm({ employee: '', break_type: 'personal', date: '', start_time: '', end_time: '', reason: '' });
      toast.success('Break request submitted');
      load();
    } catch (err) {
      const msg = err.message || 'Failed to submit break request.';
      setError(msg);
      toast.error(msg);
    }
  }

  async function reviewLeave(id, action) {
    setError('');
    try {
      await api.post(`/leave/requests/${id}/${action}/`, {});
      toast.success(action === 'approve' ? 'Leave approved' : 'Leave rejected');
      load();
    } catch (err) {
      toast.error(err.message || 'Action failed.');
    }
  }

  async function reviewBreak(id, action) {
    setError('');
    try {
      await api.post(`/leave/break-requests/${id}/${action}/`, {});
      toast.success(action === 'approve' ? 'Break approved' : 'Break rejected');
      load();
    } catch (err) {
      toast.error(err.message || 'Action failed.');
    }
  }

  async function pdfLeave(id, copy = 'employee') {
    try {
      await downloadPdf(`/leave/requests/${id}/pdf/?copy=${copy}`, `leave-request-${id}-${copy}.pdf`);
      toast.success('Leave form PDF downloaded');
    } catch (err) {
      toast.error(err.message || 'PDF download failed');
    }
  }

  async function pdfBreak(id, copy = 'employee') {
    try {
      await downloadPdf(`/leave/break-requests/${id}/pdf/?copy=${copy}`, `break-request-${id}-${copy}.pdf`);
      toast.success('Break form PDF downloaded');
    } catch (err) {
      toast.error(err.message || 'PDF download failed');
    }
  }

  const pendingLeave = useMemo(() => requests.filter((r) => r.status === 'pending').length, [requests]);
  const pendingBreak = useMemo(() => breaks.filter((r) => r.status === 'pending').length, [breaks]);
  // The queue filter box writes `listFilter`; without this the input accepted
  // text and the table never changed. Match the same fields the row renders.
  const visibleRequests = useMemo(() => {
    const q = listFilter.trim().toLowerCase();
    if (!q) return requests;
    return requests.filter((r) => [r.employee_name, r.employee_id_card_no, r.employee_code, r.id]
      .some((v) => String(v ?? '').toLowerCase().includes(q)));
  }, [requests, listFilter]);

  return (
    <div className="workspace-page">
      <section className="welcome-row">
        <div>
          <div className="eyebrow">PEOPLE OPERATIONS</div>
          <h1>Leave &amp; breaks</h1>
          <p>Manage time-off and break requests, approvals, and printable employee copies.</p>
        </div>
        <div className="dash-actions">
          <button type="button" className={`btn ${tab === 'leave' ? 'btn-primary' : 'btn-secondary'}`} style={{ width: 'auto' }} onClick={() => setTab('leave')}>
            Leave ({pendingLeave} pending)
          </button>
          <button type="button" className={`btn ${tab === 'break' ? 'btn-primary' : 'btn-secondary'}`} style={{ width: 'auto' }} onClick={() => setTab('break')}>
            Breaks ({pendingBreak} pending)
          </button>
        </div>
      </section>

      {error && <div className="alert alert-error">{error}</div>}

      {tab === 'leave' && (
        <>
          <section className="panel" id="leave-entry">
            <div className="panel-head">
              <div>
                <h2>New leave request</h2>
                <p>Create a request for an employee, then review it from the queue below.</p>
              </div>
            </div>
            <form onSubmit={submitLeave}>
              <div className="form-row">
                <div>
                  <label>Employee (search ID no / code / name)</label>
                  <EmployeePicker
                    value={leaveForm.employee}
                    required
                    onChange={(id) => setLeaveForm({ ...leaveForm, employee: id })}
                  />
                </div>
                <div>
                  <label>Leave type</label>
                  <select value={leaveForm.leave_type} onChange={(e) => setLeaveForm({ ...leaveForm, leave_type: e.target.value })}>
                    {Object.entries(leaveTypes).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </div>
                <div>
                  <label>Start date</label>
                  <input type="date" value={leaveForm.start_date} onChange={(e) => setLeaveForm({ ...leaveForm, start_date: e.target.value })} required />
                </div>
                <div>
                  <label>End date</label>
                  <input type="date" value={leaveForm.end_date} onChange={(e) => setLeaveForm({ ...leaveForm, end_date: e.target.value })} required />
                </div>
              </div>
              <label>Reason</label>
              <input value={leaveForm.reason} onChange={(e) => setLeaveForm({ ...leaveForm, reason: e.target.value })} placeholder="Optional note for the reviewer" />
              <button className="btn btn-primary compact" type="submit">Submit leave request</button>
            </form>
          </section>

          <section className="panel table-panel">
            <div className="panel-head">
              <div>
                <h2>Leave queue <span className="count-pill">{pendingLeave} pending</span></h2>
                <p>Review requests and download employee / company PDF copies.</p>
                <input
                  style={{ marginTop: 8, maxWidth: 280 }}
                  placeholder="Filter by name or ID…"
                  value={listFilter}
                  onChange={(e) => setListFilter(e.target.value)}
                />
              </div>
            </div>
            <div className="table-wrap">
              <table className="modern-table">
                <thead>
                  <tr>
                    <th>Employee</th><th>Type</th><th>Dates</th><th>Days</th><th>Status</th><th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {loading && <tr><td colSpan="6" className="empty-row">Loading…</td></tr>}
                  {!loading && visibleRequests.map((r) => (
                    <tr key={r.id}>
                      <td><div className="person-cell"><div className="avatar">{(r.employee_name || 'E').slice(0, 1)}</div><div><strong>{r.employee_name}</strong><small style={{display:'block',color:'#64748b'}}>{r.employee_id_card_no || r.employee_code || ''}</small></div></div></td>
                      <td>{leaveTypes[r.leave_type] || r.leave_type}</td>
                      <td>{r.start_date} <span className="muted-arrow">→</span> {r.end_date}</td>
                      <td>{r.days_requested}</td>
                      <td><span className={`badge badge-${r.status}`}>{r.status}</span></td>
                      <td>
                        <div className="table-actions">
                          {r.status === 'pending' && (
                            <>
                              <button className="btn btn-secondary compact" onClick={() => reviewLeave(r.id, 'approve')}>Approve</button>
                              <button className="btn btn-danger compact" onClick={() => reviewLeave(r.id, 'reject')}>Reject</button>
                            </>
                          )}
                          <button className="btn-link" onClick={() => pdfLeave(r.id, 'employee')}>Employee PDF</button>
                          <button className="btn-link" onClick={() => pdfLeave(r.id, 'company')}>Company PDF</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {!loading && !visibleRequests.length && (
                    <tr>
                      <td colSpan="6" className="empty-row">
                        {listFilter.trim()
                          ? `No leave requests match “${listFilter.trim()}”.`
                          : 'No leave requests yet.'}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      {tab === 'break' && (
        <>
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>New break request</h2>
                <p>Log a short, lunch, or personal break. Download a signed form PDF for the employee.</p>
              </div>
            </div>
            <form onSubmit={submitBreak}>
              <div className="form-row">
                <div>
                  <label>Employee (search ID no / code / name)</label>
                  <EmployeePicker
                    value={breakForm.employee}
                    required
                    onChange={(id) => setBreakForm({ ...breakForm, employee: id })}
                  />
                </div>
                <div>
                  <label>Break type</label>
                  <select value={breakForm.break_type} onChange={(e) => setBreakForm({ ...breakForm, break_type: e.target.value })}>
                    {Object.entries(breakTypes).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </div>
                <div>
                  <label>Date</label>
                  <input type="date" value={breakForm.date} onChange={(e) => setBreakForm({ ...breakForm, date: e.target.value })} required />
                </div>
                <div>
                  <label>Start time</label>
                  <input type="time" value={breakForm.start_time} onChange={(e) => setBreakForm({ ...breakForm, start_time: e.target.value })} required />
                </div>
                <div>
                  <label>End time</label>
                  <input type="time" value={breakForm.end_time} onChange={(e) => setBreakForm({ ...breakForm, end_time: e.target.value })} />
                </div>
              </div>
              <label>Reason</label>
              <input value={breakForm.reason} onChange={(e) => setBreakForm({ ...breakForm, reason: e.target.value })} placeholder="Optional note" />
              <button className="btn btn-primary compact" type="submit">Submit break request</button>
            </form>
          </section>

          <section className="panel table-panel">
            <div className="panel-head">
              <div>
                <h2>Break queue <span className="count-pill">{pendingBreak} pending</span></h2>
                <p>Approve breaks and download employee or company PDF copies.</p>
              </div>
            </div>
            <div className="table-wrap">
              <table className="modern-table">
                <thead>
                  <tr>
                    <th>Employee</th><th>Type</th><th>Date</th><th>Time</th><th>Status</th><th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {loading && <tr><td colSpan="6" className="empty-row">Loading…</td></tr>}
                  {!loading && breaks.map((r) => (
                    <tr key={r.id}>
                      <td><div className="person-cell"><div className="avatar">{(r.employee_name || 'E').slice(0, 1)}</div><div><strong>{r.employee_name}</strong><small style={{display:'block',color:'#64748b'}}>{r.employee_id_card_no || r.employee_code || ''}</small></div></div></td>
                      <td>{breakTypes[r.break_type] || r.break_type}</td>
                      <td>{r.date}</td>
                      <td>{String(r.start_time || '').slice(0, 5)}{r.end_time ? ` → ${String(r.end_time).slice(0, 5)}` : ''}</td>
                      <td><span className={`badge badge-${r.status}`}>{r.status}</span></td>
                      <td>
                        <div className="table-actions">
                          {r.status === 'pending' && (
                            <>
                              <button className="btn btn-secondary compact" onClick={() => reviewBreak(r.id, 'approve')}>Approve</button>
                              <button className="btn btn-danger compact" onClick={() => reviewBreak(r.id, 'reject')}>Reject</button>
                            </>
                          )}
                          <button className="btn-link" onClick={() => pdfBreak(r.id, 'employee')}>Employee PDF</button>
                          <button className="btn-link" onClick={() => pdfBreak(r.id, 'company')}>Company PDF</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {!loading && !breaks.length && <tr><td colSpan="6" className="empty-row">No break requests yet.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
