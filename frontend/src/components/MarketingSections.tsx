// Public renderer for platform-managed marketing content.
//
// Every section type the backend accepts has a `case` here, and the backend
// rejects any type that does not. `tests_marketing_schema.py` asserts that
// agreement in both directions, so adding a type to one half without the other
// fails the suite rather than shipping a page with a silent hole in it.
//
// Content describes *copy and section order*, never layout or styling. Each
// landing page keeps its own design in JSX; this decides which sections appear
// and what they say. That is deliberate - it means a typo in the content system
// cannot restyle the site, and a redesign stays a code change rather than
// something an admin can do by accident.
//
// Safe-link note: hrefs were scheme-checked on write, so `/...`, `#...` and
// `https://...` are the only values that can reach this component. That is what
// makes rendering them as links safe. It is a write-time guarantee, so these
// components do not repeat the check.

import type { ReactNode } from 'react';

/** A managed section. Field sets vary per `type`, so this is intentionally permissive. */
export interface ManagedSection {
  type?: string;
  eyebrow?: string;
  title?: string;
  title_accent?: string;
  subtitle?: string;
  body?: string;
  primary_cta?: string;
  primary_href?: string;
  secondary_cta?: string;
  secondary_href?: string;
  items?: Array<Record<string, string | undefined>>;
  blocks?: Array<{ title?: string; body?: string }>;
  plans?: Array<{
    name?: string;
    price?: string;
    blurb?: string;
    highlight?: boolean;
    features?: string[];
  }>;
  notes?: Array<{ title?: string; body?: string }>;
  actions?: Array<{ label?: string; href?: string }>;
  [key: string]: unknown;
}

export interface ManagedContent {
  sections?: ManagedSection[];
  [key: string]: unknown;
}

interface ManagedLinkProps {
  href?: string;
  className?: string;
  children: ReactNode;
}

// Internal links go through the router so the SPA does not reload. External
// links get rel="noopener noreferrer" because a managed link can point at
// another origin, and target="_blank" without it hands that page a live
// reference to this one.
function ManagedLink({ href, className, children }: ManagedLinkProps) {
  if (!href) return null;
  const internal = href.startsWith('/');
  if (internal) {
    return <a className={className} href={href}>{children}</a>;
  }
  return (
    <a className={className} href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

function Hero({ section }: { section: ManagedSection }) {
  const {
    eyebrow, title, title_accent: accent, subtitle,
    primary_cta: primaryCta, primary_href: primaryHref,
    secondary_cta: secondaryCta, secondary_href: secondaryHref,
  } = section;
  return (
    <section className="ledger-inner-hero">
      <div className="ledger-inner-hero-inner">
        {eyebrow && <div className="ledger-eyebrow">{eyebrow}</div>}
        <h1>{title}{accent && <> <span>{accent}</span></>}</h1>
        {subtitle && <p>{subtitle}</p>}
        {(primaryCta || secondaryCta) && (
          <div className="ledger-inner-hero-actions">
            {primaryCta && (
              <ManagedLink className="ledger-btn ledger-btn-gold" href={primaryHref}>
                {primaryCta}
              </ManagedLink>
            )}
            {secondaryCta && (
              <ManagedLink className="ledger-btn ledger-btn-outline" href={secondaryHref}>
                {secondaryCta}
              </ManagedLink>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

function FeatureRows({ section }: { section: ManagedSection }) {
  const { eyebrow, title, subtitle, items } = section;
  const rows = items || [];
  if (!rows.length) return null;
  return (
    <section className="ledger-section">
      {(eyebrow || title || subtitle) && (
        <div className="ledger-section-head">
          {eyebrow && <div className="ledger-eyebrow">{eyebrow}</div>}
          {title && <h2>{title}</h2>}
          {subtitle && <p>{subtitle}</p>}
        </div>
      )}
      <div className="ledger-features">
        {rows.map((item, index) => (
          <div className="ledger-feature-row" key={`${item.title}-${index}`}>
            <h3>{item.title}</h3>
            {item.body && <p>{item.body}</p>}
          </div>
        ))}
      </div>
    </section>
  );
}

function Checklist({ section }: { section: ManagedSection }) {
  const { eyebrow, title, body, items } = section;
  const rows = items || [];
  if (!rows.length) return null;
  return (
    <section className="ledger-section">
      {eyebrow && <div className="ledger-eyebrow">{eyebrow}</div>}
      {title && <h2>{title}</h2>}
      {body && <p className="ledger-checklist-intro">{body}</p>}
      <ul className="ledger-checklist">
        {rows.map((item, index) => (
          <li key={`${item.label}-${index}`}>{item.label}</li>
        ))}
      </ul>
    </section>
  );
}

function ProseBlocks({ section }: { section: ManagedSection }) {
  const { eyebrow, blocks } = section;
  const rows = blocks || [];
  if (!rows.length) return null;
  return (
    <div className="ledger-about-body">
      {eyebrow && <div className="ledger-eyebrow">{eyebrow}</div>}
      {rows.map((block, index) => (
        <div className="ledger-about-block" key={`${block.title}-${index}`}>
          {block.title && <h2>{block.title}</h2>}
          {block.body && <p>{block.body}</p>}
        </div>
      ))}
    </div>
  );
}

function Pricing({ section }: { section: ManagedSection }) {
  const { title, subtitle, plans, notes } = section;
  const rows = plans || [];
  if (!rows.length) return null;
  return (
    <>
      {(title || subtitle) && (
        <div className="ledger-pricing-hero">
          <div className="ledger-pricing-hero-inner">
            {section.eyebrow && <div className="ledger-eyebrow">{section.eyebrow}</div>}
            {title && <h1>{title}</h1>}
            {subtitle && <p>{subtitle}</p>}
          </div>
        </div>
      )}
      <div className="ledger-pricing-table">
        <div className="ledger-pricing-grid">
          {rows.map((plan, index) => (
            <div
              className={`ledger-plan${plan.highlight ? ' ledger-plan-featured' : ''}`}
              key={`${plan.name}-${index}`}
            >
              <h3>{plan.name}</h3>
              <div className="ledger-plan-price">
                {plan.price}
                {plan.price && plan.price !== 'Custom' && <span>/month</span>}
              </div>
              {plan.blurb && <p className="ledger-plan-blurb">{plan.blurb}</p>}
              <ul className="ledger-plan-features">
                {(plan.features || []).map((feature, f) => (
                  <li key={`${feature}-${f}`}>{feature}</li>
                ))}
              </ul>
              <ManagedLink
                className={`ledger-btn ${plan.highlight ? 'ledger-btn-gold' : 'ledger-btn-dark'}`}
                href={`/register?plan=${String(plan.name || '').toLowerCase()}`}
              >
                {plan.price === 'Custom' ? 'Talk to us' : 'Get started'}
              </ManagedLink>
            </div>
          ))}
        </div>
      </div>
      {notes && notes.length > 0 && (
        <div className="ledger-pricing-note">
          <div className="ledger-pricing-note-inner">
            {notes.map((note, index) => (
              <div key={`${note.title}-${index}`}>
                {note.title && <h4>{note.title}</h4>}
                {note.body && <p>{note.body}</p>}
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

function Cta({ section }: { section: ManagedSection }) {
  const { eyebrow, title, actions } = section;
  const buttons = (actions || []).filter((action) => action.label);
  if (!buttons.length) return null;
  return (
    <section className="ledger-cta">
      <div className="ledger-cta-inner">
        <div>
          {eyebrow && <div className="ledger-eyebrow">{eyebrow}</div>}
          {title && <h2>{title}</h2>}
        </div>
        <div className="ledger-cta-actions">
          {buttons.map((action, index) => (
            <ManagedLink
              key={`${action.label}-${index}`}
              // First button is the primary action; the rest are secondary.
              // Style is not managed content - the design owns it.
              className={`ledger-btn ${index === 0 ? 'ledger-btn-dark' : 'ledger-btn-outline-dark'}`}
              href={action.href}
            >
              {action.label}
            </ManagedLink>
          ))}
        </div>
      </div>
    </section>
  );
}

export function MarketingSection({ section }: { section: ManagedSection }) {
  switch (section.type) {
    case 'hero':
      return <Hero section={section} />;
    case 'feature_rows':
      return <FeatureRows section={section} />;
    case 'checklist':
      return <Checklist section={section} />;
    case 'prose_blocks':
      return <ProseBlocks section={section} />;
    case 'pricing':
      return <Pricing section={section} />;
    case 'cta':
      return <Cta section={section} />;
    default:
      // Unreachable: the backend refuses unknown types on write, and the parity
      // test fails if a case is removed here while the backend still sends it.
      return null;
  }
}

interface MarketingSectionsProps {
  content?: ManagedContent;
  only?: string[];
}

// Renders a page's sections in the order the admin arranged them. This is what
// makes reordering a real operation rather than a cosmetic one.
export function MarketingSections({ content, only }: MarketingSectionsProps) {
  const sections = (content && content.sections) || [];
  const visible = only
    ? sections.filter((section) => only.includes(section.type || ''))
    : sections;
  if (!visible.length) return null;
  return (
    <>
      {visible.map((section, index) => (
        <MarketingSection key={`${section.type}-${index}`} section={section} />
      ))}
    </>
  );
}

function sectionsOf(content?: ManagedContent): ManagedSection[] {
  return (content && content.sections) || [];
}

// The first section of a given type, spread over a set of defaults. Used by
// `home` and `security`, which manage their hero but keep bespoke layouts for
// everything below it, so a page with no managed content still renders the copy
// that shipped in its JSX.
export function managedSection(
  content: ManagedContent | undefined,
  type: string,
  defaults: ManagedSection,
): ManagedSection {
  const section = (sectionsOf(content) || []).find((s) => s.type === type) || {};
  return { ...defaults, ...section };
}