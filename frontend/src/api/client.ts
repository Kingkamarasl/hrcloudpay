// Explicit VITE_API_URL always wins (set it in frontend/.env). Otherwise:
// in `npm run dev` (split dev servers), default to the Django dev server
// at :8000. In a production build served BY Django itself (single-server
// mode), default to a relative '/api' so it works on whatever host/port
// Django is actually running on.
const API_URL = import.meta.env.VITE_API_URL
  || (import.meta.env.DEV ? 'http://localhost:8000/api' : '/api');

export function setToken(_token: string): void { /* Browser authentication uses HttpOnly cookies. */ }

function getCookie(name: string): string {
  const value = document.cookie.split('; ').find(row => row.startsWith(`${name}=`));
  return value ? decodeURIComponent(value.split('=').slice(1).join('=')) : '';
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  auth?: boolean;
}

interface ApiError extends Error {
  status: number;
  data?: unknown;
}

interface ApiResponse {
  detail?: string;
  message?: string;
  [key: string]: unknown;
}

async function request(path: string, { method = 'GET', body, auth = true }: RequestOptions = {}): Promise<unknown> {
  const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;
  // Never set Content-Type for FormData — the browser must add the multipart boundary.
  const headers: Record<string, string> = isFormData ? {} : { 'Content-Type': 'application/json' };
  if (auth && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const csrf = getCookie('csrftoken');
    if (csrf) headers['X-CSRFToken'] = csrf;
  }

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers,
      credentials: 'include',
      body: body ? (isFormData ? body : JSON.stringify(body)) : undefined,
    });
  } catch (networkErr: unknown) {
    const err = networkErr as Error;
    const error = new Error(
      err?.message?.includes('Failed to fetch')
        ? 'Cannot reach the API server. Check that the backend is running and VITE_API_URL is correct.'
        : (err.message || 'Network error'),
    ) as ApiError;
    error.status = 0;
    throw error;
  }

  let data: unknown = null;
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
    let detail = data && typeof data === 'object' && (data as ApiResponse).detail;
    let msg = data && typeof data === 'object' && (data as ApiResponse).message;
    let fallback: string | null = typeof data === 'object' && data ? (JSON.stringify(data) as string) : null;
    let message: string = (detail || msg || fallback || `Request failed (${res.status})`) as string;
    // DRF validation errors are often { field: ["msg"] }
    if (typeof data === 'object' && data && !(data as ApiResponse).detail && !(data as ApiResponse).message) {
      const parts = Object.entries(data as Record<string, unknown>).map(([k, v]) => {
        const val = Array.isArray(v) ? v.join(', ') : String(v);
        return `${k}: ${val}`;
      });
      if (parts.length) message = parts.join('; ');
    }
    const error = new Error(message) as ApiError;
    error.status = res.status;
    error.data = data;
    throw error;
  }

  return data;
}

export async function downloadFile(path: string): Promise<{ blob: Blob; disposition: string }> {
  const res = await fetch(`${API_URL}${path}`, { credentials: 'include' });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Download failed (${res.status})`);
  }
  return { blob: await res.blob(), disposition: res.headers.get('content-disposition') || '' };
}

export const api = {
  get: <T,>(path: string, opts: RequestOptions = {}) => request(path, { ...opts }) as Promise<T>,
  post: <T,>(path: string, body: unknown, opts: RequestOptions = {}) => request(path, { method: 'POST', body, ...opts }) as Promise<T>,
  put: <T,>(path: string, body: unknown) => request(path, { method: 'PUT', body }) as Promise<T>,
  patch: <T,>(path: string, body: unknown) => request(path, { method: 'PATCH', body }) as Promise<T>,
  // `body` is optional and used by the few endpoints where a destructive action
  // needs its confirmation carried in the request (typing the exact username, for
  // instance) rather than in a second round trip.
  del: <T,>(path: string, body?: unknown) => request(path, { method: 'DELETE', body }) as Promise<T>,
  upload: (path: string, formData: FormData) => request(path, { method: 'POST', body: formData }),
};

export { API_URL };