import { useEffect, useState, useMemo } from 'react';
import { api } from '../api/client';
import { withStepUp } from '../api/stepUp';
import EmployeePicker from '../components/EmployeePicker';

const nice = (s) => (s || '').replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase());

const REQUEST_TYPES = [
    { value: 'salary', label: 'Salary change' },
    { value: 'position', label: 'Position / transfer' },
];

const EMPTY_FORM = {
    employee: '',
    request_type: 'salary',
    effective_date: '',
    reason: '',
    new_salary: '',
    job_title: '',
    department_obj: '',
};

export default function RequestTracking() {
    const [requests, setRequests] = useState([]);
    const [departments, setDepartments] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');
    const [selectedRequest, setSelectedRequest] = useState(null);
    const [showCreate, setShowCreate] = useState(false);
    const [form, setForm] = useState(EMPTY_FORM);
    const [saving, setSaving] = useState(false);
    const [decision, setDecision] = useState({ id: null, action: '', comments: '' });
    const [deciding, setDeciding] = useState(false);

    function load() {
        setLoading(true);
        setError('');
        api.get('/employees/hr-requests/')
            .then(data => setRequests(data.results ?? data))
            .catch(err => setError(err.message || 'Unable to load request history.'))
            .finally(() => setLoading(false));
    }

    useEffect(load, []);

    // Only needed for the position/transfer form, so it is fetched with the
    // rest of the page data rather than on every keystroke.
    useEffect(() => {
        api.get('/employees/departments/')
            .then(d => setDepartments(d.results ?? d ?? []))
            .catch(() => setDepartments([]));
    }, []);

    const stats = useMemo(() => ({
        pending: requests.filter(r => r.status === 'pending').length,
        approved: requests.filter(r => r.status === 'approved').length,
        rejected: requests.filter(r => r.status === 'rejected').length,
        total: requests.length
    }), [requests]);

    const openCreate = () => {
        setForm(EMPTY_FORM);
        setError('');
        setNotice('');
        setShowCreate(true);
    };

    async function submitRequest(ev) {
        ev.preventDefault();
        if (!form.employee) { setError('Select an employee.'); return; }

        // The payload keys are the ones EmployeeService.approve_hr_request
        // reads when the request is approved, so they must match exactly.
        const payload = form.request_type === 'salary'
            ? {
                new_salary: Number(form.new_salary),
                effective_date: form.effective_date || null,
                reason: form.reason,
            }
            : {
                job_title: form.job_title,
                department_obj: form.department_obj ? Number(form.department_obj) : null,
                effective_date: form.effective_date || null,
                reason: form.reason,
            };

        if (form.request_type === 'salary' && !(payload.new_salary > 0)) {
            setError('Enter a new salary greater than zero.'); return;
        }
        if (form.request_type === 'position' && !form.job_title.trim()) {
            setError('Enter the new job title.'); return;
        }

        setSaving(true);
        setError('');
        try {
            await api.post('/employees/hr-requests/', {
                employee: Number(form.employee),
                request_type: form.request_type,
                payload,
            });
            setShowCreate(false);
            setNotice('Request submitted and awaiting approval.');
            load();
        } catch (e) {
            setError(e.message || 'Could not submit the request.');
        } finally {
            setSaving(false);
        }
    }

    async function submitDecision(ev) {
        ev.preventDefault();
        if (!decision.id) return;
        setDeciding(true);
        setError('');
        try {
            // Only approval is gated by step-up MFA; rejecting a change cannot
            // move money, so the backend lets it through without a prompt.
            const send = () => api.post(`/employees/hr-requests/${decision.id}/${decision.action}/`, {
                comments: decision.comments,
            });
            await (decision.action === 'approve' ? withStepUp(send) : send());
            setNotice(`Request ${decision.action === 'approve' ? 'approved' : 'rejected'}.`);
            setDecision({ id: null, action: '', comments: '' });
            setSelectedRequest(null);
            load();
        } catch (e) {
            setError(e.message || `Could not ${decision.action} the request.`);
        } finally {
            setDeciding(false);
        }
    }

    const renderPayload = (payload) => {
        if (!payload || !Object.keys(payload).length) return 'No details provided.';
        return Object.entries(payload).map(([key, value]) => (
            <div key={key} className="request-payload-row">
                <span className="muted">{nice(key)}:</span>
                <strong>{value === null || value === '' ? '—' : String(value)}</strong>
            </div>
        ));
    };

    return (
        <div>
            <div className="page-header">
                <div>
                    <div className="eyebrow">GOVERNANCE & APPROVALS</div>
                    <h1>Request Tracking</h1>
                    <p className="page-subtitle">Monitor and manage employment changes, salary adjustments, and contract renewals.</p>
                </div>
                <button className="btn btn-primary compact" onClick={openCreate}>
                    + New Request
                </button>
            </div>

            {error && <div className="alert alert-error">{error}</div>}
            {notice && <div className="alert alert-success">{notice}</div>}

            <div className="employee-summary-grid">
                <div className="employee-summary-card">
                    <span>Pending Approval</span>
                    <strong className="text-warning">{stats.pending}</strong>
                    <small>Requires review</small>
                </div>
                <div className="employee-summary-card">
                    <span>Approved</span>
                    <strong className="text-success">{stats.approved}</strong>
                    <small>Changes applied</small>
                </div>
                <div className="employee-summary-card">
                    <span>Rejected</span>
                    <strong className="text-danger">{stats.rejected}</strong>
                    <small>Declined requests</small>
                </div>
                <div className="employee-summary-card">
                    <span>Total Requests</span>
                    <strong>{stats.total}</strong>
                    <small>Historical log</small>
                </div>
            </div>

            <div className="panel table-panel">
                <div className="panel-head">
                    <div>
                        <div className="eyebrow">HISTORY</div>
                        <h2>Change Requests <span className="count-pill">{requests.length}</span></h2>
                        <p>Full audit trail of submitted HR modifications and their approval status.</p>
                    </div>
                </div>

                {loading ? (
                    <div className="page-loading">Loading requests…</div>
                ) : (
                    <div className="table-wrap">
                        <table className="data-table modern-table">
                            <thead>
                                <tr>
                                    <th>Type</th>
                                    <th>Employee</th>
                                    <th>Submitted By</th>
                                    <th>Date</th>
                                    <th>Status</th>
                                    <th>HR Comments</th>
                                    <th>Details</th>
                                </tr>
                            </thead>
                            <tbody>
                                {requests.map(req => (
                                    <tr key={req.id}>
                                        <td><strong>{nice(req.request_type)}</strong></td>
                                        <td>{req.employee_name}</td>
                                        <td>{req.requested_by_name || '—'}</td>
                                        <td>{new Date(req.created_at).toLocaleDateString()}</td>
                                        <td>
                                            <span className={`mini-status status-${req.status}`}>
                                                {nice(req.status)}
                                            </span>
                                        </td>
                                        <td>{req.comments || '—'}</td>
                                        <td>
                                            <div className="table-actions">
                                                {req.status === 'pending' && (
                                                    <>
                                                        <button
                                                            className="btn btn-secondary compact"
                                                            onClick={() => setDecision({ id: req.id, action: 'approve', comments: '' })}
                                                        >
                                                            Approve
                                                        </button>
                                                        <button
                                                            className="btn btn-danger compact"
                                                            onClick={() => setDecision({ id: req.id, action: 'reject', comments: '' })}
                                                        >
                                                            Reject
                                                        </button>
                                                    </>
                                                )}
                                                <button
                                                    className="btn btn-ghost compact"
                                                    onClick={() => setSelectedRequest(req)}
                                                >
                                                    View
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                                {!requests.length && (
                                    <tr><td colSpan="7" className="empty-row">No requests found in the system.</td></tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {showCreate && (
                <div className="modal-overlay" onClick={() => !saving && setShowCreate(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()}>
                        <form onSubmit={submitRequest}>
                            <div className="modal-head">
                                <h3>New change request</h3>
                                <button type="button" className="btn-close" onClick={() => setShowCreate(false)}>&times;</button>
                            </div>
                            <div className="modal-body">
                                <div className="request-detail-grid">
                                    <div className="detail-item">
                                        <label>Employee</label>
                                        <EmployeePicker
                                            value={form.employee}
                                            required
                                            onChange={(id) => setForm({ ...form, employee: id })}
                                        />
                                    </div>
                                    <div className="detail-item">
                                        <label>Request type</label>
                                        <select
                                            value={form.request_type}
                                            onChange={e => setForm({ ...form, request_type: e.target.value })}
                                        >
                                            {REQUEST_TYPES.map(t => (
                                                <option key={t.value} value={t.value}>{t.label}</option>
                                            ))}
                                        </select>
                                    </div>
                                </div>

                                {form.request_type === 'salary' ? (
                                    <div className="detail-item">
                                        <label>New salary</label>
                                        <input
                                            type="number"
                                            min="0"
                                            step="0.01"
                                            value={form.new_salary}
                                            onChange={e => setForm({ ...form, new_salary: e.target.value })}
                                        />
                                    </div>
                                ) : (
                                    <div className="request-detail-grid">
                                        <div className="detail-item">
                                            <label>New job title</label>
                                            <input
                                                value={form.job_title}
                                                onChange={e => setForm({ ...form, job_title: e.target.value })}
                                            />
                                        </div>
                                        <div className="detail-item">
                                            <label>Department</label>
                                            <select
                                                value={form.department_obj}
                                                onChange={e => setForm({ ...form, department_obj: e.target.value })}
                                            >
                                                <option value="">No change</option>
                                                {departments.map(d => (
                                                    <option key={d.id} value={d.id}>{d.name}</option>
                                                ))}
                                            </select>
                                        </div>
                                    </div>
                                )}

                                <div className="request-detail-grid">
                                    <div className="detail-item">
                                        <label>Effective date</label>
                                        <input
                                            type="date"
                                            value={form.effective_date}
                                            onChange={e => setForm({ ...form, effective_date: e.target.value })}
                                        />
                                    </div>
                                    <div className="detail-item">
                                        <label>Reason</label>
                                        <input
                                            value={form.reason}
                                            onChange={e => setForm({ ...form, reason: e.target.value })}
                                        />
                                    </div>
                                </div>
                                <p className="hint">
                                    Approving applies these changes to the employee record straight away.
                                </p>
                            </div>
                            <div className="modal-foot">
                                <button type="button" className="btn btn-secondary" onClick={() => setShowCreate(false)}>Cancel</button>
                                <button type="submit" className="btn btn-primary" disabled={saving}>
                                    {saving ? 'Submitting…' : 'Submit request'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {decision.id && (
                <div className="modal-overlay" onClick={() => !deciding && setDecision({ id: null, action: '', comments: '' })}>
                    <div className="modal-content" onClick={e => e.stopPropagation()}>
                        <form onSubmit={submitDecision}>
                            <div className="modal-head">
                                <h3>{decision.action === 'approve' ? 'Approve request' : 'Reject request'}</h3>
                                <button type="button" className="btn-close" onClick={() => setDecision({ id: null, action: '', comments: '' })}>&times;</button>
                            </div>
                            <div className="modal-body">
                                {decision.action === 'approve' && (
                                    <p className="hint">
                                        Approving writes these changes to the employee record immediately.
                                    </p>
                                )}
                                <div className="detail-item">
                                    <label>Comments</label>
                                    <textarea
                                        rows={3}
                                        value={decision.comments}
                                        onChange={e => setDecision({ ...decision, comments: e.target.value })}
                                        placeholder="Optional note recorded against the request"
                                    />
                                </div>
                            </div>
                            <div className="modal-foot">
                                <button type="button" className="btn btn-secondary" onClick={() => setDecision({ id: null, action: '', comments: '' })}>Cancel</button>
                                <button
                                    type="submit"
                                    className={decision.action === 'approve' ? 'btn btn-primary' : 'btn btn-danger'}
                                    disabled={deciding}
                                >
                                    {deciding ? 'Saving…' : decision.action === 'approve' ? 'Approve' : 'Reject'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {selectedRequest && (
                <div className="modal-overlay" onClick={() => setSelectedRequest(null)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()}>
                        <div className="modal-head">
                            <h3>Request Details</h3>
                            <button className="btn-close" onClick={() => setSelectedRequest(null)}>&times;</button>
                        </div>
                        <div className="modal-body">
                            <div className="request-detail-grid">
                                <div className="detail-item">
                                    <label>Employee</label>
                                    <strong>{selectedRequest.employee_name}</strong>
                                </div>
                                <div className="detail-item">
                                    <label>Request Type</label>
                                    <strong>{nice(selectedRequest.request_type)}</strong>
                                </div>
                                <div className="detail-item">
                                    <label>Status</label>
                                    <span className={`mini-status status-${selectedRequest.status}`}>{nice(selectedRequest.status)}</span>
                                </div>
                                <div className="detail-item">
                                    <label>Submitted On</label>
                                    <strong>{new Date(selectedRequest.created_at).toLocaleString()}</strong>
                                </div>
                            </div>
                            <div className="detail-section">
                                <h4>Proposed Changes</h4>
                                <div className="payload-box">
                                    {renderPayload(selectedRequest.payload)}
                                </div>
                            </div>
                            {selectedRequest.comments && (
                                <div className="detail-section">
                                    <h4>HR Decision / Comments</h4>
                                    <div className="comments-box">{selectedRequest.comments}</div>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
