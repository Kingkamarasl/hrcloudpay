import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';

const CONFIG = {
  employee: {
    eyebrow: 'EMPLOYEE 360°',
    title: 'Employee operations',
    sub: 'One operational view of people, contracts, documents, requests and workforce events.',
    endpoint: '/employees/dashboard-summary/',
    links: [
      ['/employees', 'Employee directory'],
      ['/departments', 'Departments'],
      ['/compliance', 'Compliance'],
      ['/request-tracking', 'Requests'],
    ],
  },
  payroll: {
    eyebrow: 'PAYROLL CONTROL',
    title: 'Payroll operations',
    sub: 'A controlled payroll workflow from preparation through approval, payment evidence and audit.',
    endpoint: '/payroll/dashboard/',
    links: [
      ['/payroll', 'Payroll runs'],
      ['/payroll-dashboard', 'Analytics'],
      ['/payroll-extras', 'Overtime & advances'],
      ['/audit-logs', 'Audit trail'],
    ],
  },
  leave: {
    eyebrow: 'WORKFORCE OPERATIONS',
    title: 'Attendance & leave',
    sub: 'Keep attendance, leave balances, requests and approvals connected to employee operations.',
    endpoint: '/leave/balances/',
    links: [
      ['/attendance', 'Attendance'],
      ['/leave', 'Leave & breaks'],
      ['/leave-accrual', 'Leave accruals'],
      ['/request-tracking', 'Request tracking'],
    ],
  },
  default: {
    eyebrow: 'SAAS CONTROL CENTER',
    title: 'Platform operations',
    sub: 'Operate HRCloudPay as a multi-tenant SaaS with customer, billing, security, support and release controls.',
    endpoint: null,
    links: [
      ['/platform-admin', 'Platform Admin'],
      ['/audit-logs', 'Audit trail'],
      ['/billing', 'Billing'],
      ['/integrations', 'Integrations'],
    ],
  },
};

const label = (key) => key.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

const isScalar = (v) => v === null || ['string', 'number', 'boolean'].includes(typeof v);

/**
 * Renders whatever the summary endpoint returns as readable key/value rows.
 *
 * The three hubs return three unrelated shapes ({kpis, alerts}, a payroll
 * chart bundle, a balance list), and hardcoding one layout per endpoint would
 * drift the moment a field is renamed. Values that are neither scalars nor
 * plain lists fall back to a collapsed raw view rather than being dropped.
 */
function SummaryRows({ data }) {
  if (Array.isArray(data)) {
    if (!data.length) return <p className="muted">Nothing to show yet.</p>;
    return (
      <ul className="ops-summary-list">
        {data.slice(0, 50).map((row, i) => (
          <li key={row.id ?? i}>
            {isScalar(row)
              ? String(row)
              : Object.entries(row)
                  .filter(([, v]) => isScalar(v))
                  .map(([k, v]) => `${label(k)}: ${v === null ? '—' : String(v)}`)
                  .join(' · ') || JSON.stringify(row)}
          </li>
        ))}
      </ul>
    );
  }

  const groups = Object.entries(data ?? {});
  if (!groups.length) return <p className="muted">No summary data available.</p>;

  return groups.map(([section, value]) => {
    if (isScalar(value)) {
      return (
        <div className="ops-summary-row" key={section}>
          <span className="muted">{label(section)}</span>
          <strong>{value === null ? '—' : String(value)}</strong>
        </div>
      );
    }
    const entries = Object.entries(value ?? {});
    return (
      <div key={section} className="ops-summary-section">
        <h3>{label(section)}</h3>
        {entries.length === 0 && <p className="muted">No data.</p>}
        {entries.map(([k, v]) => (
          <div className="ops-summary-row" key={k}>
            <span className="muted">{label(k)}</span>
            <strong>
              {isScalar(v)
                ? (v === null ? '—' : Array.isArray(v) ? v.length : String(v))
                : `${(Array.isArray(v) ? v : Object.keys(v ?? {})).length} items`}
            </strong>
          </div>
        ))}
      </div>
    );
  });
}

export default function OperationsHub({ type }) {
  const config = CONFIG[type] ?? CONFIG.default;
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(!!config.endpoint);

  useEffect(() => {
    let cancelled = false;
    if (!config.endpoint) return undefined;
    setLoading(true);
    setError('');
    // The paths stay as literals in the calls rather than in CONFIG because
    // backend/hrcloudpay/tests_api_contract.py proves frontend API strings
    // against the real urlconf, and it only sees literals passed to api.get.
    // A lookup table would silently drop them out of that check.
    const request = type === 'employee'
      ? api.get('/employees/dashboard-summary/')
      : type === 'payroll'
        ? api.get('/payroll/dashboard/')
        : api.get('/leave/balances/').then((d) => ({ items: d.results ?? d ?? [] }));

    request
      .then((d) => {
        if (!cancelled) setSummary(d);
      })
      .catch((e) => {
        // Previously swallowed with .catch(() => {}), which left `summary`
        // null so the panel silently never appeared.
        if (!cancelled) setError(e.message || 'Could not load the operational summary.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [type, config.endpoint]);

  return (
    <div className="ops-hub">
      <div className="page-header">
        <div>
          <div className="eyebrow">{config.eyebrow}</div>
          <h1>{config.title}</h1>
          <p className="page-subtitle">{config.sub}</p>
        </div>
      </div>

      <div className="ops-links">
        {config.links.map(([to, label]) => (
          <Link className="card" to={to} key={to}>
            <strong>{label}</strong>
            <span>Open workspace →</span>
          </Link>
        ))}
      </div>

      {config.endpoint && (
        <div className="card">
          <div className="section-head">
            <div>
              <h2>Live operational signal</h2>
              <p>Connected to your existing HRCloudPay records.</p>
            </div>
          </div>
          {loading && <div className="page-loading">Loading summary…</div>}
          {!loading && error && <div className="alert alert-error">{error}</div>}
          {!loading && !error && <SummaryRows data={summary} />}
        </div>
      )}
    </div>
  );
}
