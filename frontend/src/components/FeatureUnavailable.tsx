import { Link } from 'react-router-dom';
import Icon from './Icon';
import { useFeatures } from '../context/FeatureContext';

const ICON_BY_REASON: Record<string, string> = {
  disabled: 'lock',
  environment: 'globe',
  rollout_zero: 'clock',
  rollout_bucket: 'trend',
};

const TONE_BY_REASON: Record<string, string> = {
  disabled: 'note',
  environment: 'note',
  rollout_zero: 'progress',
  rollout_bucket: 'progress',
};

interface FeatureUnavailableProps {
  featureKey: string;
  title: string;
  backTo?: string;
  backLabel?: string;
  children?: React.ReactNode;
}

export default function FeatureUnavailable({
  featureKey,
  title,
  backTo = '/dashboard',
  backLabel = 'Back to dashboard',
  children,
}: FeatureUnavailableProps) {
  const { messageFor, reasonFor, unavailable, loading } = useFeatures();

  const reason = reasonFor(featureKey);
  const message = messageFor(featureKey);

  if (unavailable) {
    return (
      <div className="feature-note" role="status">
        <div className="feature-note__icon" aria-hidden="true">
          <Icon name="alert" size={19} />
        </div>
        <div className="feature-note__body">
          <h2 className="feature-note__title">{title}</h2>
          <p className="feature-note__text">
            HRCloudPay could not load this module&apos;s availability, so it cannot
            tell you whether {title.toLowerCase()} is switched on for your workspace.
            Reload the page to try again.
          </p>
          <div className="feature-note__actions">
            <button type="button" className="btn btn-secondary" onClick={() => window.location.reload()}>
              Reload page
            </button>
            <Link className="btn btn-secondary" to={backTo}>{backLabel}</Link>
          </div>
        </div>
      </div>
    );
  }

  if (loading) return null;

  const body = message || `${title} is not available for your workspace.`;

  return (
    <div className={`feature-note${TONE_BY_REASON[reason] === 'progress' ? ' feature-note--progress' : ''}`} role="status">
      <div className="feature-note__icon" aria-hidden="true">
        <Icon name={ICON_BY_REASON[reason] || 'lock'} size={19} />
      </div>
      <div className="feature-note__body">
        <h2 className="feature-note__title">{title}</h2>
        <p className="feature-note__text">{body}</p>
        {children}
        <div className="feature-note__actions">
          <Link className="btn btn-secondary" to={backTo}>{backLabel}</Link>
        </div>
      </div>
    </div>
  );
}