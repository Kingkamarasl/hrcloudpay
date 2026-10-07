import React, { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';

/**
 * The two halves of password reset, as one component because they are one task:
 * a person who forgot a password cannot get in to click anything else, so the
 * second half has to be reachable from the emailed link and must not depend on
 * being signed in.
 *
 * Both screens say the same thing regardless of whether the address is known.
 * The server answers identically either way, and echoing a local "no such
 * account" here would reintroduce the enumeration oracle the endpoint is careful
 * to avoid.
 */
export default function ResetPassword() {
  const { uid, token } = useParams();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [sent, setSent] = useState(false);
  const [done, setDone] = useState(false);

  const confirming = Boolean(uid && token);

  async function request(e) {
    e.preventDefault();
    setBusy(true); setError('');
    try {
      await api.post('/auth/password-reset/', { email }, { auth: false });
      setSent(true);
    } catch (err) {
      setError(err.message || 'Could not send the reset link.');
    } finally {
      setBusy(false);
    }
  }

  async function confirmReset(e) {
    e.preventDefault();
    setError('');
    if (password !== confirm) {
      setError('The two passwords do not match.');
      return;
    }
    setBusy(true);
    try {
      await api.post('/auth/password-reset/confirm/', {
        uid, token, new_password: password,
      }, { auth: false });
      setDone(true);
      // Straight to the login page rather than straight into the app: the
      // session was destroyed on purpose, so staying here would show a page that
      // cannot work.
      setTimeout(() => navigate('/login'), 1800);
    } catch (err) {
      setError(err.message || 'Could not change the password.');
    } finally {
      setBusy(false);
    }
  }

  if (confirming) {
    return (
      <div className="auth-page">
        <form className="auth-card" onSubmit={confirmReset}>
          <div className="eyebrow">PASSWORD RESET</div>
          <h1>Choose a new password</h1>
          {done ? (
            <>
              <div className="alert alert-success">Your password has been changed. Taking you to the sign-in page.</div>
            </>
          ) : (
            <>
              {error && <div className="alert alert-error">{error}</div>}
              <div className="auth-field">
                <label>New password</label>
                <input type="password" value={password} autoComplete="new-password"
                       onChange={e => setPassword(e.target.value)} required />
              </div>
              <div className="auth-field">
                <label>Confirm new password</label>
                <input type="password" value={confirm} autoComplete="new-password"
                       onChange={e => setConfirm(e.target.value)} required />
              </div>
              <button className="btn btn-primary" type="submit" disabled={busy}>
                {busy ? 'Saving...' : 'Change password'}
              </button>
              <p className="auth-footer">
                Every existing session ends when this succeeds.
              </p>
            </>
          )}
        </form>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={request}>
        <div className="eyebrow">PASSWORD RESET</div>
        <h1>Reset your password</h1>
        {sent ? (
          <div className="alert alert-success">
            If that address belongs to an account, a reset link is on its way.
            Check your inbox, and your spam folder.
          </div>
        ) : (
          <>
            {error && <div className="alert alert-error">{error}</div>}
            <div className="auth-field">
              <label>Email address</label>
              <input type="email" value={email} autoComplete="email"
                     onChange={e => setEmail(e.target.value)} required />
            </div>
            <button className="btn btn-primary" type="submit" disabled={busy}>
              {busy ? 'Sending...' : 'Send reset link'}
            </button>
          </>
        )}
        <p className="auth-footer">
          <Link to="/login">Back to sign in</Link>
        </p>
      </form>
    </div>
  );
}