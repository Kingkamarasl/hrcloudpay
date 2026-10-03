import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

interface Toast {
  id: number;
  type: 'success' | 'error' | 'warning' | 'info';
  message: string;
  duration: number;
}

interface ToastContextType {
  success: (message: string, options?: { duration?: number }) => number;
  error: (message: string, options?: { duration?: number }) => number;
  warning: (message: string, options?: { duration?: number }) => number;
  info: (message: string, options?: { duration?: number }) => number;
  remove: (id: number) => void;
}

const ToastContext = createContext<ToastContextType | null>(null);

let toastId = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const remove = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = useCallback((type: Toast['type'], message: string, options: { duration?: number } = {}) => {
    const id = ++toastId;
    const duration = options.duration ?? (type === 'error' ? 6000 : 4000);
    setToasts((prev) => [...prev.slice(-4), { id, type, message, duration }]);
    if (duration > 0) {
      setTimeout(() => remove(id), duration);
    }
    return id;
  }, [remove]);

  const api = useMemo(() => ({
    success: (msg: string, opts?: { duration?: number }) => push('success', msg, opts),
    error: (msg: string, opts?: { duration?: number }) => push('error', msg, opts),
    warning: (msg: string, opts?: { duration?: number }) => push('warning', msg, opts),
    info: (msg: string, opts?: { duration?: number }) => push('info', msg, opts),
    remove,
  }), [push, remove]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toast-viewport" aria-live="polite" aria-relevant="additions">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.type}`} role="status">
            <span className="toast-msg">{t.message}</span>
            <button type="button" className="toast-close" onClick={() => remove(t.id)} aria-label="Dismiss">×</button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextType {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}