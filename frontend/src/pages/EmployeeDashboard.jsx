import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { downloadFile } from '../api/client';
import { api } from '../api/client';
import Icon from '../components/Icon';
import EmptyState from '../components/EmptyState';
import { money } from '../utils/money';

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

function unwrap(value) {
  return value?.results ?? value ?? [];
}

export default function EmployeeDashboard() {
  const [profile, setProfile] = useState(null);
  const [payslips, setPayslips] = useState([]);
  const [attendance, setAttendance] = useState([]);
  const [leave, setLeave] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [downloading, setDownloading] = useState(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      api.get('/employees/employees/my-profile/'),
      api.get('/payroll/payslips/'),
      api.get('/attendance/records/'),
      api.get('/leave/requests/'),
    ])
      .then(([profileData, payslipData, attendanceData, leaveData]) => {
        if (!active) return;
        setProfile(profileData);
        setPayslips(unwrap(payslipData));
        setAttendance(unwrap(attendanceData));
        setLeave(unwrap(leaveData));
      })
      .catch((err) => {
        if (active) setError(err.message || 'Unable to load your workspace.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  const pendingLeave = useMemo(
    () => leave.filter((item) => item.status === 'pending').length,
    [leave],
  );
  const latestPayslip = payslips[0];
  const recentAttendance = attendance.slice(0, 5);
  const recentLeave = leave.slice(0, 5);

  async function downloadPayslip(id) {
    setDownloading(id);
    setError('');
    try {
      const { blob } = await downloadFile(`/payroll/payslips/${id}/?download=pdf&copy=employee`);
      saveBlob(blob, `payslip-${id}.pdf`);
    } catch (err) {
      setError(err.message || 'Could not download your payslip.');
    } finally {
      setDownloading(null);
    }
  }

  return (
    <div className="dashboard-page employee-dashboard">
      <section className="welcome-row dashboard-welcome">
        <div className="dashboard-welcome-copy">
          <div className="eyebrow">MY WORKSPACE</div>
          <h1>Welcome, {profile?.full_name || 'there'}.</h1>
          <p>Keep track of your profile, attendance, leave, and payslips in one place.</p>
        </div>
        <div className="dash-actions">
          <Link to="/my-leave" className="btn btn-primary compact">Request leave <Icon name="arrow" size={16} /></Link>
          <Link to="/my-attendance" className="btn btn-secondary compact">View attendance</Link>
        </div>
      </section>

      {error && <div className="alert alert-error" role="alert">{error}</div>}

      {loading ? (
        <div className="page-loading">Loading your workspace…</div>
      ) : (
        <>
          <div className="dash-stats">
            <div className="dash-stat"><div className="stat-icon"><Icon name="wallet" /></div><div className="stat-copy"><span>Latest net pay</span><strong>{latestPayslip ? money(latestPayslip.net_salary) : '—'}</strong><small>{latestPayslip ? `${latestPayslip.period_start} → ${latestPayslip.period_end}` : 'No payslip yet'}</small></div></div>
            <div className="dash-stat"><div className="stat-icon"><Icon name="clock" /></div><div className="stat-copy"><span>Attendance records</span><strong>{attendance.length}</strong><small>Visible to you</small></div></div>
            <div className="dash-stat"><div className="stat-icon"><Icon name="calendar" /></div><div className="stat-copy"><span>Pending leave</span><strong>{pendingLeave}</strong><small>Awaiting review</small></div></div>
            <div className="dash-stat"><div className="stat-icon"><Icon name="user" /></div><div className="stat-copy"><span>Job title</span><strong>{profile?.job_title || '—'}</strong><small>{profile?.effective_department || profile?.department || 'No department'}</small></div></div>
          </div>

          <div className="dash-grid">
            <section className="panel">
              <div className="panel-head"><div><h2>My payslips</h2><p>Your latest payroll statements</p></div></div>
              {payslips.length ? (
                <div className="activity-list">
                  {payslips.slice(0, 5).map((slip) => (
                    <div className="activity-row" key={slip.id}>
                      <div className="activity-icon"><Icon name="wallet" size={16} /></div>
                      <div><strong>{slip.period_start} → {slip.period_end}</strong><small>Net pay {money(slip.net_salary)}</small></div>
                      <button className="btn-link" type="button" disabled={downloading === slip.id} onClick={() => downloadPayslip(slip.id)}>{downloading === slip.id ? 'Preparing…' : 'PDF'}</button>
                    </div>
                  ))}
                </div>
              ) : <EmptyState icon="wallet" title="No payslips yet" description="Your payslips will appear here after payroll is processed." />}
            </section>

            <section className="panel">
              <div className="panel-head"><div><h2>My leave</h2><p>Recent requests and decisions</p></div><Link to="/my-leave">Open leave <Icon name="arrow" size={14} /></Link></div>
              {recentLeave.length ? (
                <div className="activity-list">
                  {recentLeave.map((item) => <div className="activity-row" key={item.id}><div className="activity-icon"><Icon name="calendar" size={16} /></div><div><strong>{item.start_date} → {item.end_date}</strong><small>{item.leave_type || 'Leave request'}</small></div><span className={`badge badge-${item.status}`}>{item.status}</span></div>)}
                </div>
              ) : <EmptyState icon="calendar" title="No leave requests" description="Submit a leave request when you need time away." actionLabel="Request leave" actionTo="/my-leave" />}
            </section>
          </div>

          <section className="panel">
            <div className="panel-head"><div><h2>Recent attendance</h2><p>Your latest recorded attendance</p></div><Link to="/my-attendance">View all <Icon name="arrow" size={14} /></Link></div>
            {recentAttendance.length ? (
              <div className="table-wrap"><table className="modern-table"><thead><tr><th>Date</th><th>Status</th><th>Clock in</th><th>Clock out</th><th>Worked</th></tr></thead><tbody>{recentAttendance.map((item) => <tr key={item.id}><td>{item.date}</td><td><span className={`badge badge-${item.status}`}>{item.status}</span></td><td>{item.check_in || '—'}</td><td>{item.check_out || '—'}</td><td>{item.worked_minutes != null ? `${Math.floor(item.worked_minutes / 60)}h ${item.worked_minutes % 60}m` : '—'}</td></tr>)}</tbody></table></div>
            ) : <EmptyState icon="clock" title="No attendance records" description="Your attendance history will appear here." actionLabel="Open attendance" actionTo="/my-attendance" />}
          </section>
        </>
      )}
    </div>
  );
}
