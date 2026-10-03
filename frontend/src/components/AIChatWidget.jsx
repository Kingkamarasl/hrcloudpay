import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { COMPANY_ROLES, ROLE_LABELS, canManageDrafts, canManageKnowledge } from '../constants/roles';
import Icon from './Icon';

const suggestions = [
  'How many employees do we have?',
  'Who is currently on leave?',
  'Which contracts expire soon?',
  'Give me a payroll overview.',
];

const emptyKnowledgeForm = { title: '', source_type: 'policy', content: '', allowed_roles: [...COMPANY_ROLES] };

/**
 * Whether an assistant message was backed by a verified database read.
 *
 * This must look at the tool list, not at the metadata object itself: the metadata
 * is also populated for a pure knowledge-base answer, and testing it for truthiness
 * showed a green "Verified HRCloudPay data" tick on answers stitched from uploaded
 * documents with no verified read behind them. Reading `metadata` (rather than the
 * live-response-only `tool` field) also means a message renders the same whether it
 * just arrived or was reloaded from history.
 */
const verifiedToolCount = (message) => message?.metadata?.tools?.length ?? message?.tool?.tools?.length ?? 0;

export default function AIChatWidget() {
  const { user } = useAuth();
  const role = user?.role;
  const mayManageKnowledge = canManageKnowledge(role);
  const mayManageDrafts = canManageDrafts(role);

  const [open, setOpen] = useState(false);
  const [conversationId, setConversationId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [draftOpen, setDraftOpen] = useState(false);
  const [draftType, setDraftType] = useState('employment_letter');
  const [draftContext, setDraftContext] = useState('');
  const [draft, setDraft] = useState(null);
  const [draftLoading, setDraftLoading] = useState(false);
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);
  const [knowledge, setKnowledge] = useState([]);
  const [knowledgeForm, setKnowledgeForm] = useState(emptyKnowledgeForm);
  const [knowledgeFile, setKnowledgeFile] = useState(null);
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    const timer = setTimeout(() => inputRef.current?.focus(), 80);
    return () => clearTimeout(timer);
  }, [open, messages, loading]);

  // Tracks the request the user is currently waiting on, so a "new conversation"
  // during an in-flight send discards the reply instead of writing the abandoned
  // conversation's id back into the fresh thread.
  const pendingRef = useRef(0);

  function newConversation() {
    pendingRef.current += 1;
    setConversationId(null);
    setMessages([]);
    setInput('');
    setError('');
    setTimeout(() => inputRef.current?.focus(), 80);
  }

  function closeWidget() {
    // Drafts and pasted knowledge stay in component state, and this component is
    // mounted on every route, so a generated warning letter would remain rendered
    // for the rest of the session. Clear the sensitive state on close.
    pendingRef.current += 1;
    setOpen(false);
    setDraft(null);
    setDraftContext('');
    setDraftOpen(false);
    setKnowledgeOpen(false);
    setKnowledgeForm(emptyKnowledgeForm);
    setKnowledgeFile(null);
    setError('');
  }

  async function sendMessage(text = input) {
    const prompt = String(text || '').trim();
    if (!prompt || loading) return;
    setInput('');
    setError('');
    setMessages((prev) => [...prev, { id: `local-${Date.now()}`, role: 'user', content: prompt }]);
    setLoading(true);
    const ticket = pendingRef.current;
    try {
      const data = await api.post('/ai/conversations/', {
        conversation_id: conversationId,
        message: prompt,
      });
      if (ticket !== pendingRef.current) return;
      setConversationId(data.conversation_id);
      setMessages((prev) => [...prev, data.message]);
    } catch (err) {
      if (ticket !== pendingRef.current) return;
      setError(err.message || 'HRCloudPay AI could not respond.');
    } finally {
      if (ticket === pendingRef.current) setLoading(false);
    }
  }

  async function createDraft() {
    if (!draftContext.trim() || draftLoading) return;
    setDraftLoading(true);
    setError('');
    try {
      const data = await api.post('/ai/drafts/', { type: draftType, context: draftContext.trim() });
      setDraft(data);
      setDraftContext('');
    } catch (err) {
      setError(err.message || 'Could not create the AI draft.');
    } finally {
      setDraftLoading(false);
    }
  }

  async function reviewDraft(status) {
    if (!draft || draftLoading) return;
    setDraftLoading(true);
    setError('');
    try {
      const data = await api.patch(`/ai/drafts/${draft.id}/`, { status });
      setDraft(data);
    } catch (err) {
      setError(err.message || 'Could not update the draft.');
    } finally {
      setDraftLoading(false);
    }
  }


  async function loadKnowledge() {
    try { setKnowledge(await api.get('/ai/knowledge/')); } catch (err) { setError(err.message || 'Could not load AI knowledge.'); }
  }

  async function uploadKnowledgeFile() {
    if (!knowledgeFile || knowledgeLoading) return;
    // An empty role selection must never be sent: the backend cannot tell "nobody"
    // from "not specified" on a multipart body, and would widen it to the whole
    // company. Refuse locally instead of relying on a 400.
    if (!knowledgeForm.allowed_roles.length) {
      setError('Select at least one role that may use this knowledge.');
      return;
    }
    setKnowledgeLoading(true); setError('');
    try {
      const form = new FormData();
      form.append('file', knowledgeFile);
      form.append('title', knowledgeForm.title.trim() || knowledgeFile.name.replace(/\.[^.]+$/, ''));
      form.append('source_type', knowledgeForm.source_type);
      // Joined, not appended per role: repeating the key makes DRF's QueryDict
      // return only the last value, which silently stored every upload as
      // "employee only".
      form.append('allowed_roles', knowledgeForm.allowed_roles.join(','));
      const data = await api.upload('/ai/knowledge/upload/', form);
      setKnowledgeFile(null);
      setKnowledgeForm(emptyKnowledgeForm);
      await loadKnowledge();
      return data;
    } catch (err) { setError(err.message || 'Could not extract and index the document.'); }
    finally { setKnowledgeLoading(false); }
  }

  async function addKnowledge() {
    if (!knowledgeForm.title.trim() || !knowledgeForm.content.trim() || knowledgeLoading) return;
    if (!knowledgeForm.allowed_roles.length) {
      setError('Select at least one role that may use this knowledge.');
      return;
    }
    setKnowledgeLoading(true); setError('');
    try {
      await api.post('/ai/knowledge/', knowledgeForm);
      setKnowledgeForm(emptyKnowledgeForm);
      await loadKnowledge();
    } catch (err) { setError(err.message || 'Could not index the document.'); }
    finally { setKnowledgeLoading(false); }
  }

  async function updateKnowledge(id, action) {
    if (knowledgeLoading) return;
    setKnowledgeLoading(true); setError('');
    try { await api.patch(`/ai/knowledge/${id}/`, { action }); await loadKnowledge(); }
    catch (err) { setError(err.message || 'Could not update the document.'); }
    finally { setKnowledgeLoading(false); }
  }

  async function removeKnowledge(id) {
    if (knowledgeLoading) return;
    setKnowledgeLoading(true); setError('');
    try { await api.del(`/ai/knowledge/${id}/`); await loadKnowledge(); }
    catch (err) { setError(err.message || 'Could not remove the document.'); }
    finally { setKnowledgeLoading(false); }
  }

  // Reindexing is its own endpoint. It used to be preceded by an empty PATCH purely
  // to touch the URL, which wrote a no-op row and a bogus "Updated AI knowledge
  // document" audit entry on every click.
  async function reindexKnowledge(item) {
    if (knowledgeLoading) return;
    setKnowledgeLoading(true); setError('');
    try { await api.post('/ai/knowledge/reindex/', { document_id: item.id }); await loadKnowledge(); }
    catch (err) { setError(err.message || 'Could not reindex the document.'); }
    finally { setKnowledgeLoading(false); }
  }

  function onSubmit(e) {
    e.preventDefault();
    sendMessage();
  }

  function toggleRole(role) {
    setKnowledgeForm((f) => ({
      ...f,
      allowed_roles: f.allowed_roles.includes(role)
        ? f.allowed_roles.filter((r) => r !== role)
        : [...f.allowed_roles, role],
    }));
  }

  return (
    <div className={`ai-widget ${open ? 'is-open' : ''}`}>
      {open && (
        <section className="ai-widget-panel" aria-label="HRCloudPay AI Assistant">
          <header className="ai-widget-header">
            <div className="ai-widget-identity">
              <div className="ai-widget-avatar"><Icon name="sparkles" size={17} /></div>
              <div>
                <strong>HRCloudPay AI</strong>
                <span><i /> HRCloudPay AI assistant</span>
              </div>
            </div>
            <div className="ai-widget-actions">
              {mayManageKnowledge && (
                <button type="button" title="Company AI knowledge" aria-label="Company AI knowledge" onClick={() => { setKnowledgeOpen((v) => !v); if (!knowledgeOpen) loadKnowledge(); }}>
                  <Icon name="file" size={17} />
                </button>
              )}
              <button type="button" title="New conversation" aria-label="New conversation" onClick={newConversation} disabled={loading}>
                <Icon name="plus" size={17} />
              </button>
              <button type="button" title="Close" aria-label="Close HRCloudPay AI" onClick={closeWidget}>
                <Icon name="x" size={18} />
              </button>
            </div>
          </header>

          {mayManageDrafts && (
            <div className="ai-widget-toolbar">
              <button type="button" className={draftOpen ? 'active' : ''} onClick={() => setDraftOpen((v) => !v)}>
                <Icon name="file" size={14} /> Draft HR document
              </button>
            </div>
          )}


          {knowledgeOpen && mayManageKnowledge && (
            <div className="ai-widget-knowledge">
              <div className="ai-widget-draft-preview-head"><div><strong>Company AI knowledge</strong><span>Tenant-scoped RAG</span></div><button type="button" onClick={() => setKnowledgeOpen(false)}>Close</button></div>
              <p>Approved HR policies, handbooks and guides are retrieved only for this company. Do not paste secrets or credentials.</p>
              <select value={knowledgeForm.source_type} onChange={(e) => setKnowledgeForm({ ...knowledgeForm, source_type: e.target.value })}>
                <option value="policy">HR policy</option><option value="handbook">Employee handbook</option><option value="contract_template">Contract template</option><option value="guide">HR guide</option><option value="other">Other</option>
              </select>
              <input value={knowledgeForm.title} onChange={(e) => setKnowledgeForm({ ...knowledgeForm, title: e.target.value })} placeholder="Document title (optional for uploads)" />
              <div className="ai-widget-access">
                <span>Who can use this knowledge?</span>
                {COMPANY_ROLES.map((r) => <label key={r}><input type="checkbox" checked={knowledgeForm.allowed_roles.includes(r)} onChange={() => toggleRole(r)} /> {ROLE_LABELS[r] || r}</label>)}
              </div>
              {knowledgeForm.allowed_roles.length === 0 && <small className="ai-widget-access-warning">Select at least one role, otherwise the document cannot be saved.</small>}
              <label className="ai-widget-file-input">
                <span>Upload PDF or DOCX</span>
                <input type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(e) => setKnowledgeFile(e.target.files?.[0] || null)} />
              </label>
              {knowledgeFile && <div className="ai-widget-file-selected">{knowledgeFile.name} · {(knowledgeFile.size / 1024 / 1024).toFixed(2)} MB</div>}
              <button type="button" className="ai-widget-draft-create" onClick={uploadKnowledgeFile} disabled={knowledgeLoading || !knowledgeFile || !knowledgeForm.allowed_roles.length}>Extract & index document</button>
              <div className="ai-widget-divider">or paste text manually</div>
              <textarea value={knowledgeForm.content} onChange={(e) => setKnowledgeForm({ ...knowledgeForm, content: e.target.value })} rows={4} placeholder="Paste approved company policy or HR guidance..." />
              <button type="button" className="ai-widget-draft-create secondary" onClick={addKnowledge} disabled={knowledgeLoading || !knowledgeForm.title.trim() || !knowledgeForm.content.trim() || !knowledgeForm.allowed_roles.length}>Index pasted content</button>
              <div className="ai-widget-knowledge-list">{knowledge.map((item) => <div key={item.id}>
                <div><strong>{item.title}</strong><small>{item.source_type_label} · v{item.version} · {item.chunk_count} chunks · {item.lifecycle_status}</small><small>Access: {(item.allowed_roles || []).map((r) => ROLE_LABELS[r] || r).join(', ')}</small>{item.needs_reindex && <small>Index is stale - reindex to restore semantic search.</small>}</div>
                <div className="ai-widget-knowledge-actions">
                  {item.lifecycle_status === 'archived' ? <button type="button" onClick={() => updateKnowledge(item.id, 'restore')} disabled={knowledgeLoading}>Restore</button> : <button type="button" onClick={() => updateKnowledge(item.id, 'archive')} disabled={knowledgeLoading}>Archive</button>}
                  <button type="button" onClick={() => reindexKnowledge(item)} disabled={knowledgeLoading}>Reindex</button>
                  <button type="button" onClick={() => removeKnowledge(item.id)} disabled={knowledgeLoading}>Delete</button>
                </div>
              </div>)}</div>
            </div>
          )}

          {draftOpen && mayManageDrafts && (
            <div className="ai-widget-draft-panel">
              <div className="ai-widget-draft-title">Create a reviewable draft</div>
              <select value={draftType} onChange={(e) => setDraftType(e.target.value)} disabled={draftLoading}>
                <option value="employment_letter">Employment letter</option>
                <option value="warning_letter">Warning letter</option>
                <option value="payroll_explanation">Payroll explanation</option>
                <option value="hr_report">HR report</option>
              </select>
              <textarea value={draftContext} onChange={(e) => setDraftContext(e.target.value)} rows={4} placeholder="Provide verified facts for the draft. Do not include information you do not want sent to the AI provider." disabled={draftLoading} />
              <button type="button" className="ai-widget-draft-create" onClick={createDraft} disabled={draftLoading || !draftContext.trim()}>
                {draftLoading ? 'Generating…' : 'Generate draft'}
              </button>
            </div>
          )}

          {draft && (
            <div className="ai-widget-draft-preview">
              <div className="ai-widget-draft-preview-head">
                <div><strong>{draft.type_label || 'AI draft'}</strong><span>{draft.status_label || 'Pending review'}</span></div>
                <button type="button" onClick={() => setDraft(null)}>Close</button>
              </div>
              <pre>{draft.content}</pre>
              {mayManageDrafts && (
                <div className="ai-widget-draft-review">
                  <button type="button" onClick={() => reviewDraft('rejected')} disabled={draftLoading || draft.status === 'rejected'}>Reject</button>
                  <button type="button" onClick={() => reviewDraft('approved')} disabled={draftLoading || draft.status === 'approved'}>Mark reviewed</button>
                </div>
              )}
              <small>Review status does not send or apply this document to an employee record.</small>
            </div>
          )}

          <div className="ai-widget-messages">
            {!messages.length && (
              <div className="ai-widget-welcome">
                <div className="ai-widget-welcome-mark"><Icon name="sparkles" size={20} /></div>
                <h3>How can I help?</h3>
                <p>Ask about your workforce, payroll, leave, attendance or HR operations.</p>
                <div className="ai-widget-suggestions">
                  {suggestions.map((item) => (
                    <button key={item} type="button" onClick={() => sendMessage(item)}>{item}</button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((message) => (
              <div key={message.id} className={`ai-widget-message ${message.role}`}>
                <div className="ai-widget-bubble">
                  <div className="ai-widget-content">{message.content}</div>
                  {verifiedToolCount(message) > 0 && <div className="ai-widget-verified"><Icon name="check" size={12} /> Verified HRCloudPay data</div>}
                  {message.metadata?.knowledge?.length > 0 && (
                    <div className="ai-widget-sources">
                      <div className="ai-widget-sources-title">Sources</div>
                      {message.metadata.knowledge.map((source) => (
                        <div className="ai-widget-source" key={`${message.id}-${source.document_id}-${source.citation}`}>
                          <span className="ai-widget-source-badge">{source.citation}</span>
                          <div><strong>{source.title}</strong><small>{source.source_type}{source.page_number ? ` · Page ${source.page_number}` : ''}{source.section_label ? ` · ${source.section_label}` : ''}{source.snippet ? ` · ${source.snippet}` : ''}</small></div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}

            {loading && (
              <div className="ai-widget-message assistant">
                <div className="ai-widget-bubble ai-widget-thinking"><span /><span /><span /></div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {error && <div className="ai-widget-error" role="alert">{error}</div>}

          <form className="ai-widget-composer" onSubmit={onSubmit}>
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask HRCloudPay AI..."
              rows={1}
              disabled={loading}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  onSubmit(e);
                }
              }}
            />
            <button type="submit" aria-label="Send message" disabled={loading || !input.trim()}>
              <Icon name="arrow" size={18} />
            </button>
          </form>
          <div className="ai-widget-footer">AI can make mistakes. Verify payroll, compliance and employee decisions.</div>
        </section>
      )}

      <button
        type="button"
        className="ai-widget-trigger"
        onClick={() => (open ? closeWidget() : setOpen(true))}
        aria-label={open ? 'Close HRCloudPay AI' : 'Open HRCloudPay AI'}
        title={open ? 'Close HRCloudPay AI' : 'Ask HRCloudPay AI'}
      >
        <span className="ai-widget-trigger-icon"><Icon name={open ? 'x' : 'sparkles'} size={22} /></span>
        {!open && <span className="ai-widget-trigger-label">AI Assistant</span>}
      </button>
    </div>
  );
}
