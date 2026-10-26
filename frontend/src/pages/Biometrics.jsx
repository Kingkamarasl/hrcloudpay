import {useEffect,useState} from 'react';
import {api} from '../api/client';
import Icon from '../components/Icon';

// Biometric terminals have no user account and no browser. They authenticate
// with an API key and POST punches; HRCloudPay turns those into attendance
// records. Templates never leave the device, so the most sensitive data is not
// in this database or in any backup of it.
const TABS=[['devices','Devices'],['enrollments','Enrollments'],['punches','Punch log']];

export default function Biometrics(){
 const [tab,setTab]=useState('devices');
 const [devices,setDevices]=useState([]),[enrollments,setEnrollments]=useState([]),[punches,setPunches]=useState([]);
 const [employees,setEmployees]=useState([]);
 const [loading,setLoading]=useState(true),[error,setError]=useState('');
 const [newKey,setNewKey]=useState(null),[form,setForm]=useState({name:'',device_id:'',device_type:'fingerprint',location:''});
 const [enrollForm,setEnrollForm]=useState({employee:'',device:'',method:'fingerprint',template_id:''});
 async function load(){
  setLoading(true);
  try{
   const [d,e,p,em]=await Promise.all([
     api.get('/biometrics/devices/'),
     api.get('/biometrics/enrollments/'),
     api.get('/biometrics/punches/?limit=100'),
     api.get('/employees/employees/?limit=500'),
   ]);
   setDevices(d.results??d);setEnrollments(e.results??e);setPunches(p.results??p);
   const empData=em.results??em;
   setEmployees(Array.isArray(empData)?empData:(empData.results??[]));
   setError('');
  }catch(e){setError(e.message||'Could not load biometric data.')}
  finally{setLoading(false)}
 }
 useEffect(()=>{load()},[]);
 async function register(e){
  e.preventDefault();
  try{
   const created=await api.post('/biometrics/devices/',form);
   setNewKey(created.api_key);setForm({name:'',device_id:'',device_type:'fingerprint',location:''});await load();
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
 if(loading)return <div className="page-loading">Loading biometric data…</div>;
 return <div className="page-shell">
 <section className="page-header"><div><div className="eyebrow">ATTENDANCE</div><h1>Biometric terminals</h1><p>Register fingerprint, face, iris or card terminals, enrol employees on them, and review the punches they report. Templates stay on the device.</p></div><button className="btn btn-secondary" onClick={load}><Icon name="refresh" size={15}/>Refresh</button></section>
 {error&&<div className="alert alert-error">{error}</div>}
 {newKey&&<div className="alert alert-warning"><strong>Copy this key now.</strong> It is shown once and never stored in readable form. Paste it into the terminal's configuration and keep it safe: {newKey}<button className="btn btn-secondary compact" style={{marginLeft:12}} onClick={()=>setNewKey(null)}>I have saved it</button></div>}
 <div className="panel"><div className="tabs">{TABS.map(([k,l])=><button key={k} className={`tab ${tab===k?'active':''}`} onClick={()=>setTab(k)}>{l}</button>)}</div>
 {tab==='devices'&&<>
  <form className="form-grid" onSubmit={register} style={{padding:16}}>
   <div className="form-row"><div><label>Name</label><input value={form.name} onChange={e=>setForm({...form,name:e.target.value})} required/></div><div><label>Device ID</label><input value={form.device_id} onChange={e=>setForm({...form,device_id:e.target.value})} required placeholder="Serial number"/></div></div>
   <div className="form-row"><div><label>Type</label><select value={form.device_type} onChange={e=>setForm({...form,device_type:e.target.value})}><option value="fingerprint">Fingerprint</option><option value="face">Face recognition</option><option value="iris">Iris</option><option value="palm">Palm</option><option value="card">Card / RFID</option><option value="other">Other</option></select></div><div><label>Location</label><input value={form.location} onChange={e=>setForm({...form,location:e.target.value})} placeholder="Lobby, gate 2…"/></div></div>
   <div className="modal-actions"><button className="btn btn-primary" type="submit"><Icon name="plus" size={15}/>Register terminal</button></div>
  </form>
  <div className="table-wrap"><table className="data-table"><thead><tr><th>Name</th><th>Device ID</th><th>Type</th><th>Location</th><th>Status</th><th>Last seen</th><th></th></tr></thead><tbody>
   {devices.map(d=><tr key={d.id}><td><strong>{d.name}</strong></td><td>{d.device_id}</td><td>{d.device_type}</td><td>{d.location||'—'}</td><td><span className={`badge badge-${d.status==='active'?'paid':d.status==='retired'?'rejected':'pending'}`}>{d.status}</span></td><td>{d.last_seen_at?new Date(d.last_seen_at).toLocaleString():'Never'}</td><td>{d.status!=='retired'&&<button className="btn btn-secondary compact" onClick={()=>retire(d.id)}>Retire</button>}</td></tr>)}
   {!devices.length&&<tr><td colSpan="7" className="empty-row">No terminals registered. Register one above and paste its API key into the device.</td></tr>}
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
  <div className="table-wrap"><table className="data-table"><thead><tr><th>Time</th><th>Employee</th><th>Terminal</th><th>Type</th><th>Status</th><th>Error</th></tr></thead><tbody>
   {punches.map(p=><tr key={p.id}><td>{new Date(p.punch_time).toLocaleString()}</td><td>{p.employee_name||'Unmatched'}</td><td>{p.device_name}</td><td>{p.punch_type}</td><td><span className={`badge badge-${p.status==='processed'?'paid':p.status==='failed'?'rejected':'pending'}`}>{p.status}</span></td><td>{p.error||'—'}</td></tr>)}
   {!punches.length&&<tr><td colSpan="6" className="empty-row">No punches received yet. Point a terminal at POST /api/biometrics/punch/ with its API key.</td></tr>}
  </tbody></table></div>
 </>}
 </div></div>
}
