import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import Icon from './Icon';

const ENDPOINT = '/auth/security/connection/';

interface SessionState {
  icon: string;
  label: string;
  note: string;
  tone: string;
}

interface ConnectionData {
  session?: { status?: string };
  source?: string;
  ip_address?: string;
  city?: string;
  region?: string;
  country?: string;
  country_code?: string;
  isp?: string;
  asn?: string | number;
  checked_at?: string;
  refresh_throttled?: boolean;
}

/* The backend reports security facts; the wording, icon and colour are a
   presentation decision, so they live here rather than in the API. */
const SESSION_STATES: Record<string, SessionState> = {
  /* Shown only until the first answer arrives. It must not borrow the alarming
     'unknown' styling, or every page load opens on a red warning. */
  pending: { icon: 'shield', label: 'Checking session…', note: '', tone: 'idle' },
  secure: { icon: 'shield', label: 'Secure session', note: 'Connected', tone: 'ok' },
  standard: { icon: 'lock', label: 'Session active', note: 'MFA not verified', tone: 'warn' },
  unmanaged: { icon: 'lock', label: 'Session active', note: 'Standard sign-in', tone: 'warn' },
  insecure: { icon: 'alert', label: 'Unencrypted', note: 'Connected', tone: 'warn' },
  expired: { icon: 'alert', label: 'Session expired', note: 'Sign in again', tone: 'bad' },
  unknown: { icon: 'alert', label: 'Session status unknown', note: 'Connected', tone: 'bad' },
};

/* ISO 3166-1 alpha-2 to a flag, via the two regional indicator symbols. Returns
   '' for anything that is not a two-letter code, so a provider that sends a
   country *name* in this field cannot render as a broken box. */
function flagFor(code: unknown): string {
  if (typeof code !== 'string' || !/^[A-Za-z]{2}$/.test(code.trim())) return '';
  const base = 0x1f1e6;
  const upper = code.trim().toUpperCase();
  return String.fromCodePoint(
    base + (upper.charCodeAt(0) - 65),
    base + (upper.charCodeAt(1) - 65),
  );
}

function relativeTime(iso: string, now: number): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return 'Unknown';
  const seconds = Math.max(0, Math.round((now - then) / 1000));
  if (seconds < 10) return 'Just now';
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function clockTime(value: string): string {
  try {
    return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

function fullTime(value: string): string {
  try {
    return new Date(value).toLocaleString();
  } catch {
    return '';
  }
}

/* Read once per render rather than in an effect: it cannot change without the
   page being re-rendered anyway, and this keeps the render pure. */
function browserZone(): { zone: string; offset: string } {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Unknown';
    // getTimezoneOffset counts minutes *behind* UTC, hence the negation.
    const minutes = -new Date().getTimezoneOffset();
    const sign = minutes < 0 ? '-' : '+';
    const abs = Math.abs(minutes);
    const offset = `UTC${sign}${String(Math.floor(abs / 60)).padStart(2, '0')}:${String(abs % 60).padStart(2, '0')}`;
    return { zone, offset };
  } catch {
    return { zone: 'Unavailable', offset: '' };
  }
}

interface FactProps {
  icon: string;
  label: string;
  value: string;
  sub?: string;
  flag?: string;
  title?: string;
  isTime?: boolean;
  time?: string;
}

function Fact({ icon, label, value, sub, flag, title, isTime, time }: FactProps) {
  return (
    <div className="connection-fact">
      <dt>
        <Icon name={icon} size={12} />
        {label}
      </dt>
      <dd>
        {flag ? <span className="connection-flag" aria-hidden="true">{flag}</span> : null}
        {isTime ? (
          <time className="connection-value" dateTime={value} title={title || fullTime(value)}>
            {time}
          </time>
        ) : (
          <span className="connection-value" title={title || value}>{value}</span>
        )}
        {sub ? <span className="connection-sub">{sub}</span> : null}
      </dd>
    </div>
  );
}

/* Loopback and private ranges are both "no public location", but calling a
   request that never left the machine a "private network" is misleading in the
   other direction - the user is sitting at the machine, not on some LAN. */
function isLoopbackAddress(ip: unknown): boolean {
  if (typeof ip !== 'string') return false;
  const value = ip.trim().toLowerCase();
  return value === '::1' || value === '0:0:0:0:0:0:0:1' || /^127\./.test(value);
}

interface ConnectionState {
  loading: boolean;
  data: ConnectionData | null;
  failed: boolean;
  refreshing: boolean;
}

export default function ConnectionDetails() {
  const [state, setState] = useState<ConnectionState>({ loading: true, data: null, failed: false, refreshing: false });
  const [now, setNow] = useState(() => Date.now());
  const mounted = useRef(true);

  const load = useCallback((force: boolean) => {
    setState((current) => ({ ...current, refreshing: force ? true : current.loading }));
    api
      .get<ConnectionData>(force ? `${ENDPOINT}?refresh=1` : ENDPOINT)
      .then((data) => {
        if (mounted.current) setState({ loading: false, data, failed: false, refreshing: false });
      })
      .catch(() => {
        // Silent by design: the connection card is supplementary, and a failure
        // here must not present itself as an error on the dashboard.
        if (mounted.current) setState({ loading: false, data: null, failed: true, refreshing: false });
      });
  }, []);

  useEffect(() => {
    mounted.current = true;
    load(false);
    return () => {
      mounted.current = false;
    };
  }, [load]);

  // Drives both the relative "last checked" figure and the local clock. Short
  // enough to feel live, long enough not to be busywork on an idle tab.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 15000);
    return () => clearInterval(id);
  }, []);

  if (state.failed) return null;

  const data = state.data;
  const session = data && data.session;
  const status = state.loading && !data
    ? SESSION_STATES.pending
    : SESSION_STATES[(session && session.status) || 'unknown'] || SESSION_STATES.unknown;
  const { zone, offset } = browserZone();
  const isPrivate = !data || data.source === 'private';
  const lookupFailed = !!data && data.source === 'unavailable';

  const place = !data
    ? ''
    : isPrivate
      ? (isLoopbackAddress(data.ip_address) ? 'This device' : 'Private network')
      : [data.city, data.region, data.country].filter(Boolean).join(', ') || 'Unknown';

  /* "Not available" while still loading would be a false statement - the answer
     simply has not arrived yet. For a private address "Not applicable" is the
     honest word: the traffic never reached an ISP, so there is none to report. */
  const local = !data || isPrivate;
  const provider = !data
    ? (state.loading ? 'Checking…' : 'Not available')
    : isPrivate
      ? 'Not applicable'
      : data.isp || 'Not published';

  const facts: Array<FactProps & { key: string }> = [
    {
      key: 'ip',
      icon: 'signal',
      label: 'IP address',
      value: (data && data.ip_address) || (state.loading ? 'Checking…' : 'Unavailable'),
    },
    {
      key: 'location',
      icon: 'pin',
      label: 'Location',
      value: place || (lookupFailed ? 'Lookup unavailable' : 'Checking…'),
      flag: data && !isPrivate ? flagFor(data.country_code) : '',
    },
    {
      key: 'isp',
      icon: 'globe',
      label: 'ISP provider',
      value: provider,
      // Providers disagree on whether the ASN carries its own "AS" prefix:
      // ipwho.is returns a bare number (328136), IPGeolocation.io returns
      // "AS14593". Prefixing unconditionally rendered "ASAS14593", so normalise
      // before adding the one prefix we actually want.
      sub: data && data.asn ? `AS${String(data.asn).replace(/^AS/i, '')}` : '',
    },
    {
      key: 'zone',
      icon: 'clock',
      label: 'Browser time zone',
      value: zone,
      sub: [offset, clockTime(new Date(now).toISOString())].filter(Boolean).join(' · '),
    },
    {
      key: 'checked',
      icon: 'check',
      label: 'Last checked',
      value: (data && data.checked_at) || new Date(now).toISOString(),
      isTime: true,
      time: data && data.checked_at ? relativeTime(data.checked_at, now) : 'Checking…',
      sub: data && data.checked_at ? clockTime(data.checked_at) : '',
    },
  ];

  return (
    <div className="dashboard-connection" aria-busy={state.loading || undefined}>
      <div className="connection-head">
        <span className={`connection-status is-${status.tone}`}>
          <Icon name={status.icon} size={14} />
          <b>{status.label}</b>
          {status.note ? <em>{status.note}</em> : null}
        </span>
        <span className="connection-head-right">
          {data && data.refresh_throttled ? (
            /* Not "just refreshed" - the opposite: the request was rate limited
               and the cached result was served. The wording has to say the data
               is current without claiming a lookup happened. */
            <em
              className="connection-flag-note"
              title="You refreshed this moments ago, so the current result is already up to date."
            >
              Up to date
            </em>
          ) : null}
          <button
            type="button"
            className={`connection-refresh${state.refreshing ? ' is-busy' : ''}`}
            onClick={() => load(true)}
            disabled={state.refreshing}
            aria-label="Refresh connection details"
          >
            <Icon name="refresh" size={13} />
            <span>{state.refreshing ? 'Refreshing' : 'Refresh'}</span>
          </button>
        </span>
      </div>
      <dl className="connection-facts">
        {facts.map(({ key, ...fact }) => (
          <Fact key={key} {...fact} />
        ))}
      </dl>
      {local && data ? (
        /* Say why, or an empty country reads as a broken lookup rather than the
           accurate answer it is. */
        <p className="connection-explain">
          {isLoopbackAddress(data.ip_address)
            ? 'This request came from this device over the loopback interface, so it never left your computer and has no public location or ISP.'
            : 'This request came from a private address that is not routable on the internet, so there is no public location or ISP to report.'}
        </p>
      ) : null}
    </div>
  );
}