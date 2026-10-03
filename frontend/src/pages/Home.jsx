import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import useMarketingPage from '../hooks/useMarketingPage';
import { managedSection } from '../components/MarketingSections';

const CURRENCIES = ['GNF', 'NGN', 'GHS', 'SLL', 'LRD'];

// The hero is managed; everything below it is a bespoke layout with an animated
// workspace preview, so it stays in JSX. This constant is the fallback for when
// the content endpoint is unavailable.
const DEFAULT_HERO = {
  eyebrow: 'The intelligent operating system for people, payroll & HR',
  title: 'Run your people operations',
  title_accent: 'with clarity.',
  subtitle: 'HRCloudPay brings payroll, employee 360°, attendance, leave, compliance, documents, and an AI HR assistant into one secure workspace.',
  primary_cta: 'Start for free',
  primary_href: '/register',
  secondary_cta: 'Explore the platform',
  secondary_href: '/platform',
};

function HeroWorkspace() {
  const [i, setI] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setI((n) => (n + 1) % CURRENCIES.length), 2400);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="hc-hero-workspace">
      <div className="hc-windowbar"><span /><span /><span /><b>HRCloudPay workspace</b><em>Live preview</em></div>
      <div className="hc-workspace-body">
        <aside className="hc-mini-sidebar">
          <strong>HC</strong>
          <i>⌂</i><i>♙</i><i>▣</i><i>✓</i><i>◌</i>
        </aside>
        <div className="hc-workspace-main">
          <div className="hc-preview-header"><div><small>Good morning</small><h3>People operations</h3></div><span className="hc-avatar">HR</span></div>
          <div className="hc-metric-row">
            <div><small>Employees</small><strong>248</strong><span>+12 this quarter</span></div>
            <div><small>Payroll status</small><strong>Ready</strong><span>Review before approval</span></div>
            <div><small>AI assistant</small><strong>Online</strong><span>Company knowledge connected</span></div>
          </div>
          <div className="hc-preview-grid">
            <div className="hc-payroll-card">
              <div className="hc-card-head"><span>Payroll overview</span><b>{CURRENCIES[i]}</b></div>
              <strong>312,180</strong>
              <div className="hc-bars"><i /><i /><i /><i /><i /><i /><i /></div>
              <div className="hc-card-foot"><span>48 employees processed</span><em>Example data</em></div>
            </div>
            <div className="hc-ai-card">
              <div className="hc-ai-head"><span>✦</span><b>HRCloud AI</b><em>AI assistant</em></div>
              <div className="hc-chat user">Show me the leave policy for managers.</div>
              <div className="hc-chat bot">I found the current company policy and can explain the manager approval steps.</div>
              <div className="hc-source">▤ 1 verified company source</div>
            </div>
          </div>
        </div>
      </div>
      <p className="hc-hero-caption">
        Interactive preview. The figures are illustrative sample data, not a live account.
      </p>
    </div>
  );
}

const PILLARS = [
  ['01', 'Payroll', 'Run payroll with company-specific pay rules, review stages, statutory configuration, and a clear approval trail.', 'Payroll'],
  ['02', 'Employee 360°', 'Keep contracts, documents, warnings, attendance, leave, employment status, and history together.', 'HR'],
  ['03', 'AI HR assistant', 'Ask questions about your company’s HR knowledge and get grounded answers with source citations.', 'AI'],
  ['04', 'Document intelligence', 'Extract, organize, index, and search HR documents with page and section context.', 'Docs'],
  ['05', 'Compliance & audit', 'Make sensitive actions traceable with role-aware access, audit events, and compliance evidence.', 'Trust'],
  ['06', 'Connected operations', 'Create a foundation for integrations, reporting, multi-country workflows, and future automation.', 'Scale'],
];

const AI_FEATURES = [
  ['Ask', 'Natural-language HR questions', 'Ask about policies, employees, leave, attendance, contracts, and payroll information your role permits.'],
  ['Find', 'Search company knowledge', 'AI can use approved company documents and indexed knowledge instead of relying only on generic answers.'],
  ['Cite', 'See where answers came from', 'Knowledge-grounded responses can show the source document and context used to answer the question.'],
  ['Draft', 'Create HR drafts safely', 'Generate first drafts for common HR documents and explanations, then review before anything is used operationally.'],
];

const ROLES = [
  ['Founders & leaders', 'See people costs, payroll status, workforce changes, and operational signals without chasing spreadsheets.'],
  ['HR & People teams', 'Own employee records, contracts, documents, leave, attendance, policies, and day-to-day HR workflows.'],
  ['Finance teams', 'Control payroll preparation, review, approval, payment evidence, and reconciliation workflows.'],
  ['Managers & employees', 'Give each role a focused experience with the information and actions relevant to them.'],
];

const STEPS = [
  ['01', 'Set up your company', 'Choose your country context, currency, pay frequency, statutory configuration, roles, and access rules.'],
  ['02', 'Bring your people and knowledge', 'Add employees, contracts, HR documents, policies, and the company knowledge your teams need.'],
  ['03', 'Run payroll and HR together', 'Manage payroll, attendance, leave, documents, approvals, compliance, and employee self-service from one workspace.'],
];

export default function Home() {
  const managedPage = useMarketingPage('home');
  const managedHero = managedSection(managedPage, 'hero', DEFAULT_HERO);

  return (
    <>
      <section className="ledger-hero ledger-hero-upgraded hc-hero">
        <div className="ledger-hero-inner">
          <div className="ledger-hero-copy">
            <div className="ledger-eyebrow"><span className="ledger-eyebrow-mark" /> {managedHero.eyebrow}</div>
            <h1>{managedHero.title} <span>{managedHero.title_accent}</span></h1>
            <p className="ledger-hero-sub">{managedHero.subtitle}</p>
            <div className="ledger-hero-actions">
              <Link className="ledger-btn ledger-btn-gold" to="/register">{managedHero.primary_cta} <span>→</span></Link>
              <Link className="ledger-btn ledger-btn-outline" to="/platform">{managedHero.secondary_cta}</Link>
            </div>
            <div className="hc-hero-trust"><span>✓ AI-assisted HR</span><span>✓ Employee 360°</span><span>✓ Payroll &amp; compliance</span><span>✓ Role-based access</span></div>
          </div>
          <HeroWorkspace />
        </div>
      </section>

      <section className="hc-positioning-strip">
        <div><span>One workspace</span><b>People</b><i>+</i><b>Payroll</b><i>+</i><b>AI</b><i>+</i><b>Knowledge</b><i>+</i><b>Compliance</b></div>
      </section>

      <section className="ledger-proof-section hc-problem-section">
        <div className="ledger-proof-inner">
          <div className="ledger-proof-heading"><div className="ledger-eyebrow">Why HRCloudPay</div><h2>Stop managing people operations in disconnected systems.</h2><p>HR teams need more than payroll software. They need a dependable operating layer where employee information, policies, documents, payroll, and decisions stay connected.</p></div>
          <div className="hc-problem-grid">
            <article><span>Before</span><h3>Spreadsheets everywhere</h3><p>Employee records, leave, contracts, payroll inputs, and policy documents live in different places.</p></article>
            <article><span>With HRCloudPay</span><h3>One operating record</h3><p>Your company has a shared HR workspace with role-aware access and a traceable history.</p></article>
            <article><span>With AI</span><h3>Answers without the hunt</h3><p>Ask questions, search approved knowledge, and surface relevant HR context without manually opening every document.</p></article>
          </div>
        </div>
      </section>

      <section className="ledger-section ledger-capabilities-section hc-pillars-section">
        <div className="ledger-section-head ledger-section-head-wide"><div className="ledger-eyebrow">The HRCloudPay platform</div><h2>Everything your people team needs — with intelligence built into the workflow.</h2><p>Start with the operational essentials, then add deeper AI and knowledge capabilities as your organization grows.</p></div>
        <div className="ledger-capabilities-grid hc-pillars-grid">
          {PILLARS.map(([number, title, description, tag]) => <article className="ledger-capability-card hc-pillar-card" key={title}><div className="hc-pillar-top"><span className="ledger-capability-number">{number}</span><em>{tag}</em></div><h3>{title}</h3><p>{description}</p></article>)}
        </div>
      </section>

      <section className="hc-ai-section">
        <div className="hc-ai-inner">
          <div className="hc-ai-copy">
            <div className="ledger-eyebrow hc-eyebrow-light">Introducing HRCloud AI</div>
            <h2>Your HR knowledge, available through a conversation.</h2>
            <p>Give your team a faster way to find company-specific answers. HRCloud AI combines controlled HR tools with approved company knowledge, while permissions and human review remain part of the workflow.</p>
            <div className="hc-ai-actions"><Link className="ledger-btn ledger-btn-gold" to="/platform">Explore AI capabilities →</Link><Link className="hc-light-link" to="/security">See security approach</Link></div>
          </div>
          <div className="hc-ai-features">
            {AI_FEATURES.map(([label, title, description]) => <article key={label}><span>{label}</span><div><h3>{title}</h3><p>{description}</p></div></article>)}
          </div>
        </div>
      </section>

      <section className="ledger-section hc-docs-section">
        <div className="hc-docs-layout">
          <div className="hc-docs-visual">
            <div className="hc-doc-window"><div className="hc-doc-top"><span>Employee Handbook.pdf</span><b>ACTIVE · v3</b></div><div className="hc-doc-content"><div className="hc-doc-lines"><i/><i/><i/><i/><i/><i/><i/></div><div className="hc-doc-highlight"><small>AI EXTRACTED</small><strong>Leave approval process</strong><span>Section 4 · Manager responsibilities</span></div></div><div className="hc-doc-footer"><span>✓ Indexed</span><span>Page 12</span><span>Role access: HR · Manager</span></div></div>
          </div>
          <div className="ledger-section-head hc-docs-copy"><div className="ledger-eyebrow">AI document intelligence</div><h2>Turn HR documents into usable company knowledge.</h2><p>Upload policies, handbooks, contracts, and other supported documents. HRCloudPay can extract content, preserve page and section context, create searchable knowledge, and manage document versions and access.</p><ul><li><b>Lifecycle control</b><span>Active, processing, failed, and archived states.</span></li><li><b>Version awareness</b><span>Keep historical versions while making the current version clear.</span></li><li><b>Role-based knowledge</b><span>Control which roles can retrieve a document through AI.</span></li></ul><Link className="ledger-text-link" to="/platform">Explore the platform →</Link></div>
        </div>
      </section>

      <section className="ledger-section ledger-workflow-section hc-roles-section">
        <div className="ledger-section-head"><div className="ledger-eyebrow">Built for every role</div><h2>One platform. Different views for the people who use it.</h2><p>HRCloudPay keeps the underlying company record connected while showing each role the information and actions it is responsible for.</p></div>
        <div className="hc-role-grid">{ROLES.map(([title, description], index) => <article key={title}><span>0{index + 1}</span><h3>{title}</h3><p>{description}</p></article>)}</div>
      </section>

      <section className="ledger-section hc-trust-section">
        <div className="hc-trust-layout"><div className="ledger-section-head"><div className="ledger-eyebrow">Security &amp; governance</div><h2>AI that fits inside your HR controls.</h2><p>AI should help your team work faster without becoming an uncontrolled path to sensitive employee or payroll information.</p><Link className="ledger-text-link" to="/security">Explore security &amp; trust →</Link></div><div className="hc-trust-list"><div><b>Tenant-scoped data</b><span>Company information stays within the appropriate company context.</span></div><div><b>Role-aware access</b><span>Knowledge retrieval follows the access roles configured for the document.</span></div><div><b>Human review</b><span>AI-generated HR drafts are designed for review before operational use.</span></div><div><b>Auditability</b><span>Sensitive HR and payroll actions can remain traceable through the platform.</span></div></div></div>
      </section>

      <section className="ledger-section ledger-steps-section hc-steps-section">
        <div className="ledger-section-head"><div className="ledger-eyebrow">A practical rollout</div><h2>Start with the essentials. Add intelligence as you grow.</h2><p>Build a useful HR operating system without needing to transform everything on day one.</p></div>
        <div className="ledger-steps">{STEPS.map(([number, title, description]) => <article className="ledger-step" key={number}><span className="ledger-step-number">{number}</span><div><h3>{title}</h3><p>{description}</p></div></article>)}</div>
      </section>

      <section className="ledger-section-dark ledger-future-section hc-future-section">
        <div className="ledger-section"><div className="ledger-section-head"><div className="ledger-eyebrow">Built for what comes next</div><h2>From payroll software to your company’s operating layer.</h2><p>HRCloudPay is designed to expand with your business — from core HR and payroll into knowledge, integrations, reporting, and multi-country operations.</p></div><div className="ledger-future-grid"><div><b>AI-native</b><span>Bring conversational assistance and company knowledge into everyday HR work.</span></div><div><b>Multi-country ready</b><span>Keep each company’s currency, pay rules, contributions, and schedules in context.</span></div><div><b>Integration-friendly</b><span>Connect finance and operational systems as your organization grows.</span></div><div><b>Insight-ready</b><span>Turn people and payroll records into the reports leaders need.</span></div></div></div>
      </section>

      <section className="ledger-cta ledger-cta-upgraded hc-final-cta"><div className="ledger-cta-inner"><div><div className="ledger-eyebrow">Your next operating advantage</div><h2>Make HR, payroll, and company knowledge work together.</h2><p>Start building a clearer way to run your people operations.</p></div><div className="ledger-cta-actions"><Link className="ledger-btn ledger-btn-gold" to="/register">Start for free</Link><Link className="ledger-btn ledger-btn-outline-dark" to="/pricing">View pricing</Link></div></div></section>
    </>
  );
}
