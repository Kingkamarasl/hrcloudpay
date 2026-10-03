import { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { canManageDrafts } from '../constants/roles';
import Icon from '../components/Icon';

const suggestions = [
  'Give me a quick overview of my HRCloudPay workspace.',
  'What can I use HRCloudPay AI for?',
  'Explain how payroll and HR data should be handled securely.',
  'How many employees do we have?',
];

/** See AIChatWidget: a "verified" tick must require an actual tool read. */
const verifiedToolCount = (message) => message?.metadata?.tools?.length ?? message?.tool?.tools?.length ?? 0;

export default function AIAssistant() {
  const { user } = useAuth();
  const [conversations, setConversations] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [historyError, setHistoryError] = useState('');
  const [error, setError] = useState('');
  const bottomRef = useRef(null);
  // Lets a "new conversation" during an in-flight send discard the reply rather
  // than writing the abandoned conversation's id back into the fresh thread.
  const pendingRef = useRef(0);

  useEffect(() => {
    api.get('/ai/conversations/')
      .then((rows) => { setConversations(rows || []); setHistoryError(''); })
      // Previously swallowed, so a 401/500 rendered "Your conversations will appear
      // here" - telling the user they had no history when the list had simply failed.
      .catch((e) => setHistoryError(e.message || 'Could not load your conversation history.'))
      .finally(() => setLoadingHistory(false));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  async function openConversation(id) {
    setError('');
    pendingRef.current += 1;
    setLoading(false);
    try {
      const data = await api.get(`/ai/conversations/${id}/`);
      setConversationId(data.id);
      setMessages(data.messages || []);
      // Leaving the composer populated sent a half-typed message to whichever
      // conversation the user switched into.
      setInput('');
    } catch (err) {
      setError(err.message || 'Unable to open conversation.');
    }
  }

  function newConversation() {
    pendingRef.current += 1;
    setConversationId(null);
    setMessages([]);
    setInput('');
    setError('');
    setLoading(false);
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
      // Update the one affected row in place. This used to refetch the entire
      // conversation list after every send, which the sidebar only needs id/title/
      // updated_at from and which grew without bound as history accumulated.
      setConversations((prev) => {
        const next = prev.filter((c) => c.id !== data.conversation_id);
        return [{ id: data.conversation_id, title: data.title || 'New conversation', updated_at: data.updated_at || new Date().toISOString() }, ...next].slice(0, 30);
      });
    } catch (err) {
      if (ticket !== pendingRef.current) return;
      setError(err.message || 'HRCloudPay AI could not respond.');
    } finally {
      if (ticket === pendingRef.current) setLoading(false);
    }
  }

  function onSubmit(e) {
    e.preventDefault();
    sendMessage();
  }

  return (
    <div className="ai-page">
      <div className="page-header ai-page-header">
        <div>
          <div className="eyebrow">HRCloudPay AI</div>
          <h1>AI Assistant</h1>
          <p className="page-subtitle">Your assistant for HR, payroll and workforce operations.</p>
        </div>
        <button className="btn btn-primary compact" onClick={newConversation} disabled={loading}>+ New conversation</button>
      </div>

      <div className="ai-layout">
        <aside className="ai-history panel">
          <div className="panel-head">
            <div><div className="eyebrow">HISTORY</div><h2>Conversations</h2></div>
          </div>
          {loadingHistory
            ? <div className="page-loading">Loading…</div>
            : historyError
              ? <div className="alert alert-error" role="alert">{historyError}</div>
              : conversations.length
                ? conversations.map((item) => (
                  <button key={item.id} className={`ai-history-item ${conversationId === item.id ? 'active' : ''}`} onClick={() => openConversation(item.id)}>
                    <strong>{item.title}</strong>
                    <small>{new Date(item.updated_at).toLocaleDateString()}</small>
                  </button>
                ))
                : <div className="ai-empty-history">Your conversations will appear here.</div>}
        </aside>

        <section className="ai-chat panel">
          <div className="ai-chat-top">
            <div className="ai-model-badge"><span className="ai-status-dot" /> HRCloudPay AI</div>
            <span className="ai-private-note">Company-scoped assistant</span>
          </div>

          <div className="ai-messages">
            {!messages.length && (
              <div className="ai-welcome">
                <div className="ai-welcome-mark">AI</div>
                <h2>How can I help with HRCloudPay?</h2>
                <p>Ask questions, explain HR processes, or find company policy. Your account permissions still control access to company data.</p>
                <div className="ai-suggestions">
                  {suggestions.map((item) => <button key={item} onClick={() => sendMessage(item)}>{item}</button>)}
                </div>
              </div>
            )}
            {messages.map((message) => (
              <div key={message.id} className={`ai-message ${message.role}`}>
                <div className="ai-message-label">{message.role === 'user' ? 'You' : 'HRCloudPay AI'}</div>
                <div className="ai-message-bubble">
                  {message.content}
                  {verifiedToolCount(message) > 0 && <div className="ai-message-verified"><Icon name="check" size={12} /> Verified HRCloudPay data</div>}
                  {/* This page used to discard every citation the API returned. */}
                  {message.metadata?.knowledge?.length > 0 && (
                    <div className="ai-message-sources">
                      {message.metadata.knowledge.map((source) => (
                        <div key={`${message.id}-${source.document_id}-${source.citation}`}>
                          <span className="ai-source-badge">{source.citation}</span>
                          <span>{source.title}{source.page_number ? ` · Page ${source.page_number}` : ''}{source.section_label ? ` · ${source.section_label}` : ''}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {loading && <div className="ai-message assistant"><div className="ai-message-label">HRCloudPay AI</div><div className="ai-message-bubble ai-thinking">Thinking…</div></div>}
            <div ref={bottomRef} />
          </div>

          {error && <div className="alert alert-error ai-error" role="alert">{error}</div>}
          <form className="ai-composer" onSubmit={onSubmit}>
            <textarea value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask HRCloudPay AI…" rows={2} disabled={loading} />
            <button className="btn btn-primary" disabled={loading || !input.trim()}>{loading ? 'Working…' : 'Send'}</button>
          </form>
          {!canManageDrafts(user?.role) && <div className="ai-disclaimer">HR document drafting is available to HR, finance and company administrators.</div>}
          <div className="ai-disclaimer">AI responses can be incorrect. Verify payroll, compliance, legal and employee decisions against HRCloudPay records and applicable rules.</div>
        </section>
      </div>
    </div>
  );
}
