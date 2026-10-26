import {useEffect,useState} from 'react';
import {api} from '../api/client';
import Icon from '../components/Icon';

// Mirrors STATUS_LABELS from backend/attendance/grid.py. A status the API
// returns that is not in this map renders as a grey cell rather than crashing
// the grid - the page must keep working for a status the backend learned about
// after this bundle shipped.
const STATUS_COLOR={
  present:'#16a34a',half_day:'#ca8a04',absent:'#dc2626',leave:'#2563eb',
  not_added:'#e5e7eb',
};
const STATUS_LETTER={present:'P',half_day:'H',absent:'A',leave:'L',not_added:''};

function monthLabel(y,m){return new Date(y,m-1,1).toLocaleString(undefined,{month:'long',year:'numeric'})}

export default function AttendanceGrid(){
 const now=new Date();
 const [year,setYear]=useState(now.getFullYear());
 const [month,setMonth]=useState(now.getMonth()+1);
 const [department,setDepartment]=useState('');
 const [employee,setEmployee]=useState('');
 const [employees,setEmployees]=useState([]);
 const [data,setData]=useState(null);
 const [loading,setLoading]=useState(true);
 const [error,setError]=useState('');
 const [selected,setSelected]=useState(null);

 async function load(){
  setLoading(true);
  try{
   const params=new URLSearchParams({year,month});
   if(department)params.set('department',department);
   if(employee)params.set('employee',employee);
   const d=await api.get(`/attendance/month-grid/?${params}`);
   setData(d);setError('');
  }catch(e){setError(e.message||'Could not load the attendance grid.')}
  finally{setLoading(false)}
 }
 useEffect(()=>{load()},[year,month,department,employee]);
 useEffect(()=>{
  // The employee list is nested below the employees router; /employees/ is
  // only the DRF browsable API root and returns child URLs, not employee rows.
  api.get('/employees/employees/?limit=500').then(d=>{
   const arr=d.results??d; setEmployees(Array.isArray(arr)?arr:(arr.results??[]));
  }).catch(()=>{});
 },[]);

 function shift(delta){
  let m=month+delta,y=year;
  if(m>12){m=1;y++}
  if(m<1){m=12;y--}
  setMonth(m);setYear(y);
 }

 if(loading && !data) return <div className="page-loading">Loading attendance grid…</div>;
 const days=data?.rows?.[0]?.days?.length||0;
 const dayNumbers=data?.rows?.[0]?.days?.map((_,i)=>i+1)||[];
 return <div className="page-shell">
 <section className="page-header"><div><div className="eyebrow">ATTENDANCE</div><h1>Monthly attendance grid</h1><p>One row per employee, one column per day. Derived statuses (late, early departure, overtime) are computed, not stored.</p></div>
  <div style={{display:'flex',gap:8,alignItems:'center',flexWrap:'wrap'}}>
   <button className="btn btn-secondary compact" onClick={()=>shift(-1)}><Icon name="chevron" size={14}/></button>
   <strong style={{minWidth:150,textAlign:'center'}}>{monthLabel(year,month)}</strong>
   <button className="btn btn-secondary compact" onClick={()=>shift(1)}><Icon name="chevron" size={14}/></button>
   <select value={department} onChange={e=>setDepartment(e.target.value)} style={{marginLeft:8}}>
    <option value="">All departments</option>
    {[...new Set(employees.map(e=>e.department||e.department_name).filter(Boolean))].map(d=><option key={d} value={d}>{d}</option>)}
   </select>
   <select value={employee} onChange={e=>setEmployee(e.target.value)}>
    <option value="">All employees</option>
    {employees.map(e=><option key={e.id} value={e.id}>{e.full_name}</option>)}
   </select>
  </div></section>
 {error&&<div className="alert alert-error">{error}</div>}
 {data&&<>
  <div className="legend" style={{display:'flex',gap:12,flexWrap:'wrap',margin:'8px 0 16px',fontSize:13}}>
   {Object.entries(STATUS_COLOR).filter(([k])=>k!=='not_added').map(([k,c])=><span key={k} style={{display:'inline-flex',alignItems:'center',gap:4}}><span style={{width:12,height:12,background:c,borderRadius:2,display:'inline-block'}}></span>{k.replace('_',' ')}</span>)}
   <span style={{display:'inline-flex',alignItems:'center',gap:4}}><span style={{width:12,height:12,background:'#e5e7eb',borderRadius:2,display:'inline-block'}}></span>no record</span>
  </div>
  <div style={{overflowX:'auto'}}>
   <table className="data-table" style={{minWidth:60+days*26}}>
    <thead><tr><th style={{position:'sticky',left:0,background:'var(--bg,white)',zIndex:2}}>Employee</th>
     {dayNumbers.map(d=><th key={d} style={{width:26,textAlign:'center',padding:2}}>{d}</th>)}
     <th>Worked</th><th>Late</th><th>Overtime</th></tr></thead>
    <tbody>
     {data.rows.map(r=><tr key={r.employee.id}>
      <td style={{position:'sticky',left:0,background:'var(--bg,white)',zIndex:1,whiteSpace:'nowrap'}}><strong>{r.employee.name}</strong><br/><small>{r.employee.employee_code}</small></td>
      {r.days.map(c=>{
       const st=c.status||'not_added';
       const color=STATUS_COLOR[st]||'#e5e7eb';
       const letter=STATUS_LETTER[st]||'';
       return <td key={c.date} title={`${c.date}: ${st}${c.check_in?' in '+c.check_in:''}${c.check_out?' out '+c.check_out:''}${c.late_minutes?' late '+c.late_minutes+'m':''}${c.overtime_minutes?' ot '+c.overtime_minutes+'m':''}`} style={{background:color,color:st==='not_added'?'#6b7280':'white',textAlign:'center',padding:2,cursor:'pointer',fontWeight:600}} onClick={()=>setSelected({employee:r.employee,cell:c})}>{letter}</td>;
      })}
      <td style={{textAlign:'center'}}>{r.summary.worked_ratio}</td>
      <td style={{textAlign:'center'}}>{r.summary.late_days||0}</td>
      <td style={{textAlign:'center'}}>{r.summary.overtime_minutes||0}</td>
     </tr>)}
     {!data.rows.length&&<tr><td colSpan={days+4} className="empty-row">No employees match the current filters.</td></tr>}
    </tbody>
   </table>
  </div>
  {selected&&<div className="modal-backdrop" onClick={()=>setSelected(null)}><div className="modal" onClick={e=>e.stopPropagation()}>
   <h2>{selected.employee.name} — {selected.cell.date}</h2>
   <div className="plan-meta">
    <div><strong>Status:</strong> {selected.cell.status}</div>
    {selected.cell.check_in&&<div><strong>Check in:</strong> {selected.cell.check_in}</div>}
    {selected.cell.check_out&&<div><strong>Check out:</strong> {selected.cell.check_out}</div>}
    {selected.cell.late_minutes?<div><strong>Late:</strong> {selected.cell.late_minutes} min</div>:null}
    {selected.cell.early_minutes?<div><strong>Early departure:</strong> {selected.cell.early_minutes} min</div>:null}
    {selected.cell.overtime_minutes?<div><strong>Overtime:</strong> {selected.cell.overtime_minutes} min</div>:null}
   </div>
   <div className="modal-actions"><button className="btn btn-secondary" onClick={()=>setSelected(null)}>Close</button></div>
  </div></div>}
 </>}
 </div>
}
