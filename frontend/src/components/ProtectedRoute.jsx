import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Skeleton } from './Skeleton';

export default function ProtectedRoute({ children, roles }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="page-loading-shell">
        <div className="page-loading-card">
          <Skeleton height={28} width="40%" />
          <Skeleton height={14} width="70%" />
          <Skeleton height={14} width="55%" />
        </div>
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;

  // Management consoles are hidden from the sidebar for other roles; guarding the
  // route too keeps a typed URL from landing on a page whose every control 403s.
  if (roles && !roles.includes(user.role)) return <Navigate to="/dashboard" replace />;

  return children;
}
