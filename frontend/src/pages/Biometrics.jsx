import {useEffect,useState} from 'react';
import {api} from '../api/client';
import Icon from '../components/Icon';

// Biometric terminals have no user account and no browser. They authenticate
// with an API key and POST punches; HRCloudPay turns those into attendance
// records. Templates never leave the device, so the most sensitive data is not
// in this database or in any backup of it.
const TABS=[['devices','Devices'],['enrollments','Enrollments'],['punches','Punch log']];

// A terminal that stops reporting leaves no trace: attendance for everyone who
// clocks on it just stops existing, which looks like a quiet day until payroll.
// The API answers whether each device is still reporting (see
// backend/biometrics/services.device_health) and this page leads with it.
const HEALTH_LABELS={ok:'Reporting',silent:'Silent',never_seen:'Never reported',not_monitored:'Not monitored'};
const HEALTH_BADGES={ok:'paid',silent:'rejected',never_seen:'pending',not_monitored:'pending'};
const NEEDS_ATTENTION=['silent','never_seen'];
// Which rule the server used to decide a punch belongs to that person, and how
// each terminal's matching policy reads. Both are shown because the two answer
// the same question at different times: "why is this hours on Ada's record?"
const MATCHED_BY_LABELS={enrolment:'enrolment template',employee_code:'employee code',pk:'HRCloudPay ID',manual:'set by a person'};
const POLICY_LABELS={enrolment:'Enrolment only',code:'Enrolment + code',pk:'+ HRCloudPay ID'};
function healthOf(d){return (d.health&&d.health.status)||'ok'}
function sinceLabel(iso){
 const minutes=Math.floor((Date.now()-new Date(iso).getTime())/60000);
 if(minutes<1)return 'just now';
 if(minutes<60)return `${minutes}m ago`;
 const hours=Math.floor(minutes/60);
 return hours<24?`${hours}h ago`:`${Math.floor(hours/24)}d ${hours%24}h ago`;
}

export default function Biometrics(){
 const [tab,setTab]=useState('devices');
 const [devices,setDevices]=useState([]),[enrollments,setEnrollments]=useState([]),[punches,setPunches]=useState([]);
 const [employees,setEmployees]=useState([]);
 const [loading,setLoading]=useState(true),[error,setError]=useState('');
 const [newKey,setNewKey]=useState(null),[form,setForm]=useState({name:'',device_id:'',device_type:'fingerprint',location:'',match_policy:'code'});
 const [enrollForm,setEnrollForm]=useState({employee:'',device:'',method:'fingerprint',template_id:''});
 const [punchStatus,setPunchStatus]=useState('');
 const [reconcile,setReconcile]=useState(null),[reconcileError,setReconcileError]=useState('');
 async function load(status=punchStatus){
  setLoading(true);
  try{
   const [d,e,p,em]=await Promise.all([
     api.get('/biometrics/devices/'),
     api.get('/biometrics/enrollments/'),
     api.get(`/biometrics/punches/?limit=100${status?`&status=${status}`:''}`),
     api.get('/employees/employees/?limit=500'),
   ]);
   setDevices(d.results??d);setEnrollments(e.results??e);setPunches(p.results??p);
   const empData=em.results??em;
   setEmployees(Array.isArray(empData)?empData:(empData.results??[]));
   setError('');
  }catch(e){setError(e.message||'Could not load biometric data.')}
  finally{setLoading(false)}
 }
 useEffect(()=>{load(punchStatus)},[punchStatus]);
 async function register(e){
  e.preventDefault();
  try{
   const created=await api.post('/biometrics/devices/',form);
   setNewKey(created.api_key);setForm({name:'',device_id:'',device_type:'fingerprint',location:'',match_policy:'code'});await load();
  }catch(e){setError(e.message||'Could not register device.')}
 }
 async function enroll(e){
  e.preventDefault();
  try{
   await api.post('/biometrics/enrollments/',{
     employee:Number(enrollForm.employee),device:Number(enrollForm.device),
     method:enrollForm.method,template_id:enrollForm.template_id,
   });
   setEnrollForm({employee:'',device:'',method:'fingerprint',template_id:''});await load();
  }catch(e){setError(e.message||'Could not enrol employee.')}
 }
 async function revoke(id){
  try{await api.delete(`/biometrics/enrollments/${id}/`);await load();}
  catch(e){setError(e.message||'Could not revoke enrolment.')}
 }
 async function retire(id){
  try{await api.patch(`/biometrics/devices/${id}/`,{status:'retired'});await load();}
  catch(e){setError(e.message||'Could not retire device.')}
 }
 // A punch the log kept instead of guessing at: attach it to the employee it
 // belongs to and let the server process it again.
 function openReconcile(p){setReconcileError('');setReconcile({punch:p,employee:p.employee?String(p.employee):''})}
 async function submitReconcile(e){
  e.preventDefault();
  try{
   await api.post(`/biometrics/punches/${reconcile.punch.id}/reconcile/`,reconcile.employee?{employee:Number(reconcile.employee)}:{});
   setReconcile(null);setReconcileError('');await load();
  }catch(err){setReconcileError(err.message||'Could not reconcile punch.')}
 }  if(loading)return <div className="page-loading">Loading biometric data…</div>;
  const notReporting=devices.filter(d=>NEEDS_ATTENTION.includes(healthOf(d)));
 return <div className="page-shell">
 <section className="page-header"><div><div className="eyebrow">ATTENDANCE</div><h1>Biometric terminals</h1><p>Register fingerprint, face, iris or card terminals, enrol employees on them, and review the punches they report. Terminals POST to /api/biometrics/punch/, one punch or a queued batch at a time. Templates stay on the device.</p></div><button className="btn btn-secondary" onClick={()=>load()}><Icon name="refresh" size={15}/>Refresh</button></section>
 {error&&<div className="alert alert-error">{error}</div>}
 {notReporting.length>0&&<div className="alert alert-warning"><strong>{notReporting.length===1?'1 terminal is not reporting.':`${notReporting.length} terminals are not reporting.`}</strong> {notReporting.map(d=>`${d.name}: ${d.health.detail}`).join(' ')} Nobody who clocks on a silent terminal is being recorded.</div>}
 {newKey&&<div className="alert alert-warning"><strong>Copy this key now.</strong> It is shown once and never stored in readable form. Paste it into the terminal's configuration and keep it safe: {newKey}<button className="btn btn-secondary compact" style={{marginLeft:12}} onClick={()=>setNewKey(null)}>I have saved it</button></div>}
 <div className="panel"><div className="tabs">{TABS.map(([k,l])=><button key={k} className={`tab ${tab===k?'active':''}`} onClick={()=>setTab(k)}>{l}</button>)}</div>
 {tab==='devices'&&<>
  <form className="form-grid" onSubmit={register} style={{padding:16}}>
   <div className="form-row"><div><label>Name</label><input value={form.name} onChange={e=>setForm({...form,name:e.target.value})} required/></div><div><label>Device ID</label><input value={form.device_id} onChange={e=>setForm({...form,device_id:e.target.value})} required placeholder="Serial number"/></div></div>
   <div className="form-row"><div><label>Type</label><select value={form.device_type} onChange={e=>setForm({...form,device_type:e.target.value})}><option value="fingerprint">Fingerprint</option><option value="face">Face recognition</option><option value="iris">Iris</option><option value="palm">Palm</option><option value="card">Card / RFID</option><option value="other">Other</option></select></div><div><label>Location</label><input value={form.location} onChange={e=>setForm({...form,location:e.target.value})} placeholder="Lobby, gate 2…"/></div></div>
   <div className="form-row"><div><label>Match punches by</label><select value={form.match_policy} onChange={e=>setForm({...form,match_policy:e.target.value})}><option value="code">Enrolment template ID, then employee code</option><option value="enrolment">Enrolment template ID only</option><option value="pk">Enrolment template ID, then employee code, then HRCloudPay ID</option></select><p style={{color:'var(--text-muted)',fontSize:'.78rem',marginTop:6}}>The terminal's own enrolment template is always accepted, and employee codes are unique per company. Choose the last option only if this terminal is fed our employee IDs: otherwise its own local user IDs would be read as ours, and the wrong person's hours would be recorded without an error.</p></div><div></div></div>
   <div className="modal-actions"><button className="btn btn-primary" type="submit"><Icon name="plus" size={15}/>Register terminal</button></div>
  </form>
  <div className="table-wrap"><table className="data-table"><thead><tr><th>Name</th><th>Device ID</th><th>Type</th><th>Location</th><th>Status</th><th>Matches</th><th>Reporting</th><th>Last seen</th><th></th></tr></thead><tbody>
   {devices.map(d=><tr key={d.id}><td><strong>{d.name}</strong></td><td>{d.device_id}</td><td>{d.device_type}</td><td>{d.location||'—'}</td><td><span className={`badge badge-${d.status==='active'?'paid':d.status==='retired'?'rejected':'pending'}`}>{d.status}</span></td><td title="Which identifiers this terminal may match punches by">{POLICY_LABELS[d.match_policy]||d.match_policy}</td><td><span className={`badge badge-${HEALTH_BADGES[healthOf(d)]||'pending'}`} title={d.health?.detail||''}>{HEALTH_LABELS[healthOf(d)]||healthOf(d)}</span></td><td>{d.last_seen_at?`${sinceLabel(d.last_seen_at)} · ${new Date(d.last_seen_at).toLocaleString()}`:'Never'}</td><td>{d.status!=='retired'&&<button className="btn btn-secondary compact" onClick={()=>retire(d.id)}>Retire</button>}</td></tr>)}
   {!devices.length&&<tr><td colSpan="9" className="empty-row">No terminals registered. Register one above and paste its API key into the device.</td></tr>}
  </tbody></table></div>
 </>}
 {tab==='enrollments'&&<>
  <form className="form-grid" onSubmit={enroll} style={{padding:16}}>
   <div className="form-row"><div><label>Employee</label><select value={enrollForm.employee} onChange={e=>setEnrollForm({...enrollForm,employee:e.target.value})} required><option value="">Select employee…</option>{employees.map(e=><option key={e.id} value={e.id}>{e.full_name} ({e.employee_code})</option>)}</select></div><div><label>Terminal</label><select value={enrollForm.device} onChange={e=>setEnrollForm({...enrollForm,device:e.target.value})} required><option value="">Select terminal…</option>{devices.filter(d=>d.status==='active').map(d=><option key={d.id} value={d.id}>{d.name}</option>)}</select></div></div>
   <div className="form-row"><div><label>Method</label><select value={enrollForm.method} onChange={e=>setEnrollForm({...enrollForm,method:e.target.value})}><option value="fingerprint">Fingerprint</option><option value="face">Face</option><option value="iris">Iris</option><option value="palm">Palm</option><option value="card">Card / RFID</option></select></div><div><label>Template ID (optional)</label><input value={enrollForm.template_id} onChange={e=>setEnrollForm({...enrollForm,template_id:e.target.value})} placeholder="Device-side reference"/></div></div>
   <div className="modal-actions"><button className="btn btn-primary" type="submit"><Icon name="plus" size={15}/>Enrol employee</button></div>
  </form>
  <div className="table-wrap"><table className="data-table"><thead><tr><th>Employee</th><th>Terminal</th><th>Method</th><th>Template</th><th>Status</th><th>Enrolled</th><th></th></tr></thead><tbody>
   {enrollments.map(e=><tr key={e.id}><td><strong>{e.employee_name}</strong></td><td>{devices.find(d=>d.id===e.device)?.name||e.device}</td><td>{e.method}</td><td>{e.template_id||'—'}</td><td><span className={`badge badge-${e.status==='active'?'paid':'rejected'}`}>{e.status}</span></td><td>{new Date(e.enrolled_at).toLocaleDateString()}</td><td>{e.status==='active'&&<button className="btn btn-secondary compact" onClick={()=>revoke(e.id)}>Revoke</button>}</td></tr>)}
   {!enrollments.length&&<tr><td colSpan="7" className="empty-row">No enrolments yet. Enrol an employee above so the terminal knows who they are.</td></tr>}
  </tbody></table></div>
 </>}
 {tab==='punches'&&<>
  <div style={{display:'flex',alignItems:'center',gap:10,padding:'14px 16px',flexWrap:'wrap'}}>
   <label htmlFor="punch-status" style={{fontWeight:700,fontSize:'.85rem'}}>Status</label>
   <select id="punch-status" className="inline-select" value={punchStatus} onChange={e=>setPunchStatus(e.target.value)}><option value="">All punches</option><option value="processed">Processed</option><option value="failed">Failed</option><option value="ignored">Ignored</option><option value="pending">Pending</option></select>
   <span style={{color:'var(--text-muted)',fontSize:'.78rem'}}>Failed and ignored punches are the ones waiting for a person to reconcile.</span>
  </div>
  <div className="table-wrap"><table className="data-table"><thead><tr><th>Time</th><th>Employee</th><th>Terminal</th><th>Type</th><th>Status</th><th>Error</th><th></th></tr></thead><tbody>
   {punches.map(p=><tr key={p.id}><td>{new Date(p.punch_time).toLocaleString()}</td><td>{p.employee_name||'Unmatched'}{p.matched_by&&<div style={{color:'var(--text-muted)',fontSize:'.72rem'}}>via {MATCHED_BY_LABELS[p.matched_by]||p.matched_by}</div>}</td><td>{p.device_name}</td><td>{p.punch_type}</td><td><span className={`badge badge-${p.status==='processed'?'paid':p.status==='failed'?'rejected':'pending'}`}>{p.status}</span></td><td>{p.error||'—'}</td><td>{p.status!=='processed'&&<button className="btn btn-secondary compact" onClick={()=>openReconcile(p)}>Reconcile</button>}</td></tr>)}
   {!punches.length&&<tr><td colSpan="7" className="empty-row">{punchStatus?'No punches with this status.':'No punches received yet. Point a terminal at POST /api/biometrics/punch/ with its API key.'}</td></tr>}
  </tbody></table></div>
  {reconcile&&<div className="modal-backdrop" role="dialog" aria-modal="true" onClick={()=>setReconcile(null)}><div className="modal-card" onClick={e=>e.stopPropagation()}>
   <div className="modal-head"><div><h2>Reconcile punch</h2><p>{new Date(reconcile.punch.punch_time).toLocaleString()} · {reconcile.punch.device_name} · {reconcile.punch.punch_type}</p></div><button type="button" className="icon-btn" aria-label="Close" onClick={()=>setReconcile(null)}>×</button></div>
   {reconcile.punch.error&&<div className="alert alert-warning">{reconcile.punch.error}</div>}
   {reconcileError&&<div className="alert alert-error">{reconcileError}</div>}
   <form onSubmit={submitReconcile}>
    <label htmlFor="reconcile-employee">Employee</label>
    <select id="reconcile-employee" value={reconcile.employee} onChange={e=>setReconcile({...reconcile,employee:e.target.value})} required><option value="">Select employee…</option>{employees.map(e=><option key={e.id} value={e.id}>{e.full_name} ({e.employee_code})</option>)}</select>
    <p className="modal-note">The punch is processed again for this employee. Nothing is invented for it: if the punch still cannot make a shift, it stays in the log.</p>
    <div className="modal-actions"><button type="button" className="btn btn-secondary" onClick={()=>setReconcile(null)}>Cancel</button><button className="btn btn-primary" type="submit">Reconcile punch</button></div>
   </form>
  </div></div>}
 </>}
 </div></div>
}
