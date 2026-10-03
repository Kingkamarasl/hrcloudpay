import { Link, NavLink, Outlet } from 'react-router-dom';
import { useState } from 'react';
import { useAuth } from '../context/AuthContext';

export default function MarketingLayout() {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);

  return (
    <div className="ledger-page">
      <header className="ledger-nav">
        <Link to="/" className="ledger-brand" onClick={close}>
          <span className="ledger-brand-mark">HC</span>
          HRCloudPay
        </Link>

        <button className="ledger-mobile-toggle" aria-label="Open menu" onClick={() => setOpen(!open)}>
          {open ? '×' : '☰'}
        </button>

        <nav className={`ledger-nav-links ${open ? 'is-open' : ''}`}>
          <NavLink to="/platform" onClick={close}>Platform</NavLink>
          <NavLink to="/payroll-product" onClick={close}>Payroll</NavLink>
          <NavLink to="/hr" onClick={close}>HR</NavLink>
          <NavLink to="/pricing" onClick={close}>Pricing</NavLink>
          <NavLink to="/security" onClick={close}>Security</NavLink>
          <NavLink to="/about" onClick={close}>Why HRCloudPay</NavLink>
        </nav>

        <div className="ledger-nav-cta">
          {user ? (
            <Link className="ledger-btn ledger-btn-dark" to="/dashboard">Open dashboard</Link>
          ) : (
            <>
              <Link className="ledger-loginlink" to="/login">Log in</Link>
              <Link className="ledger-btn ledger-btn-gold" to="/register">Get started</Link>
            </>
          )}
        </div>
      </header>

      <main><Outlet /></main>

      <footer className="ledger-footer">
        <div className="ledger-footer-inner">
          <div className="ledger-footer-brand">
            <Link to="/" className="ledger-brand" style={{ color: 'white' }}>
              <span className="ledger-brand-mark">HC</span>
              HRCloudPay
            </Link>
            <p>The operating layer for people, payroll, and compliance — built for ambitious businesses across Africa.</p>
          </div>
          <div className="ledger-footer-col">
            <strong>Platform</strong>
            <Link to="/platform">Overview</Link>
            <Link to="/payroll-product">Payroll</Link>
            <Link to="/hr">HR management</Link>
            <Link to="/security">Security &amp; Trust</Link>
          </div>
          <div className="ledger-footer-col">
            <strong>Why HRCloudPay</strong>
            <Link to="/about">Our approach</Link>
            <Link to="/pricing">Pricing</Link>
            <Link to="/register">Get started</Link>
          </div>
          <div className="ledger-footer-col">
            <strong>Account</strong>
            <Link to="/login">Log in</Link>
            <Link to="/register">Create account</Link>
          </div>
        </div>
        <div className="ledger-footer-bottom">© {new Date().getFullYear()} HRCloudPay. All rights reserved.</div>
      </footer>
    </div>
  );
}