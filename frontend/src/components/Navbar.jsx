import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
import { api } from '../api/client';
import Icon from './Icon';

export default function Navbar({ onMenuClick, onSearchClick }) {
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const [count, setCount] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => {
    let alive = true;
    api.get('/workflows/notifications/unread_count/')
      .then((x) => alive && setCount(x.count || 0))
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const onDoc = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [menuOpen]);

  const initials = (user?.username || 'U').slice(0, 2).toUpperCase();
  const plan = user?.company?.plan || 'starter';

  return (
    <header className="navbar">
      <button type="button" className="icon-btn mobile-menu-btn" onClick={onMenuClick} aria-label="Open menu">
        <Icon name="menu" size={20} />
      </button>
      <div className="mobile-brand"><span className="brand-mark">H</span>HRCloudPay</div>

      <button type="button" className="navbar-search" onClick={onSearchClick}>
        <Icon name="search" size={17} />
        <span>Search employees, payroll, reports…</span>
        <kbd className="search-kbd">⌘K</kbd>
      </button>

      <div className="navbar-actions">
        <button type="button" className="icon-btn" onClick={toggle} title={theme === 'dark' ? 'Light mode' : 'Dark mode'} aria-label="Toggle theme">
          <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={18} />
        </button>
        <Link to="/workflows" className="icon-btn" title="Notifications">
          <Icon name="bell" />
          {count > 0 && <span className="notification-dot">{count > 99 ? '99+' : count}</span>}
        </Link>

        <div className="user-menu" ref={menuRef}>
          <button type="button" className="user-menu-trigger" onClick={() => setMenuOpen((v) => !v)} aria-expanded={menuOpen}>
            <div className="avatar">{initials}</div>
            <div className="user-meta">
              <strong>{user?.username || 'User'}</strong>
              <small>{user?.role?.replaceAll('_', ' ') || 'Member'} · {plan}</small>
            </div>
            <Icon name="chevron" size={14} />
          </button>
          {menuOpen && (
            <div className="user-dropdown">
              <div className="user-dropdown-header">
                <strong>{user?.username}</strong>
                <small>{user?.email || user?.company?.name}</small>
              </div>
              <Link to="/team" className="user-dropdown-item" onClick={() => setMenuOpen(false)}>
                <Icon name="user" size={16} /> Profile &amp; team
              </Link>
              <Link to="/billing" className="user-dropdown-item" onClick={() => setMenuOpen(false)}>
                <Icon name="wallet" size={16} /> Billing
              </Link>
                            <Link to="/payroll-setup" className="user-dropdown-item" onClick={() => setMenuOpen(false)}>
                <Icon name="settings" size={16} /> Payroll settings
              </Link>
              <Link to="/company-settings" className="user-dropdown-item" onClick={() => setMenuOpen(false)}>
                <Icon name="building" size={16} /> Company profile &amp; logo
              </Link>
              <button type="button" className="user-dropdown-item" onClick={() => { setMenuOpen(false); toggle(); }}>
                <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={16} />
                {theme === 'dark' ? 'Light mode' : 'Dark mode'}
              </button>
              <div className="user-dropdown-divider" />
              <button type="button" className="user-dropdown-item danger" onClick={() => { setMenuOpen(false); logout(); }}>
                <Icon name="logout" size={16} /> Log out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
