import { useEffect, useState } from 'react';
import { api } from '../api/client';

const ROLE_LABELS = {
  admin: 'Admin',
  hr: 'HR Manager',
  finance: 'Finance Manager',
  department_manager: 'Department Manager',
  employee: 'Employee (self-service)',
};

const emptyForm = {
  username: '',
  email: '',
  password: '',
  role: 'hr',
  managed_department: '',
  employee_id: '',
};

export default function Team() {
  const [users, setUsers] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState('');

  function load() {
    setLoading(true);
    Promise.all([
      api.get('/auth/users/'),
      api.get('/employees/employees/'),
    ])
      .then(([usersData, empData]) => {
        setUsers(usersData);
        setEmployees(empData.results ?? empData);
      })
      .catch((err) => {
        // Without this the page fell through to "No team accounts yet besides
        // the owner", so a failed request was indistinguishable from an
        // empty team.
        setError(err.message || 'Could not load the team.');
      })
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    try {
      const payload = { ...form };
      if (payload.role !== 'department_manager') delete payload.managed_department;
      if (payload.role !== 'employee') delete payload.employee_id;
      if (payload.employee_id) payload.employee_id = Number(payload.employee_id);
      await api.post('/auth/users/', payload);
      setForm(emptyForm);
      setShowForm(false);
      load();
    } catch (err) {
      setError(err.message || 'Failed to create account');
    }
  }

  async function updateRole(userId, role) {
    setError('');
    try {
      await api.patch(`/auth/users/${userId}/`, { role });
      load();
    } catch (err) {
      setError(err.message || 'Failed to update role');
    }
  }

  async function deactivate(userId) {
    setError('');
    try {
      await api.del(`/auth/users/${userId}/`);
      load();
    } catch (err) {
      setError(err.message || 'Failed to deactivate account');
    }
  }

  const availableEmployees = employees.filter((e) => !users.some((u) => u.employee_name === e.full_name));

  return (
    <div>
      <div className="page-header">
        <h1>Team Accounts</h1>
        <button className="btn btn-primary" onClick={() => setShowForm((s) => !s)}>
          {showForm ? 'Cancel' : '+ Add team member'}
        </button>
      </div>
      <p className="page-subtitle">
        Every login is created here, under your company - HR Manager, Finance Manager, Department
        Manager, or an Employee self-service login linked to an existing employee record.
      </p>

      {error && <div className="alert alert-error">{error}</div>}

      {showForm && (
        <form className="card" onSubmit={handleSubmit}>
          <div className="form-row">
            <div>
              <label>Username</label>
              <input value={form.username} onChange={(e) => update('username', e.target.value)} required />
            </div>
            <div>
              <label>Email</label>
              <input type="email" value={form.email} onChange={(e) => update('email', e.target.value)} required />
            </div>
          </div>
          <div className="form-row">
            <div>
              <label>Password</label>
              <input type="password" value={form.password} onChange={(e) => update('password', e.target.value)} required />
            </div>
            <div>
              <label>Role</label>
              <select value={form.role} onChange={(e) => update('role', e.target.value)}>
                <option value="admin">Admin (full access)</option>
                <option value="hr">HR Manager</option>
                <option value="finance">Finance Manager</option>
                <option value="department_manager">Department Manager</option>
                <option value="employee">Employee (self-service)</option>
              </select>
            </div>
          </div>

          {form.role === 'department_manager' && (
            <>
              <label>Department they manage</label>
              <input
                value={form.managed_department}
                onChange={(e) => update('managed_department', e.target.value)}
                placeholder="Must match employees' department field exactly"
                required
              />
            </>
          )}

          {form.role === 'employee' && (
            <>
              <label>Link to employee record</label>
              <select value={form.employee_id} onChange={(e) => update('employee_id', e.target.value)} required>
                <option value="">Select employee</option>
                {availableEmployees.map((emp) => (
                  <option key={emp.id} value={emp.id}>{emp.full_name} ({emp.employee_code})</option>
                ))}
              </select>
            </>
          )}

          <button className="btn btn-primary" type="submit" style={{ marginTop: '0.75rem' }}>
            Create account
          </button>
        </form>
      )}

      {loading ? (
        <p>Loading...</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Username</th>
              <th>Email</th>
              <th>Role</th>
              <th>Department</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.username}</td>
                <td>{u.email}</td>
                <td>
                  <select value={u.role} onChange={(e) => updateRole(u.id, e.target.value)}>
                    {Object.entries(ROLE_LABELS).map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                </td>
                <td>{u.role === 'department_manager' ? u.managed_department : (u.employee_name || '—')}</td>
                <td>{u.is_active ? 'Active' : 'Deactivated'}</td>
                <td>
                  {u.is_active && (
                    <button className="btn-link" onClick={() => deactivate(u.id)}>Deactivate</button>
                  )}
                </td>
              </tr>
            ))}
            {users.length === 0 && (
              <tr><td colSpan={6} className="empty-row">No team accounts yet besides the owner. Add one above.</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
