import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

// Kept in step with `COUNTRY_CHOICES` in `regional/models.py` and
// `COUNTRY_PACKS` in `regional/countries/registry.py`. All fifty-four African
// UN member states are selectable: the packs that ship without verified
// statutory rates do not block signup, they block payroll *approval* with a gap
// that names exactly which scheme is missing. Refusing the country at
// registration would hide that, and would make the country look unsupported in
// the list and unusable in the product.
//
// Western Sahara is deliberately absent. It is not a UN member state and has
// no separate statutory authority HRCloudPay could file with, so listing it
// would be a claim the product cannot back.
const COUNTRY_OPTIONS = [
  ['AO', 'Angola'],
  ['BF', 'Burkina Faso'],
  ['BI', 'Burundi'],
  ['BJ', 'Benin'],
  ['BW', 'Botswana'],
  ['CD', 'DR Congo'],
  ['CF', 'Central African Republic'],
  ['CG', 'Republic of the Congo'],
  ['CI', "Côte d'Ivoire"],
  ['CM', 'Cameroon'],
  ['CV', 'Cabo Verde'],
  ['DJ', 'Djibouti'],
  ['DZ', 'Algeria'],
  ['EG', 'Egypt'],
  ['ER', 'Eritrea'],
  ['ET', 'Ethiopia'],
  ['GA', 'Gabon'],
  ['GH', 'Ghana'],
  ['GM', 'The Gambia'],
  ['GN', 'Guinea'],
  ['GQ', 'Equatorial Guinea'],
  ['GW', 'Guinea-Bissau'],
  ['KE', 'Kenya'],
  ['KM', 'Comoros'],
  ['LR', 'Liberia'],
  ['LS', 'Lesotho'],
  ['LY', 'Libya'],
  ['MA', 'Morocco'],
  ['MG', 'Madagascar'],
  ['ML', 'Mali'],
  ['MR', 'Mauritania'],
  ['MU', 'Mauritius'],
  ['MW', 'Malawi'],
  ['MZ', 'Mozambique'],
  ['NA', 'Namibia'],
  ['NE', 'Niger'],
  ['NG', 'Nigeria'],
  ['RW', 'Rwanda'],
  ['SC', 'Seychelles'],
  ['SD', 'Sudan'],
  ['SL', 'Sierra Leone'],
  ['SN', 'Senegal'],
  ['SO', 'Somalia'],
  ['SS', 'South Sudan'],
  ['ST', 'São Tomé and Príncipe'],
  ['SZ', 'Eswatini'],
  ['TD', 'Chad'],
  ['TG', 'Togo'],
  ['TN', 'Tunisia'],
  ['TZ', 'Tanzania'],
  ['UG', 'Uganda'],
  ['ZA', 'South Africa'],
  ['ZM', 'Zambia'],
  ['ZW', 'Zimbabwe'],
];

// Subregions follow the UN M49 geographic classification. Grouping is a
// scanning aid only - search spans every group, so a wrong grouping can never
// hide a country from someone who types its name. `backend/regional/tests/
// test_country_picker.py` fails if any code is missing from the groups or
// appears in two of them, which is the failure that would actually matter.
const COUNTRY_GROUPS = [
  { label: 'North Africa', codes: ['DZ', 'EG', 'LY', 'MA', 'SD', 'TN'] },
  {
    label: 'West Africa',
    codes: ['BF', 'BJ', 'CI', 'CV', 'GH', 'GM', 'GN', 'GW', 'LR', 'ML',
      'MR', 'NE', 'NG', 'SL', 'SN', 'TG'],
  },
  {
    label: 'Central Africa',
    codes: ['BI', 'CD', 'CF', 'CG', 'CM', 'GA', 'GQ', 'ST', 'TD'],
  },
  {
    label: 'East Africa',
    codes: ['DJ', 'ER', 'ET', 'KE', 'KM', 'MG', 'MU', 'MW', 'MZ', 'RW',
      'SC', 'SO', 'SS', 'TZ', 'UG'],
  },
  { label: 'Southern Africa', codes: ['AO', 'BW', 'LS', 'NA', 'SZ', 'ZA', 'ZM', 'ZW'] },
];

const COUNTRY_BY_CODE = COUNTRY_OPTIONS.reduce((acc, [code, name]) => {
  acc[code] = name;
  return acc;
}, {});

// Normalised once per country so filtering does not re-lowercase on every
// keystroke, and so "cote" still matches "Côte d'Ivoire" - a user typing an
// ASCII-only name is more likely than one who types the accent.
const SEARCH_INDEX = COUNTRY_OPTIONS.map(([code, name]) => ({
  code,
  name,
  haystack: `${name} ${code}`.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase(),
}));

function matches(entry, query) {
  if (!query) return true;
  return entry.haystack.includes(query);
}

/**
 * Country picker for registration.
 *
 * Replaces a native <select> of 54 entries, which is a long unfindable list
 * and reads as unfinished. This is a WAI-ARIA 1.2 combobox: a real text input
 * that stays focusable and keeps its value when closed, with the popup list
 * driven by `aria-activedescendant` so focus never leaves the input.
 *
 * The keyboard contract the native element gave for free is reproduced
 * explicitly, because losing it would be a regression rather than a trade:
 * ArrowDown/ArrowUp move the active option, Home/End jump to the ends,
 * Enter selects, Escape closes and restores what was selected, Tab closes
 * without changing it, and Alt+ArrowDown opens without editing.
 */
function CountryPicker({ value, onChange, invalid }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const controlRef = useRef(null);
  const popupRef = useRef(null);
  const listId = 'country-picker-list';

  // The popup is `position: fixed` and anchored to these numbers. `.auth-shell`
  // sets `overflow: hidden`, so a popup positioned inside the card is clipped
  // the moment it reaches past the card's edge - which it always does, because
  // the country field sits low in a long registration form. Escaping the
  // containing block entirely is the only placement that cannot be cut off.
  const [placement, setPlacement] = useState(null);

  const trimmed = query.trim().toLowerCase();
  const accentStripped = trimmed
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '');

  const groups = useMemo(
    () => COUNTRY_GROUPS
      .map((group) => ({
        label: group.label,
        entries: SEARCH_INDEX
          .filter((entry) => group.codes.includes(entry.code))
          .filter((entry) => matches(entry, accentStripped)),
      }))
      .filter((group) => group.entries.length > 0),
    [accentStripped],
  );

  // Flattened view of what is on screen, so arrow keys move through the visible
  // results in reading order rather than through the full 54.
  const flat = useMemo(
    () => groups.flatMap((group) => group.entries),
    [groups],
  );

  const selectedName = value ? COUNTRY_BY_CODE[value] : '';

  useEffect(() => {
    if (!open) return;
    // Keep the active option inside the result set as the query narrows it.
    setActiveIndex((prev) => (flat.length ? Math.min(prev, flat.length - 1) : 0));
  }, [flat.length, open]);

  useEffect(() => {
    if (!open) return;
    const node = listRef.current?.querySelector('[data-active="true"]');
    node?.scrollIntoView({ block: 'nearest' });
  }, [activeIndex, open]);

  // Anchor the popup to the control and flip it above the field when the space
  // below is too short. Measured in a layout effect so the popup never paints
  // at an unpositioned origin first.
  useLayoutEffect(() => {
    if (!open) {
      setPlacement(null);
      return undefined;
    }
    const place = () => {
      const control = controlRef.current;
      if (!control) return;
      const rect = control.getBoundingClientRect();
      const wanted = popupRef.current?.offsetHeight || 280;
      const below = window.innerHeight - rect.bottom;
      const above = rect.top;
      const flip = below < Math.min(wanted, 280) + 12 && above > below;
      const height = flip ? Math.min(wanted, above - 12) : wanted;
      setPlacement({
        top: flip ? Math.max(8, rect.top - height - 6) : rect.bottom + 6,
        left: rect.left,
        width: rect.width,
      });
    };
    place();
    window.addEventListener('resize', place);
    // Capture phase, because the page scrolls an inner container rather than
    // the window on small screens; a bubbling listener would miss that.
    window.addEventListener('scroll', place, true);
    return () => {
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
    };
  }, [open, groups.length]);

  function openList() {
    setOpen(true);
    setQuery('');
  }

  function closeList({ restore } = {}) {
    setOpen(false);
    if (restore) setQuery('');
  }

  function commit(code) {
    onChange(code);
    setOpen(false);
    setQuery('');
    inputRef.current?.focus();
  }

  function handleKeyDown(event) {
    if (event.key === 'Escape') {
      if (open) {
        // Escape abandons the edit and leaves the committed selection alone.
        event.preventDefault();
        closeList({ restore: true });
      }
      return;
    }
    if (event.key === 'Tab') {
      // Tab moves on; it must not silently commit whatever is highlighted.
      if (open) closeList();
      return;
    }
    if (event.key === 'ArrowDown') {
      // Closed: opens the list. Open: steps down, wrapping at the end. Both
      // branches are here so Alt+ArrowDown is covered without a special case -
      // the native element it replaces behaved that way.
      event.preventDefault();
      if (!open) openList();
      else setActiveIndex((prev) => (flat.length ? (prev + 1) % flat.length : 0));
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (!open) openList();
      else setActiveIndex((prev) => (flat.length ? (prev - 1 + flat.length) % flat.length : 0));
      return;
    }
    if (event.key === 'Home' && open) {
      event.preventDefault();
      setActiveIndex(0);
      return;
    }
    if (event.key === 'End' && open) {
      event.preventDefault();
      setActiveIndex(Math.max(0, flat.length - 1));
      return;
    }
    if (event.key === 'Enter' && open) {
      event.preventDefault();
      const entry = flat[activeIndex];
      if (entry) commit(entry.code);
    }
  }

  const activeId = open && flat[activeIndex]
    ? `${listId}-option-${flat[activeIndex].code}`
    : undefined;

  return (
    <div className={`country-picker${invalid ? ' is-invalid' : ''}`} data-open={open ? 'true' : 'false'}>
      <div className="country-picker-control" ref={controlRef}>
        <input
          ref={inputRef}
          id="country"
          name="country"
          type="text"
          role="combobox"
          autoComplete="off"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={activeId}
          aria-required="true"
          aria-invalid={invalid ? 'true' : undefined}
          aria-describedby={invalid ? 'country-error' : undefined}
          placeholder="Select or search for a country"
          value={open ? query : selectedName}
          onChange={(event) => {
            setQuery(event.target.value);
            if (!open) setOpen(true);
            setActiveIndex(0);
          }}
          onFocus={openList}
          onClick={openList}
          onKeyDown={handleKeyDown}
        />
        <button
          type="button"
          className="country-picker-toggle"
          tabIndex={-1}
          aria-label={open ? 'Close country list' : 'Open country list'}
          onClick={() => (open ? closeList() : (openList(), inputRef.current?.focus()))}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d={open ? 'M6 9l6 6 6-6' : 'M6 15l6-6 6 6'} />
          </svg>
        </button>
      </div>

      {open && (
        <div
          ref={popupRef}
          className="country-picker-popup"
          style={placement ? {
            top: `${placement.top}px`,
            left: `${placement.left}px`,
            width: `${placement.width}px`,
          } : { visibility: 'hidden' }}
        >
          {groups.length === 0 ? (
            <p className="country-picker-empty">
              No country matches “{query.trim()}”. All {COUNTRY_OPTIONS.length} supported
              countries are listed by name or two-letter code.
            </p>
          ) : (
            <ul className="country-picker-list" id={listId} role="listbox" ref={listRef} aria-label="Countries">
              {groups.map((group) => (
                <li key={group.label} role="presentation" className="country-picker-group">
                  <div role="presentation" className="country-picker-group-label">{group.label}</div>
                  <ul role="presentation" className="country-picker-group-list">
                    {group.entries.map((entry) => {
                      const isActive = flat[activeIndex]?.code === entry.code;
                      return (
                        <li
                          key={entry.code}
                          id={`${listId}-option-${entry.code}`}
                          role="option"
                          aria-selected={value === entry.code}
                          data-active={isActive ? 'true' : 'false'}
                          className={`country-picker-option${isActive ? ' is-active' : ''}${value === entry.code ? ' is-selected' : ''}`}
                          // Pointer interaction is handled on the list so that a
                          // drag ending over an option does not select it.
                          onMouseEnter={() => setActiveIndex(flat.findIndex((e) => e.code === entry.code))}
                          onMouseDown={(event) => event.preventDefault()}
                          onClick={() => commit(entry.code)}
                        >
                          <span className="country-picker-option-name">{entry.name}</span>
                          <span className="country-picker-option-code">{entry.code}</span>
                          {value === entry.code && (
                            <span className="country-picker-option-check" aria-hidden="true">✓</span>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {invalid && (
        <p className="country-picker-error" id="country-error" role="alert">
          Choose the country where your company operates.
        </p>
      )}
    </div>
  );
}

export default function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const selectedPlan = searchParams.get('plan') || 'starter';
  const [form, setForm] = useState({
    company_name: '',
    country: '',
    company_email: '',
    username: '',
    email: '',
    password: '',
  });
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [countryError, setCountryError] = useState(false);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    // The country control is a combobox, not a native <select>, so constraint
    // validation no longer covers it. Checking here is what keeps "no country"
    // from reaching the API and failing there with a worse message.
    if (!form.country) {
      setCountryError(true);
      return;
    }
    setCountryError(false);
    setSubmitting(true);
    try {
      await register(form);
      setMessage('Company registered! Check your email for an activation link.');
      setTimeout(() => navigate(`/billing?plan=${encodeURIComponent(selectedPlan)}`), 800);
    } catch (err) {
      setError(err.message || 'Registration failed');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-shell auth-shell-register">
        <aside className="auth-aside">
          <Link className="auth-brand" to="/"><span>H</span> HRCLOUDPAY</Link>
          <div className="auth-aside-copy"><p className="auth-kicker">SET UP YOUR WORKSPACE</p><h1>Payroll that is ready for where you operate.</h1><p>Choose your country once and get the appropriate payroll, compliance, currency and HR experience from day one.</p></div>
          <ol className="auth-steps"><li><span>1</span> Create your company workspace</li><li><span>2</span> Confirm your email address</li><li><span>3</span> Add your team and run payroll</li></ol>
        </aside>
        <form className="auth-card auth-card-register" onSubmit={handleSubmit}>
        <Link className="auth-mobile-brand" to="/"><span>H</span> HRCLOUDPAY</Link>
        <p className="auth-kicker">START YOUR WORKSPACE</p>
        <h1>Create your company account</h1>
        <p className="auth-subtitle">Get started in a few minutes. You selected the <strong>{selectedPlan}</strong> plan.</p>
        {error && <div className="alert alert-error">{error}</div>}
        {message && <div className="alert alert-success">{message}</div>}

        <div className="auth-section-label">Company details</div>
        <div className="auth-field"><label>Company name</label><input placeholder="e.g. Acme Holdings" value={form.company_name} onChange={(e) => update('company_name', e.target.value)} required /></div>
        <div className="auth-field">
          <label htmlFor="country">Country where your company operates</label>
          <CountryPicker
            value={form.country}
            invalid={countryError}
            onChange={(code) => { update('country', code); setCountryError(false); }}
          />
        </div>
        <p className="auth-hint">Your country determines the payroll, compliance, currency and HR experience available to your company.</p>
        <div className="auth-field"><label>Company email</label><input placeholder="you@company.com" type="email" value={form.company_email} onChange={(e) => update('company_email', e.target.value)} required /></div>
        <div className="auth-section-label">Your administrator account</div>
        <div className="auth-two-column"><div className="auth-field"><label>Username</label><input value={form.username} onChange={(e) => update('username', e.target.value)} required autoComplete="username" /></div><div className="auth-field"><label>Your email</label><input type="email" value={form.email} onChange={(e) => update('email', e.target.value)} required autoComplete="email" /></div></div>
        <div className="auth-field"><label>Password</label><input placeholder="Create a secure password" type="password" value={form.password} onChange={(e) => update('password', e.target.value)} required autoComplete="new-password" /></div>

        <button className="btn btn-primary" type="submit" disabled={submitting}>
          {submitting ? 'Creating account...' : 'Create workspace'}
        </button>
        <p className="auth-footer">
          Already have a workspace? <Link to="/login">Sign in</Link>
        </p>
        </form>
      </section>
    </main>
  );
}