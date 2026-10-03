import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuthProvider, useAuth } from '../context/AuthContext';
import { api } from '../api/client';
import { vi, describe, beforeEach, it, expect } from 'vitest';

// Mock the API client
vi.mock('../api/client', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

function TestComponent() {
  const { user, loading, login, logout } = useAuth();
  if (loading) return <div>Loading...</div>;
  return (
    <div>
      {user ? <span>Logged in as {user.username}</span> : <span>Not logged in</span>}
      <button onClick={() => login('testuser', 'password')}>Login</button>
      <button onClick={logout}>Logout</button>
    </div>
  );
}

describe('AuthContext', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows loading state initially', () => {
    api.get.mockReturnValue(new Promise(() => {})); // Never resolves
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  it('shows logged out state when no user', async () => {
    api.get.mockRejectedValue(new Error('Not authenticated'));
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );
    await waitFor(() => {
      expect(screen.getByText('Not logged in')).toBeInTheDocument();
    });
  });

  it('shows logged in state when user exists', async () => {
    const mockUser = { id: 1, username: 'testuser', role: 'owner' };
    api.get.mockResolvedValue(mockUser);
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );
    await waitFor(() => {
      expect(screen.getByText('Logged in as testuser')).toBeInTheDocument();
    });
  });

  it('calls login API on login button click', async () => {
    // First call to /auth/security/csrf/ - succeeds
    // Second call to /auth/me/ - fails (not authenticated)
    // Third call to /auth/security/login/ - succeeds
    api.get
      .mockResolvedValueOnce({}) // csrf
      .mockRejectedValueOnce(new Error('Not authenticated')); // me
    api.post.mockResolvedValue({ user: { id: 1, username: 'testuser' } });

    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Not logged in')).toBeInTheDocument();
    });

    await userEvent.click(screen.getByText('Login'));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/auth/security/login/', {
        username: 'testuser',
        password: 'password',
      });
    });
  });
});