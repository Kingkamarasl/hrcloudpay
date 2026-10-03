import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { vi, describe, it, expect, beforeEach } from 'vitest';

// Mock the AuthContext before importing ProtectedRoute
const mockUseAuth = vi.fn();

vi.mock('../context/AuthContext', () => ({
  useAuth: () => mockUseAuth(),
  AuthContext: {
    Provider: ({ children }) => children,
  },
}));

import ProtectedRoute from '../components/ProtectedRoute';

describe('ProtectedRoute', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows loading skeleton when loading', () => {
    mockUseAuth.mockReturnValue({ user: null, loading: true, login: vi.fn(), logout: vi.fn() });
    render(
      <MemoryRouter initialEntries={['/test']}>
        <ProtectedRoute>
          <div>Protected Content</div>
        </ProtectedRoute>
      </MemoryRouter>
    );
    expect(screen.queryByText('Protected Content')).not.toBeInTheDocument();
  });

  it('redirects to /login when not authenticated', () => {
    mockUseAuth.mockReturnValue({ user: null, loading: false, login: vi.fn(), logout: vi.fn() });
    render(
      <MemoryRouter initialEntries={['/test']}>
        <ProtectedRoute>
          <div>Protected Content</div>
        </ProtectedRoute>
      </MemoryRouter>
    );
    expect(screen.queryByText('Protected Content')).not.toBeInTheDocument();
  });

  it('renders children when authenticated', () => {
    mockUseAuth.mockReturnValue({ user: { id: 1, username: 'testuser', role: 'owner' }, loading: false, login: vi.fn(), logout: vi.fn() });
    render(
      <MemoryRouter initialEntries={['/test']}>
        <ProtectedRoute>
          <div>Protected Content</div>
        </ProtectedRoute>
      </MemoryRouter>
    );
    expect(screen.getByText('Protected Content')).toBeInTheDocument();
  });

  it('redirects when user does not have required role', () => {
    mockUseAuth.mockReturnValue({ user: { id: 1, username: 'testuser', role: 'employee' }, loading: false, login: vi.fn(), logout: vi.fn() });
    render(
      <MemoryRouter initialEntries={['/test']}>
        <ProtectedRoute roles={['owner', 'admin']}>
          <div>Admin Content</div>
        </ProtectedRoute>
      </MemoryRouter>
    );
    expect(screen.queryByText('Admin Content')).not.toBeInTheDocument();
  });

  it('renders when user has required role', () => {
    mockUseAuth.mockReturnValue({ user: { id: 1, username: 'testuser', role: 'owner' }, loading: false, login: vi.fn(), logout: vi.fn() });
    render(
      <MemoryRouter initialEntries={['/test']}>
        <ProtectedRoute roles={['owner', 'admin']}>
          <div>Admin Content</div>
        </ProtectedRoute>
      </MemoryRouter>
    );
    expect(screen.getByText('Admin Content')).toBeInTheDocument();
  });
});