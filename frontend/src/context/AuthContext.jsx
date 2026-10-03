import { createContext, useContext, useEffect, useState } from 'react';
import { api } from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/auth/security/csrf/', { auth: false }).catch(() => null);
    api.get('/auth/me/')
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  async function login(username, password) {
    await api.get('/auth/security/csrf/', { auth: false });
    const data = await api.post('/auth/security/login/', { username, password });
    // MFA is enabled on this account. The server returned no `user` and issued no
    // session cookie, so `user` stays null until verifyMfa() succeeds. Returning
    // the flag lets the login page show the code prompt instead of pretending
    // the sign-in worked.
    if (data.mfa_required) return { mfa_required: true, user: null };
    setUser(data.user);
    return { mfa_required: false, user: data.user };
  }

  // Completes the MFA challenge started by login(). The server verifies the TOTP
  // code against the challenge cookie it set, then issues the session cookie.
  async function verifyMfa(code) {
    const data = await api.post('/auth/security/mfa/verify/', { code });
    setUser(data.user);
    return data.user;
  }

  async function register(payload) {
    await api.get('/auth/security/csrf/', { auth: false });
    const data = await api.post('/auth/security/register/', payload);
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
    const data = await api.get('/auth/me/');
    setUser(data);
    return data;
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, verifyMfa, register, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
