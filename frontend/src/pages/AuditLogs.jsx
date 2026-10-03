import { useEffect, useState } from 'react';
import { api } from '../api/client';

const ACTIONS = [
  ['', 'All events'], ['login','Login'], ['login_failed','Failed login'], ['logout','Logout'],
  ['salary_change','Salary change'], ['termination','Termination'], ['contract_change','Contract change'],
  ['permission_change','Permission change'], ['payroll_process','Payroll processed'], ['payroll_approve','Payroll approved'],
  ['payroll_payment','Payroll payment'], ['data_export','Data export'], ['account_status','Account status'], ['create','Created'], ['update','Updated'], ['delete','Deleted']
];

export default function AuditLogs() {
  const [items,setItems]=useState([]); const [action,setAction]=useState(''); const [target,setTarget]=useState(''); const [actor,setActor]=useState(''); const [loading,setLoading]=useState(true); const [error,setError]=useState('');
  // This trail is a compliance record. Swallowing the failure and leaving
  // `items` empty rendered "No audit events match these filters", which reads
  // as an absence of activity rather than an error - on the one page where
  // that distinction matters most.
  const load=async()=>{setLoading(true); setError(''); try { const q=new URLSearchParams(); if(action)q.set('action',action); if(target)q.set('target_type',target); if(actor)q.set('actor',actor); setItems(await api.get(`/auth/audit-logs/?${q.toString()}`)); } catch(e) { setItems([]); setError(e.message||'Could not load the audit trail.'); } finally {setLoading(false);} };
  useEffect(()=>{load()},[action,target]);
  const sensitive=items.filter(x=>['salary_change','termination','contract_change','permission_change','payroll_approve','payroll_payment','login_failed'].includes(x.action)).length;
  return <div className="page-shell audit-page">
    <div className="page-header"><div><span className="eyebrow">Security & compliance</span><h1>Audit trail</h1><p>A chronological record of sensitive activity in your company.</p></div><button className="btn btn-secondary" onClick={load}>Refresh</button></div>
    {!error&&<div className="admin-stats audit-stats"><div className="admin-stat"><div><strong>{items.length}</strong><span>Events shown</span></div></div><div className="admin-stat"><div><strong>{sensitive}</strong><span>Sensitive events</span></div></div><div className="admin-stat"><div><strong>SHA-256</strong><span>Tamper-evident chain</span></div></div></div>}
    <div className="card audit-filter-card"><div className="audit-filters"><label>Action<select value={action} onChange={e=>setAction(e.target.value)}>{ACTIONS.map(([v,l])=><option value={v} key={v}>{l}</option>)}</select></label><label>Target type<input value={target} onChange={e=>setTarget(e.target.value)} placeholder="employee, payroll_run…"/></label><label>Actor<input value={actor} onChange={e=>setActor(e.target.value)} placeholder="Search user…" onKeyDown={e=>e.key==='Enter'&&load()}/></label></div></div>
    <div className="card"><div className="section-head"><div><h2>Activity history</h2><p>Only authorized company administrators can view this trail.</p></div></div>{loading?<div className="page-loading">Loading audit events…</div>:error?<div className="alert alert-error">{error}</div>:<div className="audit-timeline">{items.map(x=><div className="audit-event" key={x.id}><div className={`audit-dot audit-${x.action}`}></div><div className="audit-event-main"><div className="audit-event-top"><span className="audit-action">{x.action.replaceAll('_',' ')}</span><time>{new Date(x.created_at).toLocaleString()}</time></div><strong>{x.message}</strong><div className="audit-meta">{x.actor} · {x.target_type || 'system'}{x.target_id?` #${x.target_id}`:''}{x.request_id?` · Request ${x.request_id.slice(0,8)}`:''}</div>{x.metadata?.changes&&<details><summary>View changes</summary><pre>{JSON.stringify(x.metadata.changes,null,2)}</pre></details>}<div className="audit-integrity">Sequence {x.chain_sequence ?? '—'} · {x.integrity_hash ? `${x.integrity_hash.slice(0,16)}…` : 'legacy event'}</div></div></div>)}{!items.length&&<div className="empty-row">No audit events match these filters.</div>}</div>}</div>
  </div>;
}
