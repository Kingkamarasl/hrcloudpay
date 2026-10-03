import { useEffect, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';

const CHART_COLORS = ['#0f766e', '#f59e0b', '#6366f1', '#ec4899', '#10b981', '#ef4444', '#0ea5e9'];

function WidgetCard({ title, children, empty }) {
  return (
    <div className="widget-card">
      <div className="widget-title">{title}</div>
      {empty ? <div className="widget-empty">No data yet</div> : children}
    </div>
  );
}

export default function PayrollDashboard() {
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const currency = user?.company?.payroll_config?.currency || '';

  useEffect(() => {
    api
      .get('/payroll/dashboard/')
      .then(setData)
      .catch((err) => setError(err.message || 'Failed to load payroll dashboard'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p>Loading payroll dashboard...</p>;
  if (error) return <div className="alert alert-error">{error}</div>;

  const hasEmployeeData = data.amount_by_employee.length > 0;
  const hasPayDateData = data.amount_by_pay_date.length > 0;
  const hasDeptData = data.pay_statement_by_department.length > 0;
  const hasFundingData = data.payroll_funding.length > 0;
  const hasRuns = data.recent_runs.length > 0;

  return (
    <div>
      <div className="profile-banner">
        <div className="profile-banner-avatar">
          {(user?.username || '?').slice(0, 1).toUpperCase()}
        </div>
        <div className="profile-banner-info">
          <div className="profile-banner-name">{user?.username}</div>
          <div className="profile-banner-meta">
            {user?.company?.name} · {user?.company?.plan} plan
          </div>
        </div>
        <div className="profile-banner-stats">
          <div>
            <div className="profile-banner-stat-value">{data.recent_runs.filter(r => r.status === 'processed').length}</div>
            <div className="profile-banner-stat-label">Runs awaiting approval</div>
          </div>
          <div>
            <div className="profile-banner-stat-value">{data.recent_runs.filter(r => r.status === 'approved').length}</div>
            <div className="profile-banner-stat-label">Approved, awaiting payment</div>
          </div>
        </div>
      </div>

      <h1 style={{ marginTop: '1.5rem' }}>Payroll Dashboard</h1>
      <p className="page-subtitle">A snapshot of your most recent payroll run and pay trends over time.</p>

      <div className="widget-grid">
        <WidgetCard title="Amount by Employee" empty={!hasEmployeeData}>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={data.amount_by_employee}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="employee" tick={{ fontSize: 11 }} interval={0} angle={-20} textAnchor="end" height={50} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v) => `${currency} ${Number(v).toLocaleString()}`} />
              <Bar dataKey="amount" radius={[4, 4, 0, 0]}>
                {data.amount_by_employee.map((_, i) => (
                  <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </WidgetCard>

        <WidgetCard title="Amount by Pay Date" empty={!hasPayDateData}>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={data.amount_by_pay_date} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 11 }} />
              <YAxis type="category" dataKey="pay_date" tick={{ fontSize: 11 }} width={80} />
              <Tooltip formatter={(v) => `${currency} ${Number(v).toLocaleString()}`} />
              <Bar dataKey="amount" fill="#0f766e" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </WidgetCard>

        <WidgetCard title="Gross Wages by Pay Date" empty={!hasPayDateData}>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={data.gross_wages_by_pay_date}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="pay_date" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v) => `${currency} ${Number(v).toLocaleString()}`} />
              <Line type="monotone" dataKey="amount" stroke="#84cc16" strokeWidth={2} dot={{ r: 3 }} />
            </LineChart>
          </ResponsiveContainer>
        </WidgetCard>

        <WidgetCard title="Pay Statement History (by department)" empty={!hasDeptData}>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie
                data={data.pay_statement_by_department}
                dataKey="amount"
                nameKey="department"
                innerRadius={40}
                outerRadius={80}
                paddingAngle={2}
              >
                {data.pay_statement_by_department.map((_, i) => (
                  <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip formatter={(v) => `${currency} ${Number(v).toLocaleString()}`} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
            </PieChart>
          </ResponsiveContainer>
        </WidgetCard>

        <WidgetCard title="Payroll Funding (employer cost)" empty={!hasFundingData}>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={data.payroll_funding}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="pay_date" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v) => `${currency} ${Number(v).toLocaleString()}`} />
              <Bar dataKey="amount" fill="#6366f1" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </WidgetCard>

        <WidgetCard title="Payroll" empty={!hasRuns}>
          <table className="data-table widget-table">
            <thead>
              <tr>
                <th>Period</th>
                <th>Status</th>
                <th>Employees</th>
                <th>Net total</th>
              </tr>
            </thead>
            <tbody>
              {data.recent_runs.map((run) => (
                <tr key={run.id}>
                  <td>{run.period_start} → {run.period_end}</td>
                  <td><span className={`badge badge-${run.status}`}>{run.status}</span></td>
                  <td>{run.employee_count}</td>
                  <td>{currency} {run.total_net.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </WidgetCard>
      </div>
    </div>
  );
}
