import { Link } from 'react-router-dom';
import useMarketingPage from '../hooks/useMarketingPage';
import { managedSection } from '../components/MarketingSections';

// Kept as the fallback: the hero is managed, but the rest of this page is a
// bespoke layout, so if the content endpoint is unavailable the page still
// renders the copy that shipped with it rather than an empty shell.
const DEFAULT_SECURITY_HERO = { eyebrow: 'Security & Trust', title: 'Enterprise control without enterprise complexity.', subtitle: 'HRCloudPay gives growing companies role-aware access, immutable auditability, controlled payroll workflows, and a clear compliance trail from employee record to payment evidence.' };

const CONTROLS = [
  ['01', 'Immutable audit trail', 'Sensitive actions are recorded with the actor, company, target, timestamp, IP context, and structured metadata. Audit records are protected from casual editing or deletion.'],
  ['02', 'Role-aware access', 'Owners, administrators, HR, Finance, Department Managers, Employees, and Platform Administrators each receive purpose-built access boundaries.'],
  ['03', 'Tenant isolation', 'Company workspaces keep employee, payroll, attendance, leave, compliance, and integration data scoped to the organization that owns it.'],
  ['04', 'Controlled statutory workflow', 'Filing obligations move through review, approval, payment evidence, submission, and close — with checks at every critical transition.'],
  ['05', 'Compliance evidence', 'Payroll-to-obligation reconciliation, filing calendars, country reports, compliance packs, and document alerts keep operational evidence together.'],
  ['06', 'Protected integrations', 'Integration secrets are encrypted and managed separately from operational records. Banking credentials are not stored in HRCloudPay.'],
];

const GOVERNANCE = [
  ['Access boundaries', 'Finance can manage payroll without unrestricted employee-record access. Department Managers stay scoped to their own teams. Employees see their own self-service records.'],
  ['Payment controls', 'Statutory payment evidence includes amount, payment date, method, transaction reference, receipt reference, and notes. Submitted evidence cannot be overwritten.'],
  ['Operational visibility', 'Compliance dashboards surface missing documents, expiry risk, filing deadlines, overdue obligations, and reconciliation mismatches.'],
];

export default function Security() {
  const managedPage = useMarketingPage('security');
  const hero = managedSection(managedPage, 'hero', DEFAULT_SECURITY_HERO);
  return (
    <>
      <section className="ledger-security-hero">
        <div className="ledger-security-hero-inner">
          <div className="ledger-eyebrow">{hero.eyebrow}</div>
          <h1>{hero.title}</h1>
          <p>{hero.subtitle}</p>
          <div className="ledger-inner-hero-actions"><Link className="ledger-btn ledger-btn-gold" to="/register">Build your workspace</Link><Link className="ledger-btn ledger-btn-outline" to="/pricing">View plans</Link></div>
        </div>
      </section>

      <section className="ledger-section ledger-security-intro"><div className="ledger-section-head"><div className="ledger-eyebrow">Controls that work in the flow of work</div><h2>Security is not a separate screen. It is part of every important action.</h2><p>From a new employee record to a statutory payment, HRCloudPay keeps responsibility, evidence, and approval close to the workflow itself.</p></div></section>

      <section className="ledger-security-controls"><div className="ledger-security-controls-inner"><div className="ledger-security-control-grid">{CONTROLS.map(([number, title, description]) => <article className="ledger-security-control" key={title}><span>{number}</span><h3>{title}</h3><p>{description}</p></article>)}</div></div></section>

      <section className="ledger-section ledger-security-governance"><div className="ledger-section-head"><div className="ledger-eyebrow">Built for due diligence</div><h2>Clear answers for HR, Finance, IT, and compliance teams.</h2><p>Corporate buyers need more than a security badge. They need to see how controls behave when people, money, and regulatory obligations meet.</p></div><div className="ledger-security-governance-grid">{GOVERNANCE.map(([title, description]) => <div key={title}><h3>{title}</h3><p>{description}</p></div>)}</div></section>

      <section className="ledger-section-dark ledger-security-next"><div className="ledger-section"><div className="ledger-section-head"><div className="ledger-eyebrow">Our enterprise path</div><h2>Growing the trust layer as our customers grow.</h2><p>HRCloudPay covers multi-factor authentication, single sign-on, security administration and data-retention controls today, and is building toward a customer Trust Center.</p></div><div className="ledger-security-roadmap"><span>Available today</span><span>Auditability</span><span>Role-based access</span><span>Statutory controls</span><span>Compliance evidence</span><span>Multi-factor authentication</span><span>Single sign-on</span><span>Security administration</span><span>Next on the roadmap</span><span>Retention controls</span><span>Customer Trust Center</span></div></div></section>

      <section className="ledger-cta ledger-security-cta"><div className="ledger-cta-inner"><div><div className="ledger-eyebrow">Start with control</div><h2>Give your teams a safer way to run people and payroll.</h2></div><div className="ledger-cta-actions"><Link className="ledger-btn ledger-btn-gold" to="/register">Get started free</Link><Link className="ledger-btn ledger-btn-outline-dark" to="/about">Why HRCloudPay</Link></div></div></section>
    </>
  );
}
