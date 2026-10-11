import {useEffect,useState} from 'react';
import {api} from '../api/client';
import Icon from '../components/Icon';

// Approving here does not send anything. `AIDraftDetailView.patch` records the
// reviewer's decision and writes an audit row; it never emails a letter, posts
// a notice or touches an HR record. The copy on this page says so explicitly
// because a button reading "Approve & send" on a warning-letter draft would be
// a promise the API does not keep, and the person who believed it would send
// the letter from their own inbox.
const STATUS_ICON={pending:'clock',approved:'check',rejected:'x'};

function when(iso){return iso?new Date(iso).toLocaleString():'—'}

export default function AIDrafts(){
 const [drafts,setDrafts]=useState([]),[loading,setLoading]=useState(true),[error,setError]=useState(''),[open,setOpen]=useState(null),[busy,setBusy]=useState(false);
 async function load(){
  setLoading(true);
  try{
   const d=await api.get('/ai/drafts/list/');
   setDrafts(d.results??d);setError('');
  }catch(e){setError(e.message||'Could not load drafts.')}
  finally{setLoading(false)}
 }
 useEffect(()=>{load()},[]);
 // The list refreshes after a review so the badge and the counts agree with what
 // the server stored. A rejected draft stays in the list with its reviewer and
 // timestamp rather than disappearing - who turned it down, and when, is the
 // part worth keeping.
 async function review(id,status){
  setBusy(true);
  try{
   const updated=await api.patch(`/ai/drafts/${id}/`,{status});
   setOpen({...open,...updated});
   setDrafts(ds=>ds.map(d=>d.id===id?{...d,...updated}:d));
   setError('');
  }catch(e){setError(e.message||`Could not mark this draft ${status}.`)}
  finally{setBusy(false)}
 }
 if(loading)return <div className="page-loading">Loading AI drafts…</div>;
 const count=s=>drafts.filter(d=>d.status===s).length;
 return <div>
 <section className="page-header"><div><div className="eyebrow">AI COPILOT</div><h1>Drafts for review</h1><p>The AI prepares letters and reports. A person with authority over them decides whether they are used.</p></div><button className="btn btn-secondary" onClick={()=>open?setOpen(null):load()}><Icon name="refresh" size={15}/>{open?'Back to list':'Refresh'}</button></section>
 {error&&<div className="alert alert-error">{error}</div>}
 {open
  ?<div className="panel">
   <div className="panel-head"><div><h2>{open.title||'Untitled draft'}</h2><p>{open.type_label} · prepared by {open.created_by_name||'the assistant'} on {when(open.created_at)}</p></div><span className={`badge badge-${open.status}`}>{open.status_label||open.status}</span></div>
   {open.context&&<div className="alert"><strong>Basis for this draft</strong><p style={{margin:'4px 0 0'}}>{open.context}</p></div>}
   <div className="panel" style={{marginTop:12}}><pre style={{whiteSpace:'pre-wrap',fontFamily:'inherit',fontSize:'0.95rem',lineHeight:1.6,margin:0}}>{open.content}</pre></div>
   {open.status!=='pending'&&<div className="alert"><strong>{open.status_label||open.status}</strong> by {open.reviewed_by_name||'a reviewer'} on {when(open.reviewed_at)}.</div>}
   <div style={{display:'flex',gap:8,marginTop:16,flexWrap:'wrap'}}>
    {open.status!=='approved'&&<button className="btn btn-primary" disabled={busy} onClick={()=>review(open.id,'approved')}><Icon name="check" size={15}/>{busy?'Saving…':'Approve for use'}</button>}
    {open.status!=='rejected'&&<button className="btn btn-secondary" disabled={busy} onClick={()=>review(open.id,'rejected')}><Icon name="x" size={15}/>Reject</button>}
   </div>
   <p className="hint" style={{marginTop:12}}>Approving records your decision and who made it. It does not send the letter — read it, then issue it yourself.</p>
  </div>
  :<>
   <div className="dash-stats">
    <div className="dash-stat"><div className="stat-icon"><Icon name="clock"/></div><div className="stat-copy"><span>Awaiting review</span><strong>{count('pending')}</strong><small>Need a decision</small></div></div>
    <div className="dash-stat"><div className="stat-icon"><Icon name="check"/></div><div className="stat-copy"><span>Approved</span><strong>{count('approved')}</strong><small>Cleared for use</small></div></div>
    <div className="dash-stat"><div className="stat-icon"><Icon name="x"/></div><div className="stat-copy"><span>Rejected</span><strong>{count('rejected')}</strong><small>Declined</small></div></div>
   </div>
   <div className="panel"><div className="panel-head"><div><h2>All drafts</h2><p>Anything the assistant prepared for a decision.</p></div></div>
   <div className="activity-list">
    {drafts.map(d=><div className={`activity-row ${d.status==='pending'?'':'unread-row'}`} key={d.id}>
     <div className={`activity-icon ${d.status==='rejected'?'danger':''}`}><Icon name={STATUS_ICON[d.status]||'file'} size={16}/></div>
     <div><strong>{d.title||d.type_label}</strong><small>{d.type_label} · {d.created_by_name} · {when(d.created_at)}{d.reviewed_at?` · ${d.status_label} by ${d.reviewed_by_name}`:''}</small></div>
     <div style={{display:'flex',alignItems:'center',gap:8}}><span className={`badge badge-${d.status}`}>{d.status_label}</span><button className="btn btn-secondary compact" onClick={()=>setOpen(d)}>Open</button></div>
    </div>)}
    {!drafts.length&&<div className="empty-state"><strong>No drafts yet</strong><p>Open the AI Copilot and ask for a letter, a payroll explanation or an HR report. Anything prepared for a decision appears here for someone to approve or reject.</p></div>}
   </div></div>
  </>}
 </div>
}