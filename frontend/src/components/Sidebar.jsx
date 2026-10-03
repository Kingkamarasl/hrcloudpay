import { NavLink, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { KNOWLEDGE_MANAGER_ROLES } from '../constants/roles';
import Icon from './Icon';

const GROUPS = [
  { title: 'Overview', links: [
    { to: '/dashboard', label: 'Dashboard', icon: 'grid', end: true },
    { to: '/ai', label: 'AI Copilot', icon: 'sparkles' },
    { to: '/knowledge', label: 'Knowledge Center', icon: 'file', roles: KNOWLEDGE_MANAGER_ROLES },
  ] },
  { title: 'People', links: [
    { to: '/employees', label: 'Employees', icon: 'users', roles: ['owner','admin','hr','department_manager','employee'] },
    { to: '/request-tracking', label: 'Request tracking', icon: 'bell', roles: ['owner','admin','hr','department_manager','employee'] },
    { to: '/departments', label: 'Departments', icon: 'building', roles: ['owner','admin','hr','department_manager'] },
    { to: '/compliance', label: 'Compliance', icon: 'shield', roles: ['owner','admin','hr','department_manager'] },
    { to: '/workflows', label: 'Workflows', icon: 'bell', roles: ['owner','admin','hr'] },
    { to: '/team', label: 'Team accounts', icon: 'users', roles: ['owner','admin'] },
  ]},
  { title: 'Billing', links: [{ to: '/billing', label: 'Billing & subscription', icon: 'wallet', roles: ['owner','admin'] }]},
  { title: 'Integrations', links: [{ to: '/integrations', label: 'Integrations & migration', icon: 'settings', roles: ['owner','admin','hr'] }]},
  { title: 'Regional setup', links: [
    { to: '/country-setup', label: 'Country setup', icon: 'globe', roles: ['owner','admin','hr'] },
    { to: '/statutory-compliance', label: 'Statutory filings', icon: 'calendar', roles: ['owner','admin','finance','hr'] },
  ]},
  { title: 'Security', links: [{ to: '/security-center', label: 'Security Center', icon: 'shield', roles: ['owner','admin'] }] },
  { title: 'Operations', links: [
    { to: '/attendance', label: 'Attendance', icon: 'clock' },
    { to: '/leave-accrual', label: 'Leave accruals', icon: 'calendar', roles: ['owner','admin','hr'] },
    { to: '/leave', label: 'Leave & breaks', icon: 'calendar' },
    { to: '/audit-logs', label: 'Audit trail', icon: 'shield', roles: ['owner','admin','hr','finance'] },
  ]},
  { title: 'Payroll', links: [
    { to: '/payroll', label: 'Payroll runs', icon: 'wallet', roles: ['owner','admin','finance'] },
    { to: '/payroll-dashboard', label: 'Payroll analytics', icon: 'trend', roles: ['owner','admin','finance'] },
    { to: '/payroll-setup', label: 'Payroll settings', icon: 'settings', roles: ['owner','admin','finance'] },
    { to: '/payroll-extras', label: 'Overtime & advances', icon: 'clock', roles: ['owner','admin','finance'] },
  ]},
];

export default function Sidebar({ onNavigate }) {
  const { user } = useAuth();
  const role = user?.role;

  function handleNav() {
    onNavigate?.();
  }

  return (
    <aside className="sidebar">
      <Link to="/" className="brand" onClick={handleNav}>
        <span className="brand-mark">H</span>
        <span>HR<span>CloudPay</span></span>
      </Link>
            <div className="workspace">
        {user?.company?.logo_url ? (
          <img className="workspace-logo" src={user?.company?.logo_url} alt={`${user?.company?.name} logo`} />
        ) : (
          <div className="workspace-avatar">{(user?.company?.name || 'C').slice(0, 1).toUpperCase()}</div>
        )}
        <div>
          <strong>{user?.company?.name || 'Your company'}</strong>
          <small>{user?.company?.plan || 'Workspace'}</small>
        </div>
      </div>
      <nav className="sidebar-nav">
        {GROUPS.map((group) => (
          <div className="nav-group" key={group.title}>
            <div className="nav-label">{group.title}</div>
            {group.links
              .filter((l) => !l.roles || l.roles.includes(role))
              .map((link) => (
                <NavLink
                  key={link.to}
                  to={link.to}
                  end={link.end}
                  className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
                  onClick={handleNav}
                >
                  <Icon name={link.icon} />
                  <span>{link.label}</span>
                </NavLink>
              ))}
          </div>
        ))}
      </nav>
      {user?.is_staff && (
        <div className="nav-group platform-nav-group">
          <div className="nav-label">Platform</div>
          <NavLink
            to="/platform-admin"
            className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
            onClick={handleNav}
          >
            <Icon name="settings" />
            <span>Platform admin</span>
          </NavLink>
        </div>
      )}
      <div className="sidebar-bottom">
        <NavLink to="/billing" className="sidebar-link" onClick={handleNav}>
          <Icon name="wallet" />
          <span>Plans &amp; billing</span>
        </NavLink>
        <div className="upgrade-card">
          <strong>Ready to grow?</strong>
          <p>Unlock more HRCloudPay features as your team grows.</p>
          <Link to="/pricing" onClick={handleNav}>
            View plans <Icon name="arrow" size={14} />
          </Link>
        </div>
      </div>
    </aside>
  );
}
