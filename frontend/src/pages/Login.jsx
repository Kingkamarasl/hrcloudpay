import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';

export default function Login() {
  const { login, verifyMfa } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [mfaRequired, setMfaRequired] = useState(false);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      // Password step, or the MFA code step when we've already passed it once.
      if (mfaRequired) {
        await verifyMfa(mfaCode.trim());
        toast.success('Signed in successfully');
        navigate('/dashboard');
        return;
      }
      const result = await login(username, password);
      if (result.mfa_required) {
        // Credentials are good; the account has MFA enabled. Stay on this page
        // and collect the code instead of navigating into a redirect loop.
        setMfaRequired(true);
        setMfaCode('');
        return;
      }
      toast.success('Signed in successfully');
      navigate('/dashboard');
    } catch (err) {
      const msg = err.message || 'Login failed';
      setError(msg);
      toast.error(msg);
      // An expired/replayed MFA challenge fails server-side; let them retry
      // from the credentials step rather than re-entering a dead code.
      if (mfaRequired) setMfaRequired(false);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-shell">
        <aside className="auth-aside">
          <Link className="auth-brand" to="/"><span>H</span> HRCLOUDPAY</Link>
          <div className="auth-aside-copy"><p className="auth-kicker">WORKFORCE OPERATIONS, SIMPLIFIED</p><h1>Run people and payroll with confidence.</h1><p>One calm, reliable place for employee records, payroll, approvals and country-aware compliance.</p></div>
          <div className="auth-proof"><strong>Built for growing teams</strong><span>HR, payroll and compliance in one workspace.</span></div>
        </aside>
        <form className="auth-card" onSubmit={handleSubmit}>
        <Link className="auth-mobile-brand" to="/"><span>H</span> HRCLOUDPAY</Link>
        <p className="auth-kicker">WELCOME BACK</p>
        <h1>{mfaRequired ? 'Two-factor authentication' : 'Sign in to your workspace'}</h1>
        <p className="auth-subtitle">{mfaRequired ? 'Enter the 6-digit code from your authenticator app to finish signing in.' : 'Use your company credentials to continue.'}</p>
        {error && <div className="alert alert-error">{error}</div>}
        {mfaRequired ? (
          <div className="auth-field"><label>Authentication code</label><input placeholder="000000" value={mfaCode} onChange={(e) => setMfaCode(e.target.value)} required inputMode="numeric" autoComplete="one-time-code" autoFocus pattern="[0-9]*" maxLength={6} /></div>
        ) : (
          <>
            <div className="auth-field"><label>Username</label><input placeholder="Enter your username" value={username} onChange={(e) => setUsername(e.target.value)} required autoComplete="username" /></div>
            <div className="auth-field"><label>Password</label><input placeholder="Enter your password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" /></div>
          </>
        )}
        <button className="btn btn-primary" type="submit" disabled={submitting}>
          {submitting ? 'Signing in…' : (mfaRequired ? 'Verify code' : 'Sign in')}
        </button>
        {mfaRequired && <p className="auth-footer"><button type="button" className="btn btn-link" onClick={() => { setMfaRequired(false); setMfaCode(''); setError(''); }}>Back to sign in</button></p>}
        <p className="auth-footer">
          New to HRCLOUDPAY? <Link to="/register">Create your company workspace</Link>
        </p>
        </form>
      </section>
    </main>
  );
}
