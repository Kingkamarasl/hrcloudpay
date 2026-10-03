import { Link } from 'react-router-dom';
import Icon from './Icon';
import { AI_MINIMUM_PLAN, PLAN_LABELS } from '../constants/plans';

export default function UpgradePrompt({
  feature = 'this feature',
  requiredPlan = AI_MINIMUM_PLAN,
  compact = false,
}) {
  const planName = PLAN_LABELS[requiredPlan] || requiredPlan;

  if (compact) {
    return (
      <div className="upgrade-prompt upgrade-prompt-compact">
        <Icon name="alert" size={16} />
        <span>
          {feature} requires the <strong>{planName}</strong> plan or higher.
        </span>
        <Link to="/billing" className="btn-link">Upgrade</Link>
      </div>
    );
  }

  return (
    <div className="upgrade-prompt">
      <div className="upgrade-prompt-icon">
        <Icon name="wallet" size={24} />
      </div>
      <div>
        <h3>Unlock {feature}</h3>
        <p>
          This capability is available on the <strong>{planName}</strong> plan and above.
          Upgrade to get full access for your team.
        </p>
        <Link to="/billing" className="btn btn-primary" style={{ width: 'auto' }}>
          View plans &amp; upgrade
        </Link>
      </div>
    </div>
  );
}
