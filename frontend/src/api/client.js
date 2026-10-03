// Explicit VITE_API_URL always wins (set it in frontend/.env). Otherwise:
// in `npm run dev` (split dev servers), default to the Django dev server
// at :8000. In a production build served BY Django itself (single-server
// mode), default to a relative '/api' so it works on whatever host/port
// Django is actually running on.
const API_URL = import.meta.env.VITE_API_URL
  || (import.meta.env.DEV ? 'http://localhost:8000/api' : '/api');

function getToken() { return null; }
export function setToken(_token) { /* Browser authentication uses HttpOnly cookies. */ }

function getCookie(name) {
  const value = document.cookie.split('; ').find(row => row.startsWith(`${name}=`));
  return value ? decodeURIComponent(value.split('=').slice(1).join('=')) : '';
}

async function request(path, { method = 'GET', body, auth = true } = {}) {
  const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;
  // Never set Content-Type for FormData — the browser must add the multipart boundary.
  const headers = isFormData ? {} : { 'Content-Type': 'application/json' };
  if (auth && !['GET','HEAD','OPTIONS'].includes(method)) {
    const csrf = getCookie('csrftoken');
    if (csrf) headers['X-CSRFToken'] = csrf;
  }

  let res;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers,
      credentials: 'include',
      body: body ? (isFormData ? body : JSON.stringify(body)) : undefined,
    });
  } catch (networkErr) {
    const error = new Error(
      networkErr?.message?.includes('Failed to fetch')
        ? 'Cannot reach the API server. Check that the backend is running and VITE_API_URL is correct.'
        : (networkErr.message || 'Network error'),
    );
    error.status = 0;
    throw error;
  }

  let data = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!res.ok) {
    if (res.status === 401 && auth) {
      /* HttpOnly session cookie is cleared by logout/server expiry. */
      if (typeof window !== 'undefined' && window.location && !window.location.pathname.startsWith('/login')) {
        window.location.assign('/login');
      }
    }
    let message =
      (data && (data.detail || data.message)) ||
      (typeof data === 'object' && data ? JSON.stringify(data) : null) ||
      `Request failed (${res.status})`;
    // DRF validation errors are often { field: ["msg"] }
    if (typeof data === 'object' && data && !data.detail && !data.message) {
      const parts = Object.entries(data).map(([k, v]) => {
        const val = Array.isArray(v) ? v.join(', ') : String(v);
        return `${k}: ${val}`;
      });
      if (parts.length) message = parts.join('; ');
    }
    const error = new Error(message);
    error.status = res.status;
    error.data = data;
    throw error;
  }

  return data;
}

export async function downloadFile(path) {
  const res = await fetch(`${API_URL}${path}`, { credentials: 'include' });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Download failed (${res.status})`);
  }
  return { blob: await res.blob(), disposition: res.headers.get('content-disposition') || '' };
}

export const api = {
  get: (path, opts = {}) => request(path, { ...opts }),
  post: (path, body, opts = {}) => request(path, { method: 'POST', body, ...opts }),
  put: (path, body) => request(path, { method: 'PUT', body }),
  patch: (path, body) => request(path, { method: 'PATCH', body }),
  // `body` is optional and used by the few endpoints where a destructive action
  // needs its confirmation carried in the request (typing the exact username, for
  // instance) rather than in a second round trip.
  del: (path, body) => request(path, { method: 'DELETE', body }),
  upload: (path, formData) => request(path, { method: 'POST', body: formData }),
};

export { API_URL };
