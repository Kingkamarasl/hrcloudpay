import { useEffect, useMemo, useState } from 'react';
import { useToast } from '../context/ToastContext';
import { api } from '../api/client';
import Icon from '../components/Icon';

const TARGETS = [
  ['employee_code', 'Employee ID', true],
  ['first_name', 'First name', true],
  ['last_name', 'Last name', true],
  ['email', 'Email', true],
  ['phone', 'Phone', false],
  ['job_title', 'Job title', false],
  ['department', 'Department', false],
  ['base_salary', 'Base salary', true],
  ['hire_date', 'Hire date', false],
  ['employment_status', 'Employment status', false],
  ['id_card_no', 'ID card / identifier', false],
];

const providerCopy = {
  quickbooks: { icon: 'wallet', description: 'Accounting and payroll data sync, including accounting mapping and scheduled syncs.' },
  microsoft365: { icon: 'building', description: 'Import Microsoft 365 users and Excel/OneDrive data through Microsoft Graph.' },
  xero: { icon: 'wallet', description: 'Accounting connection for payroll journals and finance workflows.' },
  google_workspace: { icon: 'users', description: 'Bring workforce identity and spreadsheet data from Google Workspace.' },
  api: { icon: 'settings', description: 'Connect external systems through the HRCloudPay API and webhooks.' },
};

export default function Integrations() {
  const toast = useToast();
  const [data, setData] = useState(null);
  const [job, setJob] = useState(null);
  const [mappingProvider, setMappingProvider] = useState('');
  const [mapping, setMapping] = useState({});
  const [scheduleProvider, setScheduleProvider] = useState('');
  const [schedule, setSchedule] = useState({enabled:false, interval_minutes:1440});
  const [conflicts, setConflicts] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [file, setFile] = useState(null);
  const [importMapping, setImportMapping] = useState({});
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [updateDuplicates, setUpdateDuplicates] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [oauthBusy, setOauthBusy] = useState('');

  async function load() {
    try {
      const [hub, list] = await Promise.all([api.get('/integrations/'), api.get('/integrations/imports/')]);
      setData(hub); setJobs(list || []);
    } catch (err) { setError(err.message || 'Unable to load integrations.'); toast.error(err.message || 'Unable to load integrations.'); }
  }
  useEffect(() => { load(); loadConflicts(); const params=new URLSearchParams(window.location.search); if(params.get('oauth')==='success') setMessage(`${params.get('provider')||'Integration'} connected successfully.`); if(params.get('oauth')==='error') setError(params.get('message')||'Integration connection failed.'); }, []);

  async function connect(provider) {
    const meta = (data?.providers || []).find((p) => p.provider === provider);
    if (meta && meta.configured === false) {
      const label = meta.label || provider;
      const msg = `${label} is not configured yet. A Platform Admin must configure and enable this OAuth provider in Platform Admin → Integrations. Company admins do not enter OAuth application secrets. CSV / Excel import still works without OAuth.`;
      setError(msg);
      toast.warning(msg);
      return;
    }
    setOauthBusy(provider); setError('');
    try {
      const result = await api.get(`/integrations/oauth/${provider}/start/`);
      if (!result?.authorization_url) throw new Error('Provider did not return an authorization URL.');
      window.location.href = result.authorization_url;
    } catch (err) {
      const msg = err.message || 'Could not start connection.';
      setError(msg);
      toast.error(msg);
      setOauthBusy('');
    }
  }
  async function disconnect(provider) { if(!window.confirm('Disconnect this integration? Existing imported records will remain in HRCloudPay.')) return; try { await api.post(`/integrations/connections/${provider}/disconnect/`,{}); await load(); setMessage('Integration disconnected.'); toast.success('Integration disconnected.'); } catch(err) { setError(err.message||'Could not disconnect.'); } }
  async function sync(provider) { setOauthBusy(provider); setError(''); try { const result=await api.post(`/integrations/connections/${provider}/sync/`,{}); if(result.import_job_id) setMessage(`Sync complete. Review import job #${result.import_job_id} before importing.`); else setMessage('Sync request completed.'); await load(); } catch(err) { setError(err.message||'Sync failed.'); } finally { setOauthBusy(''); } }

  async function accountingSync(provider) { setOauthBusy(provider); setError(''); try { const r=await api.post(`/integrations/connections/${provider}/accounting-sync/`,{}); setMessage(`Synced ${r.catalog?.records||0} accounting records.`); await load(); } catch(err){setError(err.message||'Accounting sync failed.');} finally{setOauthBusy('');} }
  async function openMapping(provider) { try { const r=await api.get(`/integrations/connections/${provider}/accounting-mapping/`); setMappingProvider(provider); setMapping(r.mapping||{}); } catch(err){setError(err.message||'Could not load accounting mapping.');} }
  async function saveAccountingMapping() { if(!mappingProvider) return; try { await api.put(`/integrations/connections/${mappingProvider}/accounting-mapping/`,mapping); setMessage('Accounting mapping saved.'); setMappingProvider(''); } catch(err){setError(err.message||'Could not save mapping.');} }
  async function configureSchedule(provider) { try { const r=await api.get(`/integrations/connections/${provider}/schedule/`); setScheduleProvider(provider); setSchedule(r); } catch(err){setError(err.message||'Could not load schedule.');} }
  async function saveSchedule() { if(!scheduleProvider) return; try { const r=await api.put(`/integrations/connections/${scheduleProvider}/schedule/`,schedule); setSchedule(r); setMessage('Scheduled synchronization updated.'); } catch(err){setError(err.message||'Could not save schedule.');} }
  async function loadConflicts(){ try { const r=await api.get('/integrations/conflicts/'); setConflicts(r||[]); } catch(err){setError(err.message||'Could not load conflicts.');} }
  async function resolveConflict(id,resolution){ try { await api.post(`/integrations/conflicts/${id}/resolve/`,{resolution}); await loadConflicts(); setMessage('Conflict resolved.'); } catch(err){setError(err.message||'Could not resolve conflict.');} }

  async function upload() {
    if (!file) {
      const msg = 'Choose a CSV or .xlsx file first.';
      setError(msg); toast.warning(msg);
      return;
    }
    const name = (file.name || '').toLowerCase();
    if (!name.endsWith('.csv') && !name.endsWith('.xlsx')) {
      const msg = 'Unsupported file type. Upload a CSV or .xlsx workbook.';
      setError(msg); toast.error(msg);
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      const msg = 'File is too large. Maximum size is 10 MB.';
      setError(msg); toast.error(msg);
      return;
    }
    setError(''); setMessage(''); setUploading(true);
    try {
      const form = new FormData();
      form.append('file', file, file.name);
      const result = await api.upload('/integrations/imports/upload/', form);
      setJob(result);
      setImportMapping(result.mapping || {});
      setFile(null);
      const msg = 'File analyzed. Review the mapping and validation results before importing.';
      setMessage(msg);
      toast.success(msg);
      await load();
    } catch (err) {
      const msg = err.message || 'Import analysis failed. Check that the company is activated and the backend has openpyxl installed for Excel files.';
      setError(msg);
      toast.error(msg);
    } finally {
      setUploading(false);
    }
  }

  async function saveMapping() {
    if (!job) return;
    setBusy(true); setError('');
    try { const result = await api.patch(`/integrations/imports/${job.id}/`, { mapping: importMapping }); setJob(result); setMessage('Field mapping updated and the data was revalidated.'); }
    catch (err) { setError(err.message || 'Could not update mapping.'); }
    finally { setBusy(false); }
  }

  async function execute() {
    if (!job) return;
    if (!window.confirm(`Import ${job.valid_rows} valid employee rows into HRCloudPay?`)) return;
    setBusy(true); setError(''); setMessage('Importing employees...');
    try { const result = await api.post(`/integrations/imports/${job.id}/execute/`, { update_duplicates: updateDuplicates }); setJob(result); setMessage(result.status === 'completed' ? 'Import completed successfully.' : 'Import completed with warnings. Review the result below.'); await load(); }
    catch (err) { setError(err.message || 'Import failed.'); }
    finally { setBusy(false); }
  }

  async function rollback() {
    if (!job || !window.confirm('Roll back the employees created by this import? Existing employees updated by the import will not be reverted.')) return;
    setBusy(true); setError('');
    try { const result = await api.post(`/integrations/imports/${job.id}/rollback/`, {}); setJob(result); setMessage('Created records from this import were rolled back.'); await load(); }
    catch (err) { setError(err.message || 'Rollback failed.'); }
    finally { setBusy(false); }
  }

  const previewRows = useMemo(() => (job?.rows || []).slice(0, 25), [job]);

  return <div className="page">
    <div className="page-header">
      <div><div className="eyebrow">INTEGRATIONS</div><h1>Integrations & data migration</h1><p>Bring your existing workforce data into HRCloudPay without starting over.</p></div>
    </div>
    {error && <div className="alert alert-error">{error}</div>}
    {message && <div className="alert alert-success">{message}</div>}

    <section className="card">
      <div className="section-head"><div><h2>Integration Hub</h2><p>Connect the systems your company already uses. Connect your existing business systems. Microsoft 365 user sync is active; QuickBooks and Xero connections support accounting sync, mapping and scheduling.</p></div></div>
      <div className="integration-grid">
        {(data?.providers || []).map((provider) => { const copy = providerCopy[provider.provider] || {}; return <div className="integration-card" key={provider.provider}>
          <div className="integration-icon"><Icon name={copy.icon || 'settings'} /></div>
          <div className="integration-body"><div className="integration-title"><strong>{provider.label}</strong><span className={`badge badge-${provider.configured === false ? 'not_configured' : provider.status}`}>{provider.configured === false ? 'Not configured' : provider.status.replaceAll('_', ' ')}</span></div><p>{copy.description}</p>{provider.last_synced_at && <small>Last sync: {new Date(provider.last_synced_at).toLocaleString()}</small>}{provider.connected ? <div className="import-actions"><button className="btn btn-secondary" disabled={oauthBusy===provider.provider} onClick={()=>sync(provider.provider)}>{oauthBusy===provider.provider?'Syncing...':'Sync now'}</button>{(provider.provider==='quickbooks'||provider.provider==='xero') && <><button className="btn btn-secondary" onClick={()=>accountingSync(provider.provider)}>Sync accounting</button><button className="btn btn-secondary" onClick={()=>openMapping(provider.provider)}>Accounting mapping</button><button className="btn btn-secondary" onClick={()=>configureSchedule(provider.provider)}>Schedule</button></>}<button className="btn btn-secondary" onClick={()=>disconnect(provider.provider)}>Disconnect</button></div> : provider.configured === false ? <button className="btn btn-secondary" disabled title="Add OAuth credentials in server environment">Not configured</button> : provider.provider==='api' ? <span className="integration-note">Available to administrators only — ask your HRCloudPay administrator to issue API credentials.</span> : <button className="btn btn-primary" disabled={oauthBusy===provider.provider} onClick={()=>connect(provider.provider)}>{oauthBusy===provider.provider?'Connecting…':'Connect'}</button>}</div>
        </div>; })}
      </div>
    </section>

    {mappingProvider && <section className="card"><div className="section-head"><div><div className="eyebrow">ACCOUNTING MAPPING</div><h2>{mappingProvider}</h2><p>Map HRCloudPay payroll totals to the provider's accounting accounts. IDs can be entered from the provider account catalog.</p></div></div><div className="mapping-grid">{[['payroll_expense_account_id','Payroll expense account'],['payroll_liability_account_id','Payroll liability account'],['net_pay_account_id','Net pay account'],['employer_contribution_account_id','Employer contribution account']].map(([k,l])=><label key={k}><span>{l}</span><input value={mapping[k]||''} onChange={e=>setMapping({...mapping,[k]:e.target.value})} placeholder="External account ID/code" /></label>)}</div><div className="import-actions"><button className="btn btn-primary" onClick={saveAccountingMapping}>Save mapping</button><button className="btn btn-secondary" onClick={()=>setMappingProvider('')}>Close</button></div></section>}
    {scheduleProvider && <section className="card"><div className="section-head"><div><div className="eyebrow">AUTOMATION</div><h2>Scheduled synchronization</h2><p>HRCloudPay can run provider synchronization from a server scheduler using the integration management command.</p></div></div><div className="import-actions"><label className="checkbox-label"><input type="checkbox" checked={!!schedule.enabled} onChange={e=>setSchedule({...schedule,enabled:e.target.checked})}/> Enable scheduled sync</label><label>Interval (minutes)<input type="number" min="60" max="10080" value={schedule.interval_minutes||1440} onChange={e=>setSchedule({...schedule,interval_minutes:Number(e.target.value)})}/></label><button className="btn btn-primary" onClick={saveSchedule}>Save schedule</button><button className="btn btn-secondary" onClick={()=>setScheduleProvider('')}>Close</button></div></section>}

    <section className="card">
      <div className="section-head"><div><div className="eyebrow">MIGRATION WIZARD</div><h2>Import existing employee data</h2><p>Upload a CSV or Excel workbook. HRCloudPay will analyze it, suggest field mappings, detect duplicates, and validate records before anything is written.</p></div></div>
      <div className="import-upload-row"><label className="file-drop"><input type="file" accept=".csv,.xlsx" onChange={(e) => setFile(e.target.files?.[0] || null)} /><span>{file ? file.name : 'Choose CSV or .xlsx file'}</span><small>Maximum 10 MB · up to 5,000 rows</small></label><button className="btn btn-primary" disabled={!file || uploading} onClick={upload}>{uploading ? 'Analyzing...' : 'Analyze file'}</button></div>
    </section>

    {job && <section className="card">
      <div className="section-head"><div><div className="eyebrow">IMPORT JOB #{job.id}</div><h2>{job.filename}</h2><p>Nothing is imported until you explicitly approve the job.</p></div><span className={`badge badge-${job.status}`}>{job.status.replaceAll('_', ' ')}</span></div>
      <div className="stats-grid"><div className="stat-card"><div className="stat-value">{job.total_rows}</div><div className="stat-label">Rows</div></div><div className="stat-card"><div className="stat-value">{job.valid_rows}</div><div className="stat-label">Valid</div></div><div className="stat-card"><div className="stat-value">{job.warning_rows}</div><div className="stat-label">Warnings</div></div><div className="stat-card"><div className="stat-value">{job.error_rows}</div><div className="stat-label">Errors</div></div><div className="stat-card"><div className="stat-value">{job.duplicate_rows}</div><div className="stat-label">Existing matches</div></div></div>

      {job.status === 'ready' && <>
        <h3>Field mapping</h3><div className="mapping-grid">{TARGETS.map(([key, label, required]) => <label key={key}><span>{label}{required && ' *'}</span><select value={importMapping[key] || ''} onChange={(e) => setImportMapping({ ...importMapping, [key]: e.target.value })}><option value="">Not mapped</option>{(job.headers || []).map((header) => <option key={header} value={header}>{header}</option>)}</select></label>)}</div>
        <div className="import-actions"><button className="btn btn-secondary" disabled={busy} onClick={saveMapping}>Revalidate mapping</button><label className="checkbox-label"><input type="checkbox" checked={updateDuplicates} onChange={(e) => setUpdateDuplicates(e.target.checked)} /> Update existing employees when an Employee ID or email matches</label><button className="btn btn-primary" disabled={busy || job.valid_rows === 0} onClick={execute}>{busy ? 'Working...' : 'Approve & import'}</button></div>
      </>}

      {previewRows.length > 0 && <div className="table-wrap import-preview"><table className="data-table"><thead><tr><th>Row</th><th>Employee</th><th>Email</th><th>Department</th><th>Salary</th><th>Result</th></tr></thead><tbody>{previewRows.map((row) => <tr key={row.row_number}><td>{row.row_number}</td><td>{row.data?.first_name} {row.data?.last_name}</td><td>{row.data?.email}</td><td>{row.data?.department || '—'}</td><td>{row.data?.base_salary || '—'}</td><td>{row.errors?.length ? <span className="text-danger">{row.errors[0]}</span> : row.warnings?.length ? <span className="text-warning">{row.warnings[0]}</span> : <span className="text-success">Ready</span>}</td></tr>)}</tbody></table></div>}
      {job.rows?.length > 25 && <p className="muted">Showing the first 25 rows. The complete validation result is retained in the import job.</p>}
      {job.result?.failed_rows?.length > 0 && <div className="alert alert-error">{job.result.failed_rows.length} row(s) could not be imported. Review the job result and correct the source data before retrying those records.</div>}
      {(job.status === 'completed' || job.status === 'completed_with_warnings') && <div className="import-actions"><button className="btn btn-secondary" disabled={busy} onClick={rollback}>Rollback created records</button><small>Rollback removes employees created by this import. It does not reverse updates to existing employees.</small></div>}
    </section>}

    <section className="card"><div className="section-head"><div><div className="eyebrow">SYNC GOVERNANCE</div><h2>Conflicts requiring review</h2><p>External systems never silently overwrite HRCloudPay data when a conflict needs a decision.</p></div></div><div className="table-wrap"><table className="data-table"><thead><tr><th>Provider</th><th>Entity</th><th>External ID</th><th>Action</th></tr></thead><tbody>{conflicts.map(c=><tr key={c.id}><td>{c.provider}</td><td>{c.entity_type}</td><td>{c.external_id}</td><td><div className="import-actions"><button className="btn btn-secondary" onClick={()=>resolveConflict(c.id,'external')}>Use external</button><button className="btn btn-secondary" onClick={()=>resolveConflict(c.id,'local')}>Keep HRCloudPay</button><button className="btn btn-secondary" onClick={()=>resolveConflict(c.id,'merged')}>Mark merged</button></div></td></tr>)}{!conflicts.length&&<tr><td colSpan="4" className="empty-row">No pending conflicts.</td></tr>}</tbody></table></div></section>

    <section className="card"><div className="section-head"><div><h2>Import history</h2><p>Every migration is tracked so your team can see what happened.</p></div></div><div className="table-wrap"><table className="data-table"><thead><tr><th>Job</th><th>Source</th><th>Status</th><th>Rows</th><th>Valid</th><th>Errors</th><th>Date</th></tr></thead><tbody>{jobs.map((item) => <tr key={item.id}><td>#{item.id} · {item.filename}</td><td>{item.source_label}</td><td>{item.status.replaceAll('_', ' ')}</td><td>{item.total_rows}</td><td>{item.valid_rows}</td><td>{item.error_rows}</td><td>{new Date(item.created_at).toLocaleString()}</td></tr>)}{!jobs.length && <tr><td colSpan="7" className="empty-row">No imports yet.</td></tr>}</tbody></table></div></section>
  </div>;
}
