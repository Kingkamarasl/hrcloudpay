import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import Icon from './Icon';

const PAGES = [
  { id: 'dashboard', label: 'Dashboard', to: '/dashboard', icon: 'grid', keywords: 'home overview' },
  { id: 'employees', label: 'Employees', to: '/employees', icon: 'users', keywords: 'staff people' },
  { id: 'departments', label: 'Departments', to: '/departments', icon: 'building', keywords: 'teams org' },
  { id: 'attendance', label: 'Attendance', to: '/attendance', icon: 'clock', keywords: 'time clock' },
  { id: 'leave', label: 'Leave & breaks', to: '/leave', icon: 'calendar', keywords: 'time off vacation' },
  { id: 'payroll', label: 'Payroll runs', to: '/payroll', icon: 'wallet', keywords: 'salary pay' },
  { id: 'payroll-dashboard', label: 'Payroll analytics', to: '/payroll-dashboard', icon: 'trend', keywords: 'reports' },
  { id: 'payroll-setup', label: 'Payroll settings', to: '/payroll-setup', icon: 'settings', keywords: 'tax config' },
  { id: 'compliance', label: 'Compliance', to: '/compliance', icon: 'shield', keywords: 'documents rules' },
  { id: 'integrations', label: 'Integrations', to: '/integrations', icon: 'settings', keywords: 'import sync oauth' },
  { id: 'workflows', label: 'Workflows & notifications', to: '/workflows', icon: 'bell', keywords: 'tasks alerts' },
  { id: 'team', label: 'Team accounts', to: '/team', icon: 'users', keywords: 'invite users roles' },
  { id: 'billing', label: 'Billing & subscription', to: '/billing', icon: 'wallet', keywords: 'plan payment' },
  { id: 'audit', label: 'Audit trail', to: '/audit-logs', icon: 'shield', keywords: 'logs history' },
  { id: 'platform', label: 'Platform admin', to: '/platform-admin', icon: 'settings', keywords: 'admin companies', staffOnly: true },
];

export default function CommandPalette({ open, onClose }) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const inputRef = useRef(null);

  const items = useMemo(() => {
    const q = query.trim().toLowerCase();
    return PAGES.filter((p) => {
      if (p.staffOnly && !(user?.is_staff || user?.is_superuser)) return false;
      if (!q) return true;
      return (
        p.label.toLowerCase().includes(q) ||
        p.keywords.includes(q) ||
        p.to.includes(q)
      );
    });
  }, [query, user]);

  useEffect(() => {
    if (open) {
      setQuery('');
      setActive(0);
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);

  useEffect(() => {
    setActive(0);
  }, [query]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActive((i) => Math.min(i + 1, items.length - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActive((i) => Math.max(i - 1, 0));
      } else if (e.key === 'Enter' && items[active]) {
        e.preventDefault();
        go(items[active]);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, items, active, onClose]);

  function go(item) {
    if (!item) return;
    navigate(item.to);
    onClose();
  }

  if (!open) return null;

  return (
    <div className="modal-overlay command-overlay" onClick={onClose} role="presentation">
      <div
        className="command-palette"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="command-input-row">
          <Icon name="search" size={18} />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search pages, actions…"
            aria-label="Search"
          />
          <kbd>esc</kbd>
        </div>
        <ul className="command-list">
          {items.length === 0 && (
            <li className="command-empty">No matches for “{query}”</li>
          )}
          {items.map((item, i) => (
            <li key={item.id}>
              <button
                type="button"
                className={`command-item ${i === active ? 'active' : ''}`}
                onMouseEnter={() => setActive(i)}
                onClick={() => go(item)}
              >
                <Icon name={item.icon} size={16} />
                <span>{item.label}</span>
                <small>{item.to}</small>
              </button>
            </li>
          ))}
        </ul>
        <div className="command-footer">
          <span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
          <span><kbd>↵</kbd> open</span>
          <span><kbd>esc</kbd> close</span>
        </div>
      </div>
    </div>
  );
}
