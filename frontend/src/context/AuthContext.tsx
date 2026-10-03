import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { api } from '../api/client';

interface Company {
  name?: string;
  plan?: string;
  logo_url?: string;
}

interface User {
  id: number;
  username: string;
  role: string;
  email?: string;
  is_staff?: boolean;
  is_superuser?: boolean;
  company?: Company;
  [key: string]: unknown;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<{ mfa_required: boolean; user: User | null }>;
  verifyMfa: (code: string) => Promise<User>;
  register: (payload: Record<string, unknown>) => Promise<User>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<User>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/auth/security/csrf/', { auth: false }).catch(() => null);
    api.get('/auth/me/')
      .then((data) => setUser(data as User | null))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  async function login(username: string, password: string) {
    await api.get('/auth/security/csrf/', { auth: false });
    const data = await api.post('/auth/security/login/', { username, password }) as { mfa_required?: boolean; user?: User };
    // MFA is enabled on this account. The server returned no `user` and issued no
    // session cookie, so `user` stays null until verifyMfa() succeeds. Returning
    // the flag lets the login page show the code prompt instead of pretending
    // the sign-in worked.
    if (data.mfa_required) return { mfa_required: true, user: null };
    setUser(data.user ?? null);
    return { mfa_required: false, user: data.user ?? null };
  }

  // Completes the MFA challenge started by login(). The server verifies the TOTP
  // code against the challenge cookie it set, then issues the session cookie.
  async function verifyMfa(code: string) {
    const data = await api.post('/auth/security/mfa/verify/', { code }) as { user: User };
    setUser(data.user);
    return data.user;
  }

  async function register(payload: Record<string, unknown>) {
    await api.get('/auth/security/csrf/', { auth: false });
    const data = await api.post('/auth/security/register/', payload) as { user: User };
    setUser(data.user);
    return data.user;
  }

  async function logout() {
    try {
      await api.post('/auth/logout/', {});
    } catch {
      // ignore network errors on logout
    }
    setUser(null);
  }

  async function refreshUser() {
    const data = await api.get('/auth/me/') as User;
    setUser(data);
    return data;
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, verifyMfa, register, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}