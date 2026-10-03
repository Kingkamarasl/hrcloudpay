import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import Icon from '../components/Icon';
import OnboardingChecklist from '../components/OnboardingChecklist';
import ConnectionDetails from '../components/ConnectionDetails';
import EmptyState from '../components/EmptyState';
import { SkeletonStats, SkeletonCard } from '../components/Skeleton';

function Stat({ icon, label, value, detail }) {
  return (
    <div className="dash-stat">
      <div className="stat-icon"><Icon name={icon} /></div>
      <div className="stat-copy">
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </div>
  );
}

/* The caller's own connection card lives in its own component, and is loaded
   independently of the stats below so a slow or failing geolocation provider
   can never delay the rest of the page. */
export default function Dashboard() {
  const { user } = useAuth();
  const [employees, setEmployees] = useState([]);
  const [leaves, setLeaves] = useState([]);
  const [payrolls, setPayrolls] = useState([]);
  const [compliance, setCompliance] = useState(null);
  const [loading, setLoading] = useState(true);
  const [hasIntegrations, setHasIntegrations] = useState(false);

  useEffect(() => {
    Promise.allSettled([
      api.get('/employees/employees/'),
      api.get('/leave/requests/'),
      api.get('/payroll/runs/'),
      api.get('/employees/compliance-dashboard/'),
      api.get('/integrations/'),
    ]).then(([e, l, p, c, i]) => {
      if (e.status === 'fulfilled') setEmployees(e.value.results ?? e.value);
      if (l.status === 'fulfilled') setLeaves(l.value.results ?? l.value);
      if (p.status === 'fulfilled') setPayrolls(p.value.results ?? p.value);
      if (c.status === 'fulfilled') setCompliance(c.value);
      if (i.status === 'fulfilled') {
        setHasIntegrations((i.value?.providers || []).some((x) => x.connected));
      }
    }).finally(() => setLoading(false));
  }, []);

  const active = employees.filter((e) => e.employment_status === 'active').length;
  const pending = leaves.filter((l) => l.status === 'pending').length;
  const latest = payrolls[0];
  const greeting = useMemo(() => {
    const h = new Date().getHours();
    return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
  }, []);

  return (
    <div className="dashboard-page">
      <section className="welcome-row dashboard-welcome">
        <div className="dashboard-welcome-copy">
          <div className="eyebrow">WORKSPACE OVERVIEW</div>
          <h1>{greeting}, {user?.username || 'there'}.</h1>
          <p>Here’s what’s happening across {user?.company?.name || 'your organization'} today.</p>
          <div className="dashboard-pulse" aria-label="Workspace pulse">
            <span><Icon name="users" size={14} /><b>{loading ? '—' : active}</b> active employees</span>
            <span><Icon name="calendar" size={14} /><b>{loading ? '—' : pending}</b> requests to review</span>
            <span><Icon name="wallet" size={14} /><b>{latest?.status || 'No run'}</b> latest payroll</span>
          </div>
          <ConnectionDetails />
        </div>
        <div className="dash-actions">
          <Link to="/employees" className="btn btn-secondary">View employees</Link>
          <Link to="/payroll" className="btn btn-primary compact">
            Run payroll <Icon name="arrow" size={16} />
          </Link>
        </div>
      </section>

      <OnboardingChecklist employeeCount={employees.length} hasIntegrations={hasIntegrations} />

      {!user?.company?.payroll_configured && (
        <div className="setup-banner">
          <div className="setup-icon">!</div>
          <div>
            <strong>Finish your payroll setup</strong>
            <p>Add your country payroll rules before processing your first payroll.</p>
          </div>
          <Link to="/payroll-setup">
            Complete setup <Icon name="arrow" size={15} />
          </Link>
        </div>
      )}

      {loading ? (
        <SkeletonStats count={4} />
      ) : (
        <div className="dash-stats">
          <Stat icon="users" label="Total employees" value={employees.length} detail={`${active} active`} />
          <Stat icon="calendar" label="Pending requests" value={pending} detail="Leave & breaks" />
          <Stat
            icon="wallet"
            label="Latest payroll"
            value={latest ? latest.status : '—'}
            detail={latest ? `${latest.period_start} → ${latest.period_end}` : 'No runs yet'}
          />
          <Stat
            icon="shield"
            label="Compliance score"
            value={compliance?.summary?.average_score != null ? `${compliance.summary.average_score}%` : '—'}
            detail={`${compliance?.summary?.needs_attention ?? 0} need attention`}
          />
        </div>
      )}

      <div className="dash-grid">
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Recent leave</h2>
              <p>Latest time-off activity</p>
            </div>
            <Link to="/leave">View all <Icon name="arrow" size={14} /></Link>
          </div>
          {loading ? (
            <SkeletonCard lines={4} />
          ) : leaves.length ? (
            <div className="activity-list">
              {leaves.slice(0, 5).map((l) => (
                <div className="activity-row" key={l.id}>
                  <div className="activity-icon"><Icon name="calendar" size={16} /></div>
                  <div>
                    <strong>{l.employee_name || `Employee #${l.employee}`}</strong>
                    <small>{l.start_date} → {l.end_date}</small>
                  </div>
                  <span className={`badge badge-${l.status}`}>{l.status}</span>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              icon="calendar"
              title="No leave requests yet"
              description="When employees submit leave or break requests, they will show up here."
              actionLabel="Open leave"
              actionTo="/leave"
            />
          )}
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Recent payroll</h2>
              <p>Latest payroll runs</p>
            </div>
            <Link to="/payroll">View all <Icon name="arrow" size={14} /></Link>
          </div>
          {loading ? (
            <SkeletonCard lines={4} />
          ) : payrolls.length ? (
            <div className="activity-list">
              {payrolls.slice(0, 5).map((p) => (
                <div className="activity-row" key={p.id}>
                  <div className="activity-icon"><Icon name="wallet" size={16} /></div>
                  <div>
                    <strong>{p.period_start} — {p.period_end}</strong>
                    <small>Payroll run</small>
                  </div>
                  <span className={`badge badge-${p.status}`}>{p.status}</span>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              icon="wallet"
              title="No payroll runs yet"
              description="Once you process payroll, recent runs will appear here."
              actionLabel="Create payroll run"
              actionTo="/payroll"
            />
          )}
        </section>
      </div>

      <section className="panel quick-panel">
        <div className="panel-head">
          <div>
            <h2>HR compliance</h2>
            <p>Document and contract risk across your workforce</p>
          </div>
          <Link to="/compliance">Open compliance center <Icon name="arrow" size={14} /></Link>
        </div>
        <div className="quick-grid">
          <div className="quick-card">
            <Icon name="shield" />
            <span>
              <strong>{compliance?.summary?.average_score ?? '—'}% average compliance</strong>
              <small>{compliance?.summary?.needs_attention ?? 0} employees need attention</small>
            </span>
          </div>
          <div className="quick-card">
            <Icon name="file" />
            <span>
              <strong>{compliance?.summary?.missing_documents ?? 0} missing documents</strong>
              <small>{compliance?.summary?.expired_documents ?? 0} expired documents</small>
            </span>
          </div>
          <div className="quick-card">
            <Icon name="calendar" />
            <span>
              <strong>{compliance?.summary?.expiring_documents ?? 0} expiring documents</strong>
              <small>Plus {compliance?.summary?.open_alerts ?? 0} open compliance alerts</small>
            </span>
          </div>
        </div>
      </section>

      <section className="panel quick-panel">
        <div className="panel-head">
          <div>
            <h2>Quick actions</h2>
            <p>Common tasks for your HR team</p>
          </div>
        </div>
        <div className="quick-grid">
          <Link to="/employees" className="quick-card">
            <Icon name="users" />
            <span><strong>Add employee</strong><small>Create a new employee record</small></span>
            <Icon name="arrow" size={15} />
          </Link>
          <Link to="/departments" className="quick-card">
            <Icon name="building" />
            <span><strong>Manage departments</strong><small>Teams, managers and headcount</small></span>
            <Icon name="arrow" size={15} />
          </Link>
          <Link to="/attendance" className="quick-card">
            <Icon name="clock" />
            <span><strong>Review attendance</strong><small>Monitor daily attendance</small></span>
            <Icon name="arrow" size={15} />
          </Link>
          <Link to="/leave" className="quick-card">
            <Icon name="calendar" />
            <span><strong>Review requests</strong><small>{pending} pending requests</small></span>
            <Icon name="arrow" size={15} />
          </Link>
        </div>
      </section>
    </div>
  );
}
