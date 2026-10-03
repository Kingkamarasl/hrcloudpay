import Icon from './Icon';
import { Link } from 'react-router-dom';

export default function EmptyState({
  icon = 'file',
  title = 'Nothing here yet',
  description = 'When there is data to show, it will appear in this space.',
  actionLabel,
  actionTo,
  onAction,
  secondaryLabel,
  secondaryTo,
}) {
  return (
    <div className="empty-state">
      <div className="empty-state-icon">
        <Icon name={icon} size={28} />
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      <div className="empty-state-actions">
        {actionLabel && actionTo && (
          <Link to={actionTo} className="btn btn-primary" style={{ width: 'auto' }}>
            {actionLabel}
          </Link>
        )}
        {actionLabel && onAction && !actionTo && (
          <button type="button" className="btn btn-primary" style={{ width: 'auto' }} onClick={onAction}>
            {actionLabel}
          </button>
        )}
        {secondaryLabel && secondaryTo && (
          <Link to={secondaryTo} className="btn btn-secondary">
            {secondaryLabel}
          </Link>
        )}
      </div>
    </div>
  );
}
