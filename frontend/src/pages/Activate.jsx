import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api/client';

export default function Activate() {
  const { companyId, token } = useParams();
  const [status, setStatus] = useState('activating');
  const [error, setError] = useState('');

  useEffect(() => {
    api
      .post(`/auth/activate/${companyId}/${token}/`, {}, { auth: false })
      .then(() => setStatus('done'))
      .catch((err) => {
        setError(err.message || 'Activation failed');
        setStatus('error');
      });
  }, [companyId, token]);

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>Account activation</h1>
        {status === 'activating' && <p>Activating your account...</p>}
        {status === 'done' && (
          <>
            <div className="alert alert-success">Your account is now active!</div>
            <p>Next, log in and complete your payroll setup so we can calculate salaries correctly for your country.</p>
            <Link className="btn btn-primary" to="/login">Go to login</Link>
          </>
        )}
        {status === 'error' && <div className="alert alert-error">{error}</div>}
      </div>
    </div>
  );
}
