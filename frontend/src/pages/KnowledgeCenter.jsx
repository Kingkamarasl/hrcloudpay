import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { COMPANY_ROLES, ROLE_LABELS, canManageKnowledge } from '../constants/roles';

const STATUS = ['all', 'active', 'processing', 'failed', 'archived'];
const SOURCE_TYPES = [
  { value: 'policy', label: 'HR policy' },
  { value: 'handbook', label: 'Employee handbook' },
  { value: 'contract_template', label: 'Contract template' },
  { value: 'guide', label: 'HR guide' },
  { value: 'other', label: 'Other' },
];

export default function KnowledgeCenter() {
  const { user } = useAuth();
  const mayManage = canManageKnowledge(user?.role);
  const [docs, setDocs] = useState([]);
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [showUpload, setShowUpload] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const rows = await api.get('/ai/knowledge/');
      setDocs(rows || []);
      setError('');
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { load(); }, []);

  // Hold only the id, not the row. Holding the row made the open drawer a stale
  // snapshot: archiving from the drawer refreshed the list but left the drawer
  // still reading "active" and still offering Archive, which re-PATCHed the
  // document and wrote a second, meaningless audit event.
  const selected = useMemo(() => docs.find((d) => d.id === selectedId) || null, [docs, selectedId]);

  const filtered = useMemo(
    () => docs.filter((d) => (status === 'all' || d.lifecycle_status === status)
      && (`${d.title} ${d.description} ${d.file_name}`.toLowerCase().includes(q.toLowerCase()))),
    [docs, q, status],
  );

  async function action(id, type) {
    setError('');
    try {
      if (type === 'reindex') {
        // Reindexing is its own endpoint; no PATCH is needed to touch the URL.
        await api.post('/ai/knowledge/reindex/', { document_id: id });
      } else {
        await api.patch(`/ai/knowledge/${id}/`, { action: type });
      }
      await load();
    } catch (e) {
      setError(e.message);
    }
  }

  return <div className="knowledge-page">
    <div className="page-header">
      <div>
        <div className="eyebrow">AI KNOWLEDGE CENTER</div>
        <h1>Company knowledge</h1>
        <p className="page-subtitle">Manage the policies, handbooks and documents HRCloudPay AI can use—by version, lifecycle and role.</p>
      </div>
      {mayManage && <button className="btn btn-primary" onClick={() => setShowUpload(true)}>+ Add knowledge</button>}
    </div>
    {error && <div className="alert alert-error" role="alert">{error}</div>}
    <div className="knowledge-stats">
      <Stat label="Documents" value={docs.length} />
      <Stat label="Active" value={docs.filter((x) => x.lifecycle_status === 'active').length} />
      <Stat label="Processing" value={docs.filter((x) => x.lifecycle_status === 'processing').length} />
      <Stat label="Needs attention" value={docs.filter((x) => x.lifecycle_status === 'failed' || x.needs_reindex).length} />
    </div>
    <div className="card knowledge-toolbar">
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search knowledge…" />
      <div className="segmented">{STATUS.map((s) => <button key={s} className={status === s ? 'active' : ''} onClick={() => setStatus(s)}>{s[0].toUpperCase() + s.slice(1)}</button>)}</div>
    </div>
    <div className="knowledge-grid">
      {loading
        ? <div className="card page-loading">Loading knowledge…</div>
        : filtered.map((doc) => <article className="card knowledge-card" key={doc.id} onClick={() => setSelectedId(doc.id)}>
          <div className="knowledge-card-top"><span className={`status-pill ${doc.lifecycle_status}`}>{doc.lifecycle_status}</span><span>v{doc.version}</span></div>
          <h3>{doc.title}</h3>
          <p>{doc.description || 'No description provided.'}</p>
          <div className="knowledge-meta"><span>{doc.source_type_label}</span><span>{doc.chunk_count} chunks</span></div>
          <div className="knowledge-access">{(doc.allowed_roles || []).map((r) => <span key={r}>{ROLE_LABELS[r] || r}</span>)}</div>
          {doc.needs_reindex && <small className="muted">Index is stale — reindex to restore semantic search.</small>}
          {mayManage && <div className="knowledge-card-actions">
            {doc.lifecycle_status === 'active' && <button onClick={(e) => { e.stopPropagation(); action(doc.id, 'archive'); }}>Archive</button>}
            {doc.lifecycle_status === 'archived' && <button onClick={(e) => { e.stopPropagation(); action(doc.id, 'restore'); }}>Restore</button>}
            {(doc.lifecycle_status === 'failed' || doc.needs_reindex) && <button onClick={(e) => { e.stopPropagation(); action(doc.id, 'reindex'); }}>{doc.lifecycle_status === 'failed' ? 'Retry index' : 'Reindex'}</button>}
          </div>}
        </article>)}
    </div>
    {!loading && !filtered.length && <div className="card empty-state"><h3>No matching knowledge</h3><p>Add a policy, handbook or HR guide to ground the AI assistant.</p></div>}
    {selected && <Detail doc={selected} mayManage={mayManage} onClose={() => setSelectedId(null)} onAction={action} />}
    {showUpload && <Upload onClose={() => setShowUpload(false)} onDone={() => { setShowUpload(false); load(); }} />}
  </div>;
}

function Stat({ label, value }) { return <div className="card"><small>{label}</small><strong>{value}</strong></div>; }

function Detail({ doc, mayManage, onClose, onAction }) {
  return <div className="drawer-backdrop" onClick={onClose}>
    <aside className="drawer" onClick={(e) => e.stopPropagation()}>
      <button className="drawer-close" onClick={onClose} aria-label="Close document details">×</button>
      <div className="eyebrow">DOCUMENT / v{doc.version}</div>
      <h2>{doc.title}</h2>
      <p>{doc.description || 'No description provided.'}</p>
      <div className="drawer-grid">
        <div><small>Status</small><strong>{doc.lifecycle_status}</strong></div>
        <div><small>Source</small><strong>{doc.source_type_label}</strong></div>
        <div><small>Chunks</small><strong>{doc.chunk_count}</strong></div>
        <div><small>Last indexed</small><strong>{doc.last_indexed_at ? new Date(doc.last_indexed_at).toLocaleString() : '—'}</strong></div>
      </div>
      <h3>Access roles</h3>
      <div className="knowledge-access">{(doc.allowed_roles || []).map((r) => <span key={r}>{ROLE_LABELS[r] || r}</span>)}</div>
      <h3>Processing</h3>
      <p className="muted">{doc.processing_error || 'No processing errors reported.'}</p>
      {doc.needs_reindex && <p className="muted">Stored embeddings were produced by a different embedding model, so semantic search is skipping this document until it is reindexed.</p>}
      <div className="modal-actions">
        <button className="btn btn-secondary" onClick={onClose}>Close</button>
        {mayManage && (doc.lifecycle_status === 'active' || doc.needs_reindex) && <button className="btn btn-secondary" onClick={() => onAction(doc.id, 'reindex')}>Reindex</button>}
        {mayManage && doc.lifecycle_status === 'active' && <button className="btn btn-danger" onClick={() => onAction(doc.id, 'archive')}>Archive</button>}
        {mayManage && doc.lifecycle_status === 'archived' && <button className="btn btn-secondary" onClick={() => onAction(doc.id, 'restore')}>Restore</button>}
      </div>
    </aside>
  </div>;
}

function Upload({ onClose, onDone }) {
  const [file, setFile] = useState(null);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [sourceType, setSourceType] = useState('policy');
  const [roles, setRoles] = useState([...COMPANY_ROLES]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(e) {
    e.preventDefault();
    if (!file) return;
    // An empty selection would be read as "everyone" by the backend, which is the
    // opposite of restricting a document. Refuse it here rather than relying on 400.
    if (!roles.length) { setError('Select at least one role that may use this document.'); return; }
    setBusy(true);
    setError('');
    try {
      const fd = new FormData();
      fd.append('file', file);
      if (title) fd.append('title', title);
      // Omitting these defaulted every page-uploaded document to "Other" with no
      // description, even for an employee handbook.
      fd.append('source_type', sourceType);
      if (description.trim()) fd.append('description', description.trim());
      fd.append('allowed_roles', roles.join(','));
      await api.upload('/ai/knowledge/upload/', fd);
      onDone();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return <div className="modal-backdrop">
    <form className="modal-card" onSubmit={submit}>
      <div className="panel-head">
        <div><div className="eyebrow">KNOWLEDGE</div><h2>Add document</h2></div>
        <button type="button" onClick={onClose} aria-label="Close upload">×</button>
      </div>
      {error && <div className="alert alert-error" role="alert">{error}</div>}
      <label>PDF or DOCX<input type="file" accept=".pdf,.docx" onChange={(e) => setFile(e.target.files?.[0])} required /></label>
      <label>Title<input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Employee handbook" /></label>
      <label>Type
        <select value={sourceType} onChange={(e) => setSourceType(e.target.value)}>
          {SOURCE_TYPES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
      </label>
      <label>Description<input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What this document covers" /></label>
      <label>AI access roles
        <div className="knowledge-role-selector">
          {COMPANY_ROLES.map((r) => <label key={r}><input type="checkbox" checked={roles.includes(r)} onChange={(e) => setRoles((x) => (e.target.checked ? [...x, r] : x.filter((v) => v !== r)))} />{ROLE_LABELS[r] || r}</label>)}
        </div>
      </label>
      <div className="modal-actions">
        <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={busy || !file || !roles.length}>{busy ? 'Processing…' : 'Upload & index'}</button>
      </div>
    </form>
  </div>;
}
