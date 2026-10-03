import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';

interface Employee {
  id: number;
  full_name?: string;
  first_name?: string;
  last_name?: string;
  id_card_no?: string;
  employee_code?: string;
  job_title?: string;
}

interface EmployeePickerProps {
  value?: number | string | null;
  onChange?: (id: number | string, employee: Employee | null) => void;
  required?: boolean;
  placeholder?: string;
  disabled?: boolean;
}

/**
 * Searchable employee selector.
 * Matches id card no, employee code, name, email (API ?q=).
 */
export default function EmployeePicker({
  value,
  onChange,
  required = false,
  placeholder = 'Search by ID no, code, or name…',
  disabled = false,
}: EmployeePickerProps) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Employee[]>([]);
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<Employee | null>(null);
  const [loading, setLoading] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  // If value is set externally without selected label, try resolve once
  useEffect(() => {
    if (!value) {
      setSelected(null);
      return;
    }
    if (selected && String(selected.id) === String(value)) return;
    let cancelled = false;
    api.get<Employee>(`/employees/employees/${value}/`)
      .then((emp) => {
        if (!cancelled) {
          setSelected(emp);
          setQuery(label(emp));
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [value]);

  function label(emp: Employee | null) {
    if (!emp) return '';
    const name = emp.full_name || `${emp.first_name || ''} ${emp.last_name || ''}`.trim();
    const id = emp.id_card_no || emp.employee_code || '';
    return id ? `${name} · ${id}` : name;
  }

  function search(q: string) {
    setQuery(q);
    setOpen(true);
    if (timer.current) clearTimeout(timer.current);
    if (!q || q.trim().length < 1) {
      setResults([]);
      return;
    }
    timer.current = setTimeout(async () => {
      setLoading(true);
      try {
        const data = await api.get<{ results?: Employee[] } | Employee[]>(`/employees/employees/?q=${encodeURIComponent(q.trim())}`);
        const list = Array.isArray(data) ? data : (data?.results ?? []);
        setResults(Array.isArray(list) ? list.slice(0, 25) : []);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 250);
  }

  function choose(emp: Employee) {
    setSelected(emp);
    setQuery(label(emp));
    setOpen(false);
    setResults([]);
    onChange?.(emp.id, emp);
  }

  function clear() {
    setSelected(null);
    setQuery('');
    setResults([]);
    onChange?.('', null);
  }

  return (
    <div className="employee-picker" ref={boxRef} style={{ position: 'relative' }}>
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          type="text"
          value={query}
          disabled={disabled}
          required={required && !value}
          placeholder={placeholder}
          onChange={(e) => search(e.target.value)}
          onFocus={() => query && setOpen(true)}
          autoComplete="off"
          style={{ flex: 1 }}
        />
        {value ? (
          <button type="button" className="btn-link" onClick={clear} title="Clear">Clear</button>
        ) : null}
      </div>
      {/* Hidden required field for native form validation when using value */}
      {required && <input type="hidden" value={value || ''} required />}
      {open && (query.trim().length > 0) && (
        <div
          className="employee-picker-dropdown"
          style={{
            position: 'absolute',
            zIndex: 30,
            left: 0,
            right: 0,
            top: '100%',
            marginTop: 4,
            background: 'var(--card, #fff)',
            border: '1px solid var(--border, #e2e8f0)',
            borderRadius: 8,
            maxHeight: 240,
            overflowY: 'auto',
            boxShadow: '0 8px 24px rgba(0,0,0,0.08)',
          }}
        >
          {loading && <div style={{ padding: '0.6rem 0.75rem', fontSize: 13, color: '#64748b' }}>Searching…</div>}
          {!loading && results.length === 0 && (
            <div style={{ padding: '0.6rem 0.75rem', fontSize: 13, color: '#64748b' }}>No employees match “{query}”.</div>
          )}
          {results.map((emp) => (
            <button
              key={emp.id}
              type="button"
              onClick={() => choose(emp)}
              style={{
                display: 'block',
                width: '100%',
                textAlign: 'left',
                border: 0,
                background: String(value) === String(emp.id) ? '#f0fdf9' : 'transparent',
                padding: '0.55rem 0.75rem',
                cursor: 'pointer',
                borderBottom: '1px solid var(--border, #f1f5f9)',
              }}
            >
              <strong style={{ display: 'block', fontSize: 13 }}>
                {emp.full_name || `${emp.first_name} ${emp.last_name}`}
              </strong>
              <small style={{ color: '#64748b' }}>
                {[emp.id_card_no && `ID ${emp.id_card_no}`, emp.employee_code && `Code ${emp.employee_code}`, emp.job_title]
                  .filter(Boolean)
                  .join(' · ')}
              </small>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}