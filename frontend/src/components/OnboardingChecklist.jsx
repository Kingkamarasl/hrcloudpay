import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import Icon from './Icon';

const STORAGE_KEY = 'hrcloudpay_onboarding_dismissed';

export default function OnboardingChecklist({ employeeCount = 0, hasIntegrations = false }) {
  const { user } = useAuth();
  const [dismissed, setDismissed] = useState(() => {
    try { return localStorage.getItem(STORAGE_KEY) === '1'; } catch { return false; }
  });

  const steps = useMemo(() => {
    const company = user?.company || {};
    return [
      {
        id: 'activated',
        label: 'Activate company account',
        done: !!company.is_active,
        to: null,
        hint: 'Use the activation link emailed to your company address, or ask a platform admin.',
      },
      {
        id: 'payroll',
        label: 'Complete payroll setup',
        done: !!company.payroll_configured,
        to: '/payroll-setup',
        hint: 'Tax brackets, contributions and currency.',
      },
      {
        id: 'team',
        label: 'Invite your team',
        done: false, // soft – we don't have invite count easily; keep as guidance
        to: '/team',
        hint: 'Add HR, finance and department managers.',
        optional: true,
      },
      {
        id: 'employees',
        label: 'Add or import employees',
        done: employeeCount > 0,
        to: employeeCount > 0 ? '/employees' : '/integrations',
        hint: 'Create employees manually or import from CSV / connected systems.',
      },
      {
        id: 'integrations',
        label: 'Connect an integration (optional)',
        done: hasIntegrations,
        to: '/integrations',
        hint: 'Sync workforce or accounting data without re-entering everything.',
        optional: true,
      },
    ];
  }, [user, employeeCount, hasIntegrations]);

  const required = steps.filter((s) => !s.optional);
  const doneRequired = required.filter((s) => s.done).length;
  const allRequiredDone = doneRequired === required.length;

  if (dismissed || allRequiredDone) return null;

  function dismiss() {
    setDismissed(true);
    try { localStorage.setItem(STORAGE_KEY, '1'); } catch { /* ignore */ }
  }

  const progress = Math.round((doneRequired / required.length) * 100);

  return (
    <div className="onboarding-card">
      <div className="onboarding-head">
        <div>
          <h2>Get your workspace ready</h2>
          <p>Complete these steps to unlock the full HRCloudPay experience.</p>
        </div>
        <button type="button" className="btn-link" onClick={dismiss}>Dismiss</button>
      </div>
      <div className="onboarding-progress">
        <div className="onboarding-progress-bar" style={{ width: `${progress}%` }} />
      </div>
      <p className="onboarding-progress-label">{doneRequired} of {required.length} required steps complete</p>
      <ul className="onboarding-steps">
        {steps.map((step) => (
          <li key={step.id} className={step.done ? 'done' : ''}>
            <span className="onboarding-check">{step.done ? '✓' : ''}</span>
            <div className="onboarding-step-body">
              <strong>{step.label}{step.optional ? ' (optional)' : ''}</strong>
              <small>{step.hint}</small>
            </div>
            {!step.done && step.to && (
              <Link to={step.to} className="btn btn-secondary btn-sm">
                Go <Icon name="arrow" size={14} />
              </Link>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
