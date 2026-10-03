import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { withStepUp } from '../api/stepUp';
import ConnectionDetails from '../components/ConnectionDetails';
import Icon from '../components/Icon';

const RESTRICTED = 'Restricted to IT/security administrators';

/* dashboard/ , threat-detection/ , pam/ , incidents/ and governance/ all sit
   behind IsITSecurityAdmin, so a non-admin gets a 403 on five of the calls
   below. Each one is caught on its own and the page keeps rendering - the
   error is a property of that panel, not of the page. */
function describeError(error) {
  if (error && error.status === 403) return RESTRICTED;
  if (error && error.status === 401) return 'Your session has expired. Sign in again.';
  return (error && error.message) || 'Request failed.';
}

/* Server enums -> a pill tone. The wording stays here rather than in the API,
   matching how the rest of the app presents security state. */
const TONES = {
  approved: 'good', certified: 'good', trusted: 'good', active: 'good', resolved: 'good', secure: 'good',
  pending: 'warn', open: 'warn', untrusted: 'warn', change_requested: 'warn', standard: 'warn',
  insecure: 'warn', unmanaged: 'warn', medium: 'warn',
  blocked: 'bad', revoked: 'bad', rejected: 'bad', denied: 'bad', expired: 'bad',
  high: 'bad', critical: 'bad',
};
function tone(value) {
  return TONES[String(value == null ? '' : value).toLowerCase()] || 'neutral';
}

function Pill({ value, children }) {
  const label = children == null ? value : children;
  if (label == null || label === '') return <span className="sec-pill sec-pill-neutral">Not set</span>;
  return <span className={`sec-pill sec-pill-${tone(value)}`}>{String(label)}</span>;
}

function stamp(value) {
  if (!value) return 'Not recorded';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString();
}

/* Comma separated text -> array, and back. The PAM and role endpoints both
   take a list of permission strings and the API has no picker for them. */
function toList(value) {
  return String(value || '').split(',').map((item) => item.trim()).filter(Boolean);
}

function Stat({ label, value, note }) {
  return (
    <div className="sec-stat">
      <span>{label}</span>
      {/* `value` is whatever the endpoint returned. Callers pass a word, never
          a stand-in number, when there is genuinely nothing to show. */}
      <strong>{value == null || value === '' ? 'Not reported' : value}</strong>
      {note ? <small>{note}</small> : null}
    </div>
  );
}

function PanelHead({ title, description, children }) {
  return (
    <div className="sec-head">
      <div>
        <h2>{title}</h2>
        {description ? <p>{description}</p> : null}
      </div>
      {children ? <div className="sec-actions">{children}</div> : null}
    </div>
  );
}

/* The one place a failed panel turns into visible output, so a 403 reads as
   "you cannot see this" rather than as an empty table. */
function Gate({ error }) {
  if (!error) return null;
  const restricted = error === RESTRICTED;
  return (
    <div className={restricted ? 'sec-restricted' : 'sec-error'}>
      <Icon name={restricted ? 'lock' : 'alert'} size={14} />
      <span>{error}</span>
    </div>
  );
}

const SSO_TYPES = [
  { value: 'oidc', label: 'OIDC' },
  { value: 'saml', label: 'SAML' },
  { value: 'entra', label: 'Microsoft Entra ID' },
  { value: 'google', label: 'Google Workspace' },
];

/* The certification decisions the endpoint accepts. Anything else is a 400
   from GovernanceCertificationView. */
const DECISIONS = [
  { value: 'certified', label: 'Certify' },
  { value: 'revoked', label: 'Revoke' },
  { value: 'change_requested', label: 'Request change' },
];

export default function SecurityCenter() {
  const [ready, setReady] = useState(false);
  const [data, setData] = useState(null);
  const [status, setStatus] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [mfa, setMfa] = useState(null);
  const [devices, setDevices] = useState([]);
  const [pam, setPam] = useState([]);
  const [governance, setGovernance] = useState(null);
  const [team, setTeam] = useState([]);
  const [threat, setThreat] = useState(null);
  const [dlp, setDlp] = useState(null);

  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState({});
  const [message, setMessage] = useState('');
  const [tone, setTone] = useState('success');

  const [secret, setSecret] = useState('');
  const [code, setCode] = useState('');
  const [pamForm, setPamForm] = useState({ target_user: '', permissions: '', reason: '', duration_minutes: '60' });
  const [dlpForm, setDlpForm] = useState({ event_type: '', object_type: '', object_count: '1', external_share: false });
  const [roleForm, setRoleForm] = useState({ name: '', permissions: '', privileged: false });
  const [ssoForm, setSsoForm] = useState({ name: '', provider_type: 'oidc', domain: '' });
  const [scimForm, setScimForm] = useState({ label: '' });
  const [reviewForm, setReviewForm] = useState({ name: '', days: '30' });
  const [certReasons, setCertReasons] = useState({});
  const [scimToken, setScimToken] = useState('');

  function notify(text, level) {
    setMessage(text);
    setTone(level || 'success');
  }

  /* One panel's failure must not cancel the others, so every load is caught
     individually and its message is filed against that panel only. */
  async function loadSection(key, run, apply) {
    try {
      const value = await run();
      setErrors((prev) => (prev[key] ? { ...prev, [key]: '' } : prev));
      if (apply) apply(value);
      return value;
    } catch (error) {
      setErrors((prev) => ({ ...prev, [key]: describeError(error) }));
      return undefined;
    }
  }

  async function load() {
    setBusy((prev) => ({ ...prev, load: true }));
    await Promise.all([
      loadSection('dashboard', () => api.get('/auth/security/dashboard/'), setData),
      loadSection('status', () => api.get('/auth/security/status/'), setStatus),
      loadSection('sessions', () => api.get('/auth/security/sessions/'), setSessions),
      loadSection('incidents', () => api.get('/auth/security/incidents/'), setIncidents),
      loadSection('mfa', () => api.get('/auth/security/mfa/'), setMfa),
      loadSection('devices', () => api.get('/auth/security/devices/'), setDevices),
      loadSection('pam', () => api.get('/auth/security/pam/'), setPam),
      loadSection('governance', () => api.get('/auth/security/governance/'), setGovernance),
      // PAM approval needs a real user id as the target. The team roster is the
      // only list of company user ids an IT admin can read; it is admin-gated
      // too, so it fails on the same terms as the panel it feeds.
      loadSection('team', () => api.get('/auth/users/'), (rows) => setTeam(rows || [])),
    ]);
    setBusy((prev) => ({ ...prev, load: false }));
    setReady(true);
  }

  useEffect(() => { load(); }, []);

  /* Shared shape for every write: it owns the disabled state, reports the
     failure text, and only then reports success - so a failure can never be
     reported as if the change landed. */
  async function act(key, run, describe) {
    setBusy((prev) => ({ ...prev, [key]: true }));
    try {
      const result = await run();
      const text = typeof describe === 'function' ? describe(result) : describe;
      if (text) notify(text, 'success');
      return result;
    } catch (error) {
      notify(describeError(error), 'error');
      return undefined;
    } finally {
      setBusy((prev) => ({ ...prev, [key]: false }));
    }
  }

  async function revokeAll() {
    const done = await act('revoke', () => api.del('/auth/security/sessions/'), 'All active sessions were revoked.');
    if (done) load();
  }

  async function startMfaSetup() {
    const result = await act('mfaSetup', () => api.post('/auth/security/mfa/', { action: 'setup' }), 'MFA secret generated. Add it to your authenticator, then enter the 6-digit code.');
    if (result && result.secret) {
      setSecret(result.secret);
      setCode('');
    }
  }

  async function confirmMfa() {
    const done = await act('mfaConfirm', () => api.post('/auth/security/mfa/', { action: 'enable', code: code.trim() }), 'MFA enabled.');
    if (done) {
      setSecret('');
      setCode('');
      load();
    }
  }

  async function runThreatDetection() {
    const result = await act(
      'threat',
      () => api.post('/auth/security/threat-detection/', {}),
      (res) => (res && res.detected
        ? `Authentication burst detected. Risk signal ${res.signal_id} was recorded.`
        : 'No authentication burst detected.'),
    );
    if (result) setThreat(result);
  }

  async function requestAccess() {
    const payload = {
      target_user: pamForm.target_user,
      permissions: toList(pamForm.permissions),
      reason: pamForm.reason,
      duration_minutes: Number(pamForm.duration_minutes) || 0,
    };
    const result = await act(
      'pamCreate',
      () => api.post('/auth/security/pam/', payload),
      (res) => `Access request ${res && res.id ? res.id : ''} created with status ${res ? res.status : 'unknown'}.`,
    );
    if (result) {
      setPamForm({ target_user: '', permissions: '', reason: '', duration_minutes: '60' });
      loadSection('pam', () => api.get('/auth/security/pam/'), setPam);
    }
  }

  async function approveAccess(requestId) {
    const result = await act(
      `pamApprove:${requestId}`,
      // Granting privileged access requires a fresh MFA challenge.
      () => withStepUp(() => api.post(`/auth/security/pam/${requestId}/approve/`, {})),
      (res) => `Approved. Session ${res && res.session_id ? res.session_id : ''} expires ${stamp(res && res.expires_at)}.`,
    );
    if (result) loadSection('pam', () => api.get('/auth/security/pam/'), setPam);
  }

  async function runDlpCheck() {
    const payload = {
      event_type: dlpForm.event_type,
      object_type: dlpForm.object_type,
      object_count: Number(dlpForm.object_count) || 0,
      external_share: dlpForm.external_share,
    };
    const result = await act(
      'dlp',
      () => api.post('/auth/security/dlp/', payload),
      (res) => (res && res.blocked
        ? `Blocked. DLP event ${res.event_id} was recorded and an incident was opened.`
        : `Allowed. DLP event ${res && res.event_id ? res.event_id : ''} was recorded.`),
    );
    if (result) setDlp(result);
  }

  async function runGovernanceAction(action, payload, describe) {
    const result = await act(`gov:${action}`, () => api.post('/auth/security/governance/', { action, ...payload }), describe);
    if (result) {
      setScimToken(action === 'scim' && result.token ? result.token : '');
      loadSection('governance', () => api.get('/auth/security/governance/'), setGovernance);
    }
    return result;
  }

  async function decideCertification(certificationId, decision) {
    const result = await act(
      `cert:${certificationId}`,
      () => api.patch(`/auth/security/governance/certifications/${certificationId}/`, { decision, reason: certReasons[certificationId] || '' }),
      (res) => `Certification recorded as ${res ? res.decision : decision}.`,
    );
    if (result) loadSection('governance', () => api.get('/auth/security/governance/'), setGovernance);
  }

  if (!ready) {
    return <div className="sec-page"><h1>Security Center</h1><p className="page-loading">Loading security controls…</p></div>;
  }

  const totalTrust = status ? status.trust_score : null;
  const governanceRoles = (governance && governance.roles) || [];
  const governanceReviews = (governance && governance.reviews) || [];
  const certifications = (governance && governance.certifications) || [];
  const ssoProviders = (governance && governance.sso) || [];
  const scimCredentials = (governance && governance.scim) || [];
  const pendingAccess = pam.filter((row) => row.status === 'pending');

  return (
    <div className="sec-page">
      <div className="sec-top">
        <div>
          <h1>Security Center</h1>
          <p>IT &amp; Security operations, identity protection, Zero Trust and incident response.</p>
        </div>
        <div className="sec-actions">
          <button className="btn btn-secondary" onClick={load} disabled={!!busy.load}>{busy.load ? 'Refreshing…' : 'Refresh'}</button>
        </div>
      </div>

      {message ? <div className={tone === 'error' ? 'sec-error' : 'sec-success'}>{message}</div> : null}

      <div className="sec-grid sec-grid-4">
        <Stat
          label="Trust score"
          value={totalTrust == null ? 'Not reported' : totalTrust}
          note={status ? `User ${status.user_id}` : 'Security status unavailable'}
        />
        <Stat
          label="MFA"
          value={status ? (status.mfa_enabled ? 'Enabled' : 'Not enabled') : 'Not reported'}
          note={mfa && mfa.required ? 'Required for this account' : 'Optional for this account'}
        />
        <Stat
          label="Active sessions"
          value={errors.dashboard ? 'Restricted' : data ? data.sessions : 'Not reported'}
          note={errors.dashboard ? errors.dashboard : 'Company-wide, unrevoked and unexpired'}
        />
        <Stat
          label="Open incidents"
          value={errors.incidents ? 'Restricted' : incidents ? incidents.length : 'Not reported'}
          note={errors.incidents ? errors.incidents : 'Loaded from the incident register'}
        />
      </div>

      <section className="card">
        <PanelHead title="Connection &amp; session" description="Where this session is coming from, and how it is being secured." />
        {/* GET /auth/security/connection/ - the component owns the ?refresh=1
            re-lookup and renders the rate-limit result honestly. */}
        <ConnectionDetails />
      </section>

      <div className="sec-grid sec-grid-2">
        <section className="card">
          <PanelHead title="Identity &amp; Zero Trust" description="Multi-factor authentication and global sign-out.">
            <button className="btn btn-secondary" onClick={revokeAll} disabled={!!busy.revoke}>{busy.revoke ? 'Revoking…' : 'Sign out everywhere'}</button>
          </PanelHead>
          <Gate error={errors.mfa || errors.status} />
          <div className="sec-list">
            <div className="sec-row">
              <div className="sec-row-head">
                <strong>Multi-factor authentication</strong>
                <Pill value={mfa && mfa.enabled ? 'enabled' : mfa ? 'not enabled' : null} />
              </div>
              <small>{mfa ? (mfa.required ? 'Required for this account.' : 'Not required for this account.') : 'MFA state was not reported.'}</small>
            </div>
            <div className="sec-row">
              <div className="sec-row-head"><strong>Current session</strong></div>
              <small className="sec-code">{status ? (status.session_id || 'No managed security session is attached to this request.') : 'Session id was not reported.'}</small>
            </div>
          </div>

          {secret ? (
            <div className="sec-form">
              <div className="sec-form-row">
                <div>
                  <label htmlFor="mfa-secret">Authenticator secret</label>
                  <input id="mfa-secret" className="sec-input-secret" value={secret} readOnly onFocus={(e) => e.target.select()} />
                </div>
                <div>
                  <label htmlFor="mfa-code">Current 6-digit code</label>
                  <input
                    id="mfa-code"
                    className="sec-input-code"
                    value={code}
                    inputMode="numeric"
                    maxLength={6}
                    placeholder="000000"
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  />
                </div>
              </div>
              <div className="sec-actions">
                <button className="btn btn-primary" onClick={confirmMfa} disabled={busy.mfaConfirm || code.length !== 6}>
                  {busy.mfaConfirm ? 'Confirming…' : 'Confirm and enable'}
                </button>
                <button className="btn btn-secondary" onClick={() => { setSecret(''); setCode(''); }}>Cancel</button>
              </div>
              <p className="sec-hint">This secret is shown once. Store it in your authenticator app before confirming.</p>
            </div>
          ) : (
            <div className="sec-actions">
              <button className="btn btn-primary" onClick={startMfaSetup} disabled={!!busy.mfaSetup}>
                {busy.mfaSetup ? 'Generating…' : (mfa && mfa.enabled ? 'Rotate MFA secret' : 'Set up MFA')}
              </button>
            </div>
          )}
        </section>

        <section className="card">
          <PanelHead title="Active sessions" description="Sessions that are still usable for this account." />
          <Gate error={errors.sessions} />
          {sessions.length === 0 ? (
            <p className="sec-empty">No sessions were returned.</p>
          ) : (
            <div className="sec-list">
              {sessions.slice(0, 8).map((session) => (
                <div className="sec-row" key={session.id}>
                  <div className="sec-row-head">
                    <strong>{session.device || 'Browser'}</strong>
                    <Pill value={session.active ? 'active' : 'revoked'}>{session.active ? 'Active' : 'Revoked'}</Pill>
                    {session.mfa_verified ? <Pill value="certified">MFA verified</Pill> : null}
                  </div>
                  <small>
                    {session.ip || 'Unknown IP'} · {session.country || 'No country recorded'} · expires {stamp(session.expires_at)}
                  </small>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      <div className="sec-grid sec-grid-2">
        <section className="card">
          <PanelHead title="Threat detection" description="Runs the authentication-burst detector for this company.">
            <button className="btn btn-secondary" onClick={runThreatDetection} disabled={!!busy.threat}>{busy.threat ? 'Scanning…' : 'Run detection'}</button>
          </PanelHead>
          <Gate error={errors.threat || errors.dashboard} />
          {threat ? (
            <div className="sec-list">
              <div className="sec-row">
                <div className="sec-row-head">
                  <strong>{threat.detected ? 'Burst detected' : 'No burst detected'}</strong>
                  <Pill value={threat.detected ? 'high' : 'low'}>{threat.detected ? 'Detected' : 'Clear'}</Pill>
                </div>
                <small>Risk signal: {threat.signal_id || 'The detector did not raise a signal.'}</small>
              </div>
            </div>
          ) : (
            <p className="sec-empty">No scan has been run from this page yet.</p>
          )}
        </section>

        <section className="card">
          <PanelHead title="Data loss prevention" description="Records a sharing or export attempt and reports whether policy blocked it." />
          <div className="sec-form">
            <div className="sec-form-row">
              <div>
                <label htmlFor="dlp-event">Event type</label>
                <input id="dlp-event" value={dlpForm.event_type} placeholder="export" onChange={(e) => setDlpForm({ ...dlpForm, event_type: e.target.value })} />
              </div>
              <div>
                <label htmlFor="dlp-object">Object type</label>
                <input id="dlp-object" value={dlpForm.object_type} placeholder="payroll_run" onChange={(e) => setDlpForm({ ...dlpForm, object_type: e.target.value })} />
              </div>
              <div>
                <label htmlFor="dlp-count">Object count</label>
                <input id="dlp-count" type="number" min="0" value={dlpForm.object_count} onChange={(e) => setDlpForm({ ...dlpForm, object_count: e.target.value })} />
              </div>
            </div>
            <label className="checkbox-label" htmlFor="dlp-external">
              <input id="dlp-external" type="checkbox" checked={dlpForm.external_share} onChange={(e) => setDlpForm({ ...dlpForm, external_share: e.target.checked })} />
              Shared outside the company
            </label>
            <div className="sec-actions">
              <button className="btn btn-primary" onClick={runDlpCheck} disabled={!!busy.dlp}>{busy.dlp ? 'Checking…' : 'Submit to DLP'}</button>
            </div>
          </div>
          {dlp ? (
            <div className="sec-list">
              <div className="sec-row">
                <div className="sec-row-head">
                  <strong>{dlp.blocked ? 'Operation blocked' : 'Operation allowed'}</strong>
                  <Pill value={dlp.blocked ? 'blocked' : 'active'}>{dlp.blocked ? 'Blocked' : 'Allowed'}</Pill>
                </div>
                <small>DLP event {dlp.event_id}</small>
              </div>
            </div>
          ) : null}
        </section>
      </div>

      <section className="card">
        <PanelHead title="Trusted devices" description="Device trust state recorded for this company.">
          <button className="btn btn-secondary" onClick={() => loadSection('devices', () => api.get('/auth/security/devices/'), setDevices)}>Reload</button>
        </PanelHead>
        <Gate error={errors.devices} />
        {devices.length === 0 ? (
          <p className="sec-empty">No trusted devices have been recorded.</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr><th>Label</th><th>State</th><th>User</th><th>Last IP</th><th>Last seen</th></tr>
            </thead>
            <tbody>
              {devices.map((device) => (
                <tr key={device.id}>
                  <td>{device.label || 'Unlabelled device'}</td>
                  <td><Pill value={device.state} /></td>
                  <td>{device.user_id}</td>
                  <td>{device.last_ip || 'Not recorded'}</td>
                  <td>{stamp(device.last_seen_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {/* The urlconf only registers devices/, so there is no routed endpoint
            to change a device's state from. Offering a control that 404s would
            be worse than saying plainly that this is read-only. */}
        <p className="sec-note">Device state is read-only here: the API exposes no routed endpoint to change it.</p>
      </section>

      <section className="card">
        <PanelHead title="Privileged access management (PAM)" description="Request elevated access, and approve requests raised by other admins.">
          <button className="btn btn-secondary" onClick={() => loadSection('pam', () => api.get('/auth/security/pam/'), setPam)}>Reload</button>
        </PanelHead>
        <Gate error={errors.pam} />
        <div className="sec-form">
          <div className="sec-form-row">
            <div>
              <label htmlFor="pam-target">Target user</label>
              <select id="pam-target" value={pamForm.target_user} onChange={(e) => setPamForm({ ...pamForm, target_user: e.target.value })}>
                <option value="">{team.length ? 'Select a user' : 'No users available'}</option>
                {team.map((member) => <option key={member.id} value={member.id}>{member.username}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="pam-duration">Duration (minutes)</label>
              <input id="pam-duration" type="number" min="1" max="240" value={pamForm.duration_minutes} onChange={(e) => setPamForm({ ...pamForm, duration_minutes: e.target.value })} />
            </div>
          </div>
          <label htmlFor="pam-permissions">Permissions (comma separated)</label>
          <input id="pam-permissions" value={pamForm.permissions} placeholder="payroll.approve, reports.export" onChange={(e) => setPamForm({ ...pamForm, permissions: e.target.value })} />
          <label htmlFor="pam-reason">Reason</label>
          <input id="pam-reason" value={pamForm.reason} onChange={(e) => setPamForm({ ...pamForm, reason: e.target.value })} />
          <div className="sec-actions">
            <button
              className="btn btn-primary"
              onClick={requestAccess}
              disabled={!!busy.pamCreate || !pamForm.target_user || !pamForm.reason.trim()}
            >
              {busy.pamCreate ? 'Requesting…' : 'Request access'}
            </button>
          </div>
          {errors.team ? <p className="sec-hint">The user roster could not be loaded, so a target cannot be picked. {errors.team}</p> : null}
        </div>

        <div className="sec-head sec-gap-head">
          <div>
            <h2>Access requests</h2>
            <p>{pendingAccess.length} pending.</p>
          </div>
        </div>
        {pam.length === 0 ? (
          <p className="sec-empty">No access requests have been raised.</p>
        ) : (
          <div className="sec-list">
            {pam.map((row) => (
              <div className="sec-row" key={row.id}>
                <div className="sec-row-head">
                  <strong>{row.requester} → {row.target_user}</strong>
                  <Pill value={row.status} />
                </div>
                <small>
                  {toList(row.permissions && row.permissions.join ? row.permissions.join(',') : row.permissions).join(', ') || 'No permissions requested'} · expires {stamp(row.expires_at)}
                </small>
                {row.reason ? <small>{row.reason}</small> : null}
                {row.status === 'pending' ? (
                  <div className="sec-actions sec-gap">
                    <button
                      className="btn btn-secondary"
                      onClick={() => approveAccess(row.id)}
                      disabled={!!busy[`pamApprove:${row.id}`]}
                    >
                      {busy[`pamApprove:${row.id}`] ? 'Approving…' : 'Approve'}
                    </button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="card">
        <PanelHead title="Governance" description="Tenant roles, single sign-on, SCIM provisioning and access review campaigns.">
          <button className="btn btn-secondary" onClick={() => loadSection('governance', () => api.get('/auth/security/governance/'), setGovernance)}>Reload</button>
        </PanelHead>
        <Gate error={errors.governance} />

        {governance ? (
          <>
            <div className="sec-grid sec-grid-4">
              <Stat label="Custom roles" value={governanceRoles.length} note="Roles defined in this tenant" />
              <Stat label="SSO providers" value={ssoProviders.length} note="All start disabled" />
              <Stat label="SCIM credentials" value={scimCredentials.length} note="For directory provisioning" />
              <Stat label="Certifications" value={certifications.length} note="Access review decisions" />
            </div>

            <div className="sec-grid sec-grid-2">
              <div>
                <PanelHead title="Create a custom role" description="Tenant roles cannot grant platform-level permissions." />
                <div className="sec-form">
                  <label htmlFor="role-name">Role name</label>
                  <input id="role-name" value={roleForm.name} onChange={(e) => setRoleForm({ ...roleForm, name: e.target.value })} />
                  <label htmlFor="role-permissions">Permissions (comma separated)</label>
                  <input id="role-permissions" value={roleForm.permissions} placeholder="payroll.view, leave.approve" onChange={(e) => setRoleForm({ ...roleForm, permissions: e.target.value })} />
                  <label className="checkbox-label" htmlFor="role-privileged">
                    <input id="role-privileged" type="checkbox" checked={roleForm.privileged} onChange={(e) => setRoleForm({ ...roleForm, privileged: e.target.checked })} />
                    Privileged role
                  </label>
                  <div className="sec-actions">
                    <button
                      className="btn btn-primary"
                      onClick={() => runGovernanceAction('role', { name: roleForm.name, permissions: toList(roleForm.permissions), privileged: roleForm.privileged }, (res) => `Role ${res && res.name ? res.name : ''} created.`)}
                      disabled={!!busy['gov:role'] || !roleForm.name.trim()}
                    >
                      {busy['gov:role'] ? 'Creating…' : 'Create role'}
                    </button>
                  </div>
                </div>
                <div className="sec-list sec-gap">
                  {governanceRoles.length === 0 ? <p className="sec-empty">No custom roles are defined.</p> : governanceRoles.map((role) => (
                    <div className="sec-row" key={role.id}>
                      <div className="sec-row-head">
                        <strong>{role.name || 'Unnamed role'}</strong>
                        <Pill value={role.privileged ? 'high' : 'low'}>{role.privileged ? 'Privileged' : 'Standard'}</Pill>
                      </div>
                      <small>{toList(role.permissions && role.permissions.join ? role.permissions.join(',') : role.permissions).join(', ') || 'No permissions'}</small>
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <PanelHead title="Identity providers" description="SSO providers and SCIM credentials for this tenant." />
                <div className="sec-form">
                  <div className="sec-form-row">
                    <div>
                      <label htmlFor="sso-type">Provider type</label>
                      <select id="sso-type" value={ssoForm.provider_type} onChange={(e) => setSsoForm({ ...ssoForm, provider_type: e.target.value })}>
                        {SSO_TYPES.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}
                      </select>
                    </div>
                    <div>
                      <label htmlFor="sso-name">Provider name</label>
                      <input id="sso-name" value={ssoForm.name} onChange={(e) => setSsoForm({ ...ssoForm, name: e.target.value })} />
                    </div>
                  </div>
                  <label htmlFor="sso-domain">Domain</label>
                  <input id="sso-domain" value={ssoForm.domain} onChange={(e) => setSsoForm({ ...ssoForm, domain: e.target.value })} />
                  <div className="sec-actions">
                    <button
                      className="btn btn-secondary"
                      onClick={() => runGovernanceAction('sso', { name: ssoForm.name || 'SSO', provider_type: ssoForm.provider_type, domain: ssoForm.domain, config: {}, group_role_mapping: {} }, (res) => `SSO provider ${res && res.id ? res.id : ''} created. It starts disabled.`)}
                      disabled={!!busy['gov:sso']}
                    >
                      {busy['gov:sso'] ? 'Creating…' : 'Add SSO provider'}
                    </button>
                  </div>
                </div>
                <div className="sec-list sec-gap">
                  {ssoProviders.length === 0 ? <p className="sec-empty">No SSO providers are configured.</p> : ssoProviders.map((provider) => (
                    <div className="sec-row" key={provider.id}>
                      <div className="sec-row-head">
                        <strong>{provider.name || 'Unnamed provider'}</strong>
                        <Pill value={provider.enabled ? 'active' : 'pending'}>{provider.enabled ? 'Enabled' : 'Disabled'}</Pill>
                      </div>
                      <small>{provider.provider_type || 'Unknown type'} · {provider.domain || 'No domain recorded'}</small>
                    </div>
                  ))}
                </div>

                <div className="sec-form sec-gap">
                  <label htmlFor="scim-label">SCIM credential label</label>
                  <input id="scim-label" value={scimForm.label} onChange={(e) => setScimForm({ ...scimForm, label: e.target.value })} />
                  <div className="sec-actions">
                    <button
                      className="btn btn-secondary"
                      onClick={() => runGovernanceAction('scim', { label: scimForm.label || 'SCIM' }, (res) => `SCIM credential ${res && res.id ? res.id : ''} created.`)}
                      disabled={!!busy['gov:scim']}
                    >
                      {busy['gov:scim'] ? 'Creating…' : 'Create SCIM credential'}
                    </button>
                  </div>
                  {scimToken ? (
                    <p className="sec-note">
                      Token (shown once): <span className="sec-code">{scimToken}</span>
                    </p>
                  ) : null}
                </div>
                <div className="sec-list sec-gap">
                  {scimCredentials.length === 0 ? <p className="sec-empty">No SCIM credentials have been issued.</p> : scimCredentials.map((credential) => (
                    <div className="sec-row" key={credential.id}>
                      <div className="sec-row-head">
                        <strong>{credential.label || 'Unlabelled credential'}</strong>
                        <Pill value={credential.active ? 'active' : 'pending'}>{credential.active ? 'Active' : 'Inactive'}</Pill>
                      </div>
                      <small>Created {stamp(credential.created_at)} · last used {credential.last_used_at ? stamp(credential.last_used_at) : 'never'}</small>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="sec-head sec-gap-head">
              <div>
                <h2>Access reviews</h2>
                <p>A review snapshots every active user into a certification.</p>
              </div>
            </div>
            <div className="sec-form">
              <div className="sec-form-row">
                <div>
                  <label htmlFor="review-name">Review name</label>
                  <input id="review-name" value={reviewForm.name} onChange={(e) => setReviewForm({ ...reviewForm, name: e.target.value })} />
                </div>
                <div>
                  <label htmlFor="review-days">Due in (days)</label>
                  <input id="review-days" type="number" min="1" value={reviewForm.days} onChange={(e) => setReviewForm({ ...reviewForm, days: e.target.value })} />
                </div>
              </div>
              <div className="sec-actions">
                <button
                  className="btn btn-primary"
                  onClick={() => runGovernanceAction('review', { name: reviewForm.name || 'Access Review', days: Number(reviewForm.days) || 0 }, (res) => `Access review ${res && res.id ? res.id : ''} created with ${res ? res.certifications : 0} certifications.`)}
                  disabled={!!busy['gov:review']}
                >
                  {busy['gov:review'] ? 'Creating…' : 'Create access review'}
                </button>
              </div>
            </div>
            <div className="sec-list sec-gap">
              {governanceReviews.length === 0 ? <p className="sec-empty">No access review campaigns exist.</p> : governanceReviews.map((review) => (
                <div className="sec-row" key={review.id}>
                  <div className="sec-row-head">
                    <strong>{review.name || 'Unnamed review'}</strong>
                    <Pill value={review.status} />
                  </div>
                  <small>Due {stamp(review.due_at)}</small>
                </div>
              ))}
            </div>

            <div className="sec-head sec-gap-head">
              <div>
                <h2>Certifications</h2>
                <p>Decide whether each reviewed user keeps their access.</p>
              </div>
            </div>
            {certifications.length === 0 ? (
              <p className="sec-empty">No certifications have been raised.</p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr><th>User</th><th>Decision</th><th>Reason</th><th>Decided</th><th>Record a decision</th></tr>
                </thead>
                <tbody>
                  {certifications.map((cert) => (
                    <tr key={cert.id}>
                      <td>{cert.user_id}</td>
                      <td><Pill value={cert.decision} /></td>
                      <td>{cert.reason || '—'}</td>
                      <td>{cert.decided_at ? stamp(cert.decided_at) : 'Not decided'}</td>
                      <td>
                        <div className="sec-form-row">
                          <div>
                            <input
                              value={certReasons[cert.id] || ''}
                              placeholder="Reason (optional)"
                              onChange={(e) => setCertReasons({ ...certReasons, [cert.id]: e.target.value })}
                            />
                          </div>
                          {DECISIONS.map((option) => (
                            <button
                              key={option.value}
                              className="btn btn-secondary"
                              onClick={() => decideCertification(cert.id, option.value)}
                              disabled={!!busy[`cert:${cert.id}`]}
                            >
                              {busy[`cert:${cert.id}`] ? 'Saving…' : option.label}
                            </button>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        ) : (
          <p className="sec-empty">Governance data is not available for this account.</p>
        )}
      </section>

      <section className="card">
        <PanelHead title="Security incidents" description="Open and closed incidents for this company.">
          <button className="btn btn-secondary" onClick={() => loadSection('incidents', () => api.get('/auth/security/incidents/'), setIncidents)}>Reload</button>
        </PanelHead>
        <Gate error={errors.incidents} />
        {incidents.length === 0 ? (
          <p className="sec-empty">No incidents.</p>
        ) : (
          <div className="sec-list">
            {incidents.map((incident) => (
              <div className="sec-row" key={incident.id}>
                <div className="sec-row-head">
                  <strong>{incident.title || 'Untitled incident'}</strong>
                  <Pill value={incident.severity} />
                  <Pill value={incident.status} />
                </div>
                <small>{incident.summary || 'No summary recorded.'} · opened {stamp(incident.opened_at)}{incident.resolved_at ? ` · resolved ${stamp(incident.resolved_at)}` : ''}</small>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="card">
        <PanelHead
          title="Recent security events"
          description="The last events recorded for this company."
        >
          <button className="btn btn-secondary" onClick={() => loadSection('dashboard', () => api.get('/auth/security/dashboard/'), setData)} disabled={!!errors.dashboard}>Reload</button>
        </PanelHead>
        <Gate error={errors.dashboard} />
        {data && data.events && data.events.length ? (
          <div className="sec-list">
            {data.events.slice(0, 15).map((event) => (
              <div className="sec-row" key={event.id}>
                <div className="sec-row-head">
                  <strong>{event.event_type}</strong>
                  <Pill value={event.severity} />
                </div>
                <small>{event.message || 'No message recorded.'} · {stamp(event.created_at)}</small>
              </div>
            ))}
          </div>
        ) : (
          <p className="sec-empty">No security events have been recorded.</p>
        )}
      </section>
    </div>
  );
}
