import {Link} from 'react-router-dom';
import {useEffect,useMemo,useState} from 'react';
import {api} from '../api/client';
import Icon from '../components/Icon';

const emptyForm={id_card_no:'',first_name:'',last_name:'',email:'',phone:'',job_title:'',department_obj:'',pay_point:'',bank_account_number:'',base_salary:'',hire_date:'',employment_status:'active',employment_category:'long_time'};
const categories=[{v:'casual',l:'Casual (CA-####)'},{v:'short_time',l:'Short time (ST-####)'},{v:'long_time',l:'Long time (LT-####)'}];
const statuses=['active','on_leave','suspended','terminated','resigned'];
const nice=s=>(s||'').replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());

export default function Employees(){
  const[employees,setEmployees]=useState([]),[departments,setDepartments]=useState([]),[loading,setLoading]=useState(true),[showForm,setShowForm]=useState(false),[form,setForm]=useState(emptyForm),[error,setError]=useState(''),[query,setQuery]=useState(''),[status,setStatus]=useState(''),[department,setDepartment]=useState(''),[showImport,setShowImport]=useState(false),[importLoading,setImportLoading]=useState(false),[importResult,setImportResult]=useState(null),[importFile,setImportFile]=useState(null);
  function load(){setLoading(true);setError('');Promise.all([api.get('/employees/employees/'),api.get('/employees/departments/')]).then(([e,d])=>{setEmployees(e.results??e);setDepartments(d.results??d)}).catch(e=>setError(e.message||'Unable to load employee directory.')).finally(()=>setLoading(false));}
  useEffect(load,[]);
  const filtered=useMemo(()=>employees.filter(e=>{const text=`${e.full_name} ${e.employee_code} ${e.id_card_no||''} ${e.department||''} ${e.effective_department||''} ${e.job_title||''} ${e.email||''}`.toLowerCase();return text.includes(query.toLowerCase())&&(!status||e.employment_status===status)&&(!department||String(e.department_obj)===String(department));}),[employees,query,status,department]);
  const metrics=useMemo(()=>({total:employees.length,active:employees.filter(e=>e.employment_status==='active').length,onLeave:employees.filter(e=>e.employment_status==='on_leave').length,needsAttention:employees.filter(e=>['suspended','terminated','resigned'].includes(e.employment_status)).length}),[employees]);
  async function submit(e){e.preventDefault();setError('');try{await api.post('/employees/employees/',form);setForm(emptyForm);setShowForm(false);load()}catch(err){setError(err.message||'Failed to add employee')}}

  async function handleImport(e){
    e.preventDefault();
    if(!importFile) return;
    setImportLoading(true);
    setImportResult(null);
    const formData = new FormData();
    formData.append('file', importFile);
    try {
      const res = await api.post('/employees/employees/import-csv/', formData, { headers: { 'Content-Type': 'multipart/form-data' } });
      setImportResult({ success: true, data: res });
    } catch (err) {
      setImportResult({ success: false, error: err.message || 'Import failed' });
    } finally {
      setImportLoading(false);
      load();
    }
  }
  return <div>
    <div className="page-header"><div><div className="eyebrow">PEOPLE & HR</div><h1>Employees</h1><p className="page-subtitle">Manage employee records, employment status, departments and the complete HR lifecycle.</p></div>
    <div className="header-actions">
      <button className="btn btn-secondary compact" onClick={()=>setShowImport(!showImport)}>{showImport?'Cancel':'Import CSV'}</button>
      <button className="btn btn-primary compact" onClick={()=>setShowForm(!showForm)}>{showForm?'Cancel':'+ Add employee'}</button>
    </div>
    </div>
    {error&&<div className="alert alert-error">{error}</div>}
    <div className="employee-summary-grid"><div className="employee-summary-card"><span>Total workforce</span><strong>{metrics.total}</strong><small>Employee records</small></div><div className="employee-summary-card"><span>Active employees</span><strong>{metrics.active}</strong><small>Currently working</small></div><div className="employee-summary-card"><span>On leave</span><strong>{metrics.onLeave}</strong><small>Temporary absence</small></div><div className="employee-summary-card"><span>Needs attention</span><strong>{metrics.needsAttention}</strong><small>Suspended / separated</small></div></div>
    {showForm&&<form className="panel form-panel employee-create-panel" onSubmit={submit}>
      <div className="panel-head"><div><div className="eyebrow">NEW EMPLOYEE</div><h2>Core employee record</h2><p>Create the employee first. Personal details, emergency contacts, contracts and lifecycle history can then be completed from the Employee 360 profile.</p></div></div>
      <div className="form-section-label">Identity & employment</div>
      <div className="form-row">{[['id_card_no','National ID (optional)'],['first_name','First name'],['last_name','Last name']].map(([k,l])=><div key={k}><label>{l}</label><input value={form[k]} onChange={e=>setForm({...form,[k]:e.target.value})} required={['first_name','last_name'].includes(k)}/></div>)}</div>
      <div className="form-row"><div><label>Email</label><input type="email" value={form.email} onChange={e=>setForm({...form,email:e.target.value})} required/></div><div><label>Phone</label><input value={form.phone} onChange={e=>setForm({...form,phone:e.target.value})}/></div><div><label>Job title</label><input value={form.job_title} onChange={e=>setForm({...form,job_title:e.target.value})}/></div><div><label>Department</label><select value={form.department_obj} onChange={e=>setForm({...form,department_obj:e.target.value})}><option value="">Unassigned</option>{departments.map(d=><option key={d.id} value={d.id}>{d.name}</option>)}</select></div></div>
      <div className="form-row"><div><label>Base salary</label><input type="number" min="0" step="0.01" value={form.base_salary} onChange={e=>setForm({...form,base_salary:e.target.value})} required/></div><div><label>Hire date</label><input type="date" value={form.hire_date} onChange={e=>setForm({...form,hire_date:e.target.value})}/></div><div><label>Employment status</label><select value={form.employment_status} onChange={e=>setForm({...form,employment_status:e.target.value})}>{statuses.map(s=><option key={s} value={s}>{nice(s)}</option>)}</select></div>
        <div><label>Employment category</label><select value={form.employment_category} onChange={e=>setForm({...form,employment_category:e.target.value})} required>{categories.map(c=><option key={c.v} value={c.v}>{c.l}</option>)}</select>
        <small className="table-subline">System assigns ID: CA-#### / ST-#### / LT-####</small></div></div>
      <div className="form-row"><div><label>Pay point / duty station</label><input value={form.pay_point} onChange={e=>setForm({...form,pay_point:e.target.value})} placeholder="e.g. site or branch name"/></div><div><label>Bank account number</label><input value={form.bank_account_number} onChange={e=>setForm({...form,bank_account_number:e.target.value})}/></div></div>
      <div className="employee-create-note"><Icon name="info" size={15}/><span>For sensitive HR information, use the employee's profile after creation so the record stays organized by employee.</span></div>
      <button className="btn btn-primary compact" type="submit">Create employee</button>
    </form>}
    {showImport&&<div className="panel form-panel migration-panel">
      <div className="panel-head"><div><div className="eyebrow">MIGRATION WIZARD</div><h2>Bulk Import Employees</h2><p>Upload a CSV file to import multiple employee records. Ensure columns match the required format.</p></div></div>
      <form onSubmit={handleImport}>
        <div className="form-row">
          <div><label>CSV File</label><input type="file" accept=".csv" onChange={e=>setImportFile(e.target.files[0])} required/></div>
        </div>
        <div className="migration-note"><Icon name="info" size={15}/><span>Required columns: first_name, last_name, email, base_salary. Other fields are optional.</span></div>
        <button className="btn btn-primary compact" type="submit" disabled={importLoading}>{importLoading?'Importing...':'Start Migration'}</button>
      </form>
      {importResult && (
        <div className={`alert ${importResult.success ? 'alert-success' : 'alert-error'}`}>
          {importResult.success ? `Successfully imported ${importResult.data.imported} employees.` : importResult.error}
          {importResult.data?.failures?.length > 0 && <div className="import-failures">Failed rows: {importResult.data.failures.map(f=>`Row ${f.row}: ${JSON.stringify(f.errors||f.error)}`).join(', ')}</div>}
        </div>
      )}
    </div>}
    <div className="panel table-panel"><div className="panel-head"><div><div className="eyebrow">WORKFORCE DIRECTORY</div><h2>Employee directory <span className="count-pill">{filtered.length}</span></h2><p>Search by employee, ID, department, job title or email.</p></div><div className="table-tools"><div className="search-input"><Icon name="search" size={16}/><input placeholder="Search employees..." value={query} onChange={e=>setQuery(e.target.value)}/></div><select value={department} onChange={e=>setDepartment(e.target.value)}><option value="">All departments</option>{departments.map(d=><option key={d.id} value={d.id}>{d.name}</option>)}</select><select value={status} onChange={e=>setStatus(e.target.value)}><option value="">All statuses</option>{statuses.map(s=><option key={s} value={s}>{nice(s)}</option>)}</select></div></div>
      {loading?<div className="page-loading">Loading employee directory…</div>:<div className="table-wrap"><table className="data-table modern-table"><thead><tr><th>Employee</th><th>ID / contact</th><th>Department</th><th>Role</th><th>Contract</th><th>Status</th><th>HR records</th></tr></thead><tbody>{filtered.map(e=><tr key={e.id}><td><div className="person-cell"><div className="avatar">{e.profile_photo_url ? <img src={e.profile_photo_url} alt="" /> : (e.full_name||'E').slice(0,2).toUpperCase()}</div><div><Link to={`/employees/${e.id}`} className="table-person-link"><strong>{e.full_name}</strong></Link><small>{e.employee_code}{e.employment_category ? ` · ${nice(e.employment_category)}` : ''}</small></div></div></td><td><strong>{e.id_card_no||'—'}</strong><small className="table-subline">{e.email||e.phone||'No contact'}</small></td><td>{e.effective_department||e.department||'Unassigned'}</td><td>{e.job_title||'—'}</td><td><span className={`mini-status ${e.contract_status||'none'}`}>{nice(e.contract_status||'none')}</span>{e.contract_end_date&&<small className="table-subline">Ends {e.contract_end_date}</small>}</td><td><span className={`status-dot status-${e.employment_status}`}><i/>{nice(e.employment_status)}</span></td><td><div className="hr-record-counts"><span>{e.emergency_contact_count||0} contact</span><span>{e.employment_event_count||0} events</span></div></td></tr>)}{!filtered.length&&<tr><td colSpan="7" className="empty-row">No employees match your filters.</td></tr>}</tbody></table></div>}
    </div>
  </div>
}
