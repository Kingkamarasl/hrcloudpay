import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import EmployeePicker from '../components/EmployeePicker';
import Icon from '../components/Icon';

const labels = { present: 'Present', absent: 'Absent', half_day: 'Half day', leave: 'On leave' };

const ACTION_LABELS = {
  create: 'Create',
  update: 'Update',
  unchanged: 'No change',
  error: 'Problem',
};

const EMPTY_FORM = { employee: '', date: new Date().toISOString().slice(0, 10), status: 'present', check_in: '', check_out: '', crossed_midnight: false };

/** "09:00" -> 540, or null for a blank/invalid field. */
export function minutes(value) {
  if (!value) return null;
  const [h, m] = value.split(':').map(Number);
  if (Number.isNaN(h) || Number.isNaN(m)) return null;
  return h * 60 + m;
}

/**
 * Mirrors the server's rule so the form can say something useful before a
 * round trip. The server is still the authority - this is a hint, not a gate,
 * because a form that disagrees with the API is worse than one that is quiet.
 */
export function workedPreview(checkIn, checkOut, crossed) {
  const start = minutes(checkIn);
  const end = minutes(checkOut);
  if (start === null || end === null) return null;
  const span = (end - start) + (crossed || end < start ? 24 * 60 : 0);
  // Only a negative span is unknown. A zero-length one renders as "0h" because
  // that is what the API will report, and a preview that disagreed with the
  // saved value would be worse than an odd-looking zero.
  if (span < 0) return null;
  const h = Math.floor(span / 60);
  const m = span % 60;
  return `${h}h${m ? ` ${m}m` : ''}`;
}

function formatClock(value) {
  if (!value) return '—';
  return String(value).slice(0, 5);
}

export default function Attendance() {
  const { user } = useAuth();
  const [records, setRecords] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [bulk, setBulk] = useState({ department: '', date: new Date().toISOString().slice(0, 10), status: 'absent' });
  const [range, setRange] = useState({ start: '', end: '' });
  const [importFile, setImportFile] = useState(null);
  const [plan, setPlan] = useState(null);
  const [importResult, setImportResult] = useState(null);

  const isEmployee = user?.role === 'employee';

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const query = new URLSearchParams();
      if (range.start) query.set('start', range.start);
      if (range.end) query.set('end', range.end);
      const suffix = query.toString() ? `?${query}` : '';
      const [r, e] = await Promise.all([
        api.get(`/attendance/records/${suffix}`),
        isEmployee ? Promise.resolve({ results: [] }) : api.get('/employees/employees/'),
      ]);
      setRecords(r.results ?? r);
      setEmployees(e.results ?? e);
    } catch (err) {
      setError(err.message || 'Failed to load attendance.');
    } finally {
      setLoading(false);
    }
  }, [range.start, range.end, isEmployee]);

  useEffect(() => { load(); }, [load]);

  async function submit(event) {
    event.preventDefault();
    setError('');
    setNotice('');
    setBusy(true);
    try {
      // Blank time inputs are sent as null, not '', or the serializer sees an
      // empty string where it expects a time or nothing at all.
      const payload = {
        employee: form.employee,
        date: form.date,
        status: form.status,
        check_in: form.check_in || null,
        check_out: form.check_out || null,
        crossed_midnight: form.crossed_midnight,
      };
      await api.post('/attendance/records/', payload);
      setForm({ ...EMPTY_FORM, date: form.date });
      setNotice('Attendance recorded.');
      await load();
    } catch (err) {
      setError(err.message || 'Failed to record attendance.');
    } finally {
      setBusy(false);
    }
  }

  async function clock(action) {
    setError('');
    setNotice('');
    setBusy(true);
    try {
      await api.post('/attendance/records/clock/', { action });
      setNotice(action === 'clock_in' ? 'Clocked in.' : 'Clocked out.');
      await load();
    } catch (err) {
      setError(err.message || 'Clock action failed.');
    } finally {
      setBusy(false);
    }
  }

  async function bulkSubmit(event) {
    event.preventDefault();
    setError('');
    setNotice('');
    setBusy(true);
    try {
      const result = await api.post('/attendance/records/bulk/', {
        department: bulk.department.trim(),
        date: bulk.date,
        status: bulk.status,
      });
      // Both counts matter: "marked 18" alone would hide the two people whose
      // existing records were deliberately left alone.
      setNotice(
        `Marked ${result.created_count} as ${bulk.status}`
        + (result.skipped_existing
          ? ` — ${result.skipped_existing} already had a record and were left alone.`
          : '.'),
      );
      await load();
    } catch (err) {
      setError(err.message || 'Bulk mark failed.');
    } finally {
      setBusy(false);
    }
  }

  const summary = useMemo(() => ({
    present: records.filter(r => r.status === 'present').length,
    absent: records.filter(r => r.status === 'absent').length,
    half: records.filter(r => r.status === 'half_day').length,
    leave: records.filter(r => r.status === 'leave').length,
    hours: records.reduce((total, r) => total + (r.worked_minutes ?? 0), 0),
  }), [records]);

  const preview = workedPreview(form.check_in, form.check_out, form.crossed_midnight);
  const todayRecord = records.find(r => r.date === new Date().toISOString().slice(0, 10));

  async function downloadTemplate() {
    setError('');
    try {
      const { blob, disposition } = await api.downloadFile('/attendance/imports/template/');
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = (disposition || '').match(/filename="?([^"]+)"?/)?.[1]
        || 'attendance-template.xlsx';
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message || 'Could not download the template.');
    }
  }

  async function previewImport(event) {
    event.preventDefault();
    if (!importFile) return;
    setError('');
    setNotice('');
    setImportResult(null);
    setBusy(true);
    try {
      const data = new FormData();
      data.append('file', importFile);
      // Preview only. Nothing is written until this plan is confirmed, which
      // is the whole point - a month-end upload is not something to apply
      // blind.
      setPlan(await api.upload('/attendance/imports/preview/', data));
    } catch (err) {
      setPlan(null);
      setError(err.message || 'Could not read that file.');
    } finally {
      setBusy(false);
    }
  }

  async function applyImport() {
    if (!plan) return;
    setError('');
    setBusy(true);
    try {
      const result = await api.post('/attendance/imports/apply/', {
        preview_token: plan.preview_token,
      });
      setImportResult(result);
      setPlan(null);
      setImportFile(null);
      setNotice(
        `Imported ${result.created} new`
        + (result.updated ? ` and updated ${result.updated}` : '')
        + (result.refused ? `, ${result.refused} rows refused` : '')
        + '.',
      );
      await load();
    } catch (err) {
      setError(err.message || 'The import could not be applied.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="workspace-page">
      <section className="welcome-row">
        <div>
          <div className="eyebrow">WORKFORCE OPERATIONS</div>
          <h1>Attendance</h1>
          <p>Capture daily presence and keep an operational history by employee.</p>
        </div>
        {!isEmployee && (
          <button className="btn btn-primary" onClick={() => document.getElementById('attendance-entry')?.scrollIntoView({ behavior: 'smooth' })}>
            <Icon name="clock" size={15} />Record attendance
          </button>
        )}
      </section>

      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-success">{notice}</div>}

      {isEmployee && (
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Your shift today</h2>
              <p>
                {todayRecord
                  ? `Recorded for ${todayRecord.date}.`
                  : 'No record yet for today.'}
              </p>
            </div>
          </div>
          <div className="form-row">
            <div>
              <span className="stat-copy">
                <span>Clock in</span>
                <strong>{formatClock(todayRecord?.check_in)}</strong>
              </span>
            </div>
            <div>
              <span className="stat-copy">
                <span>Clock out</span>
                <strong>{formatClock(todayRecord?.check_out)}</strong>
              </span>
            </div>
            <div>
              <span className="stat-copy">
                <span>Worked</span>
                <strong>
                  {todayRecord?.worked_minutes != null
                    ? `${Math.floor(todayRecord.worked_minutes / 60)}h ${todayRecord.worked_minutes % 60}m`
                    : '—'}
                </strong>
              </span>
            </div>
            <div className="form-action">
              <button className="btn btn-primary" type="button" disabled={busy} onClick={() => clock('clock_in')}>
                Clock in
              </button>
              <button className="btn" type="button" disabled={busy} onClick={() => clock('clock_out')}>
                Clock out
              </button>
            </div>
          </div>
        </section>
      )}

      <div className="dash-stats">
        <div className="dash-stat">
          <div className="stat-icon"><Icon name="users" /></div>
          <div className="stat-copy"><span>{isEmployee ? 'Records' : 'Employees'}</span><strong>{isEmployee ? records.length : employees.length}</strong><small>{isEmployee ? 'Visible to you' : 'Available to record'}</small></div>
        </div>
        <div className="dash-stat">
          <div className="stat-icon"><Icon name="clock" /></div>
          <div className="stat-copy"><span>Present</span><strong>{summary.present}</strong><small>Recorded entries</small></div>
        </div>
        <div className="dash-stat">
          <div className="stat-icon"><Icon name="calendar" /></div>
          <div className="stat-copy"><span>On leave</span><strong>{summary.leave}</strong><small>Attendance entries</small></div>
        </div>
        <div className="dash-stat">
          <div className="stat-icon"><Icon name="file" /></div>
          <div className="stat-copy"><span>Exceptions</span><strong>{summary.absent + summary.half}</strong><small>Absent + half day</small></div>
        </div>
      </div>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Period</h2>
            <p>Leave both blank to see everything.</p>
          </div>
        </div>
        <div className="form-row">
          <div>
            <label htmlFor="attendance-from">From</label>
            <input id="attendance-from" type="date" value={range.start} onChange={e => setRange({ ...range, start: e.target.value })} />
          </div>
          <div>
            <label htmlFor="attendance-to">To</label>
            <input id="attendance-to" type="date" value={range.end} onChange={e => setRange({ ...range, end: e.target.value })} />
          </div>
          <div className="stat-copy">
            <span>Total worked</span>
            <strong>{Math.floor(summary.hours / 60)}h {summary.hours % 60}m</strong>
            <small>Across the period shown</small>
          </div>
          <div className="form-action">
            <button className="btn" type="button" onClick={() => setRange({ start: '', end: '' })}>Clear</button>
          </div>
        </div>
      </section>

      {!isEmployee && (
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Mark a department</h2>
              <p>
                Creates records for everyone in a department on one date. Anyone
                who already has a record is left alone.
              </p>
            </div>
          </div>
          <form onSubmit={bulkSubmit}>
            <div className="form-row">
              <div>
                <label htmlFor="bulk-department">Department</label>
                <input
                  id="bulk-department"
                  type="text"
                  value={bulk.department}
                  placeholder="e.g. Sales"
                  onChange={e => setBulk({ ...bulk, department: e.target.value })}
                />
              </div>
              <div>
                <label htmlFor="bulk-date">Date</label>
                <input
                  id="bulk-date"
                  type="date"
                  value={bulk.date}
                  onChange={e => setBulk({ ...bulk, date: e.target.value })}
                  required
                />
              </div>
              <div>
                <label htmlFor="bulk-status">Status</label>
                <select
                  id="bulk-status"
                  value={bulk.status}
                  onChange={e => setBulk({ ...bulk, status: e.target.value })}
                >
                  {Object.entries(labels).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
              </div>
              <div className="form-action">
                <button className="btn" type="submit" disabled={busy || !bulk.department.trim()}>
                  Mark department
                </button>
              </div>
            </div>
          </form>
        </section>
      )}

      {!isEmployee && (
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Import a spreadsheet</h2>
              <p>
                For a month kept in Excel. Nothing is saved until you have seen
                what the file would change.
              </p>
            </div>
            <button className="btn" type="button" onClick={downloadTemplate}>
              <Icon name="file" size={15} />Download template
            </button>
          </div>
          <form onSubmit={previewImport}>
            <div className="form-row">
              <div>
                <label htmlFor="attendance-file">Spreadsheet (.xlsx or .csv)</label>
                <input
                  id="attendance-file"
                  type="file"
                  accept=".xlsx,.xlsm,.csv"
                  onChange={e => {
                    setImportFile(e.target.files?.[0] ?? null);
                    setPlan(null);
                    setImportResult(null);
                  }}
                />
              </div>
              <div className="form-action">
                <button className="btn" type="submit" disabled={busy || !importFile}>
                  Check file
                </button>
              </div>
            </div>
          </form>

          {plan && (
            <div className="table-wrap">
              <p>
                <strong>{plan.filename}</strong> — {plan.total_rows} rows read.{' '}
                <span className="status-dot status-present"><i />{plan.summary.create} to create</span>{' '}
                <span className="status-dot status-half_day"><i />{plan.summary.update} to update</span>{' '}
                <span className="status-dot status-present"><i />{plan.summary.unchanged} unchanged</span>{' '}
                <span className="status-dot status-absent"><i />{plan.summary.error} with problems</span>
              </p>
              <table className="modern-table">
                <thead>
                  <tr>
                    <th>Row</th>
                    <th>Employee</th>
                    <th>Date</th>
                    <th>Status</th>
                    <th>In</th>
                    <th>Out</th>
                    <th>Will</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.rows.slice(0, 50).map(row => (
                    <tr key={row.row}>
                      <td>{row.row}</td>
                      <td>
                        <strong>{row.employee_name || row.employee_ref}</strong>
                        {row.errors.length > 0 && (
                          <small className="status-dot status-absent">
                            <i />{row.errors.join(' ')}
                          </small>
                        )}
                      </td>
                      <td>{row.date ?? '—'}</td>
                      <td>{row.status ? (labels[row.status] || row.status) : '—'}</td>
                      <td>{row.check_in ?? '—'}</td>
                      <td>{row.check_out ?? '—'}{row.crossed_midnight ? ' +1' : ''}</td>
                      <td>{ACTION_LABELS[row.action] || row.action}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {plan.rows.length > 50 && (
                <p><small>Showing the first 50 of {plan.rows.length} rows.</small></p>
              )}
              <div className="form-row">
                <div className="form-action">
                  <button
                    className="btn btn-primary"
                    type="button"
                    disabled={busy || plan.summary.create + plan.summary.update === 0}
                    onClick={applyImport}
                  >
                    Apply {plan.summary.create + plan.summary.update} rows
                  </button>
                  <button className="btn" type="button" onClick={() => setPlan(null)}>
                    Discard
                  </button>
                </div>
              </div>
            </div>
          )}

          {importResult && (
            <p>
              Created {importResult.created}, updated {importResult.updated},{' '}
              unchanged {importResult.unchanged}, refused {importResult.refused}.
              {importResult.errors?.length > 0 && (
                <span> {importResult.errors.join(' ')}</span>
              )}
            </p>
          )}
        </section>
      )}

      {!isEmployee && (
        <section className="panel form-panel" id="attendance-entry">
          <div className="panel-head">
            <div>
              <h2>Record attendance</h2>
              <p>Use one record per employee and date.</p>
            </div>
          </div>
          <form onSubmit={submit}>
            <div className="form-row">
              <div>
                <label>Employee (ID no / code / name)</label>
                <EmployeePicker value={form.employee} required onChange={id => setForm({ ...form, employee: id })} />
              </div>
              <div>
                <label htmlFor="attendance-date">Date</label>
                <input id="attendance-date" type="date" value={form.date} onChange={e => setForm({ ...form, date: e.target.value })} required />
              </div>
              <div>
                <label htmlFor="attendance-status">Status</label>
                <select id="attendance-status" value={form.status} onChange={e => setForm({ ...form, status: e.target.value })}>
                  {Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </div>
            </div>
            <div className="form-row">
              <div>
                <label htmlFor="attendance-in">Check in</label>
                <input id="attendance-in" type="time" value={form.check_in} onChange={e => setForm({ ...form, check_in: e.target.value })} />
              </div>
              <div>
                <label htmlFor="attendance-out">Check out</label>
                <input id="attendance-out" type="time" value={form.check_out} onChange={e => setForm({ ...form, check_out: e.target.value })} />
              </div>
              <div>
                <label htmlFor="attendance-crossed">
                  <input
                    id="attendance-crossed"
                    type="checkbox"
                    checked={form.crossed_midnight}
                    onChange={e => setForm({ ...form, crossed_midnight: e.target.checked })}
                  />
                  Ends next day
                </label>
                <small>
                  {preview
                    ? `Works out to ${preview}.`
                    : 'A check-out earlier than the check-in needs this ticked.'}
                </small>
              </div>
              <div className="stat-copy">
                <span>Worked</span>
                <strong>{preview ?? '—'}</strong>
                <small>From the times above</small>
              </div>
              <div className="form-action">
                <button className="btn btn-primary" type="submit" disabled={busy}>Save record</button>
              </div>
            </div>
          </form>
        </section>
      )}

      <section className="panel table-panel">
        <div className="panel-head">
          <div>
            <h2>Attendance history <span className="count-pill">{records.length}</span></h2>
            <p>Latest records across your accessible workforce.</p>
          </div>
        </div>
        <div className="table-wrap">
          <table className="modern-table">
            <thead>
              <tr>
                <th>Employee</th>
                <th>Date</th>
                <th>In</th>
                <th>Out</th>
                <th>Worked</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan="6" className="empty-row">Loading attendance…</td></tr>}
              {!loading && records.map(r => (
                <tr key={r.id}>
                  <td>
                    <div className="person-cell">
                      <div className="avatar">{(r.employee_name || 'E').slice(0, 1)}</div>
                      <strong>{r.employee_name}</strong>
                    </div>
                  </td>
                  <td>{r.date}</td>
                  <td>{formatClock(r.check_in)}{r.crossed_midnight && <small> +1</small>}</td>
                  <td>{formatClock(r.check_out)}</td>
                  <td>
                    {r.worked_minutes != null
                      ? `${Math.floor(r.worked_minutes / 60)}h ${r.worked_minutes % 60}m`
                      : '—'}
                  </td>
                  <td><span className={`status-dot status-${r.status}`}><i />{labels[r.status] || r.status}</span></td>
                </tr>
              ))}
              {!loading && !records.length && (
                <tr><td colSpan="6" className="empty-row">No attendance records yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}