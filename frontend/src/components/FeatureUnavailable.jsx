import { Link } from 'react-router-dom';
import Icon from './Icon';
import { useFeatures } from '../context/FeatureContext';

// One icon per reason code, so the picture cannot contradict the sentence.
// These are the only four values `feature_status()` can return for a disabled
// flag; anything else falls through to the neutral entry below.
const ICON_BY_REASON = {
  disabled: 'lock',
  environment: 'globe',
  rollout_zero: 'clock',
  rollout_bucket: 'trend',
};

// A staged rollout is something arriving, not something that went wrong, so it
// wears the primary green. Everything else is a plain neutral note. Neither is
// ever red: nothing has errored.
const TONE_BY_REASON = {
  disabled: 'note',
  environment: 'note',
  rollout_zero: 'progress',
  rollout_bucket: 'progress',
};

/**
 * Stand-in for a module this company cannot use.
 *
 * `title` should be the module's own display name, because the body text
 * already begins with it - the API sentence reads "<name> is turned off for
 * your workspace", so the heading is a label, not an explanation.
 */
export default function FeatureUnavailable({
  featureKey,
  title,
  backTo = '/dashboard',
  backLabel = 'Back to dashboard',
  children,
}) {
  const { messageFor, reasonFor, unavailable, loading } = useFeatures();

  const reason = reasonFor(featureKey);
  const message = messageFor(featureKey);

  // Two cases have to be handled without an API sentence, because there is no
  // server verdict to quote.
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

  // No message means the server told us the flag is off but not why, which
  // should not happen. Say the one thing that is still true rather than
  // guessing at a cause.
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
