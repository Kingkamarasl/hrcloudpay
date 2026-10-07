import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import Icon from '../components/Icon';
import MarketingEditor from '../components/MarketingEditor';

const EMPTY = { company_name:'', country:'', company_email:'', phone:'', plan:'starter', owner_username:'', owner_email:'', owner_password:'', activate_immediately:true, payroll_configured:false };
import { PLAN_ORDER, PLAN_LABELS, planLabel } from '../constants/plans';
const PLANS = { starter:'Starter', business:'Business', professional:'Professional', scale:'Scale', enterprise:'Enterprise' };
const tabs = [
  ['overview','Overview'], ['companies','Companies'], ['subscriptions','Billing'], ['usage','Usage'], ['content','Marketing content'],
  ['seo','Search (SEO)'], ['onboarding','Onboarding'], ['support','Support'], ['notifications','Communications'], ['payments','Transactions'], ['audit','Audit log'], ['security','Security center'], ['analytics','Analytics'], ['users','Users'], ['health','System health'], ['flags','Feature flags'], ['integrations','Payments & API keys'],['ai','AI / NVIDIA NIM'],['email','Email / SMTP'],['branding','Site icon'], ['plans','Plans']
];

function SeoEditor({onError}){
  const [data,setData]=useState(null);
  const [loading,setLoading]=useState(true);
  const [open,setOpen]=useState(null);
  const [draft,setDraft]=useState({});
  const [saving,setSaving]=useState(false);
  const [notice,setNotice]=useState('');

  const load=useCallback(()=>{
    setLoading(true);
    return api.get('/auth/platform/seo/')
      .then(next=>{setData(next);setLoading(false)})
      .catch(e=>{setLoading(false);onError(e.message||'Could not load search metadata.')});
  },[onError]);

  useEffect(()=>{load()},[load]);

  function startEditing(page){
    setOpen(page.slug);
    setNotice('');
    // Seeded from the row, not from the effective values. Writing the effective
    // fallback into the field on save would quietly promote a code default into
    // stored content, after which editing the fallback in a deploy stops having
    // any effect on that page - and nothing would say why.
    setDraft({
      meta_title:page.meta_title||'', meta_description:page.meta_description||'',
      og_image_url:page.og_image_url||'', noindex:!!page.noindex,
    });
  }

  async function save(slug){
    setSaving(true);setNotice('');
    try{
      const next=await api.patch(`/auth/platform/seo/${slug}/`,draft);
      setData(current=>({...current,pages:current.pages.map(p=>p.slug===slug?next:p)}));
      setOpen(null);
      setNotice(`Saved. ${slug} now reads "${next.effective.title}" to a crawler.`);
    }catch(e){onError(e.message||'Could not save the search metadata.')}
    finally{setSaving(false)}
  }

  async function useFallback(page){
    setDraft(current=>({...current,meta_title:'',meta_description:'',og_image_url:''}));
    if(page.meta_title||page.meta_description||page.og_image_url){
      try{
        await api.patch(`/auth/platform/seo/${page.slug}/`,{
          meta_title:'',meta_description:'',og_image_url:'',noindex:!!page.noindex,
        });
        const next=await api.get('/auth/platform/seo/');
        setData(next);
        setNotice(`${page.slug} is back to the built-in description.`);
      }catch(e){onError(e.message||'Could not clear the override.')}
    }
  }

  if(loading)return <div className="page-loading">Loading public pages...</div>;
  if(!data)return null;

  const titleOver=d=>((d.meta_title||'').trim().length>data.guidance_title_target);
  const descOver=d=>((d.meta_description||'').trim().length>data.guidance_description_target);
  const customized=p=>p.meta_title||p.meta_description||p.og_image_url||p.noindex;

  return <div>
    <div className="helper-callout" style={{display:'block'}}>
      <div><strong>These are the tags a crawler reads, not the page copy.</strong> Every public URL is a route in the React app, so they are all served one HTML shell; the tags are injected per route at request time. Page content is edited under <b>Marketing content</b>.</div>
      <div className="table-subline" style={{marginTop:'.4rem'}}>
        Sitemap: <a href={data.sitemap_url} target="_blank" rel="noreferrer">{data.sitemap_url}</a>
        {'  '}<span>Robots: <a href={data.robots_url} target="_blank" rel="noreferrer">{data.robots_url}</a></span>
      </div>
    </div>

    {notice&&<div className="alert alert-success">{notice}</div>}

    <div className="panel table-panel">
      <div className="panel-head">
        <div><h2>Public pages</h2><p>Seven indexable URLs. Blank fields fall back to the text shipped with the app.</p></div>
      </div>
      <div className="table-wrap"><table className="data-table modern-table">
        <thead><tr><th>Page</th><th>Title a crawler sees</th><th>Indexed</th><th>Source</th><th></th></tr></thead>
        <tbody>
          {data.pages.map(page=>{
            const isOpen=open===page.slug;
            return <>
              <tr key={page.slug}>
                <td><strong>{page.name}</strong><small className="table-subline">{page.path}</small></td>
                <td>
                  <div>{page.effective.title}</div>
                  <small className="table-subline">{page.effective.description}</small>
                  {page.noindex&&<small className="table-subline" style={{color:'var(--danger)'}}>noindex, nofollow &middot; removed from sitemap.xml</small>}
                </td>
                <td>{page.noindex?<span className="mini-status none">No</span>:<span className="mini-status active">Yes</span>}</td>
                <td>{customized(page)?<span className="mini-status active">Custom</span>:<span className="mini-status none">Built-in</span>}</td>
                <td><button className="btn btn-secondary compact" onClick={()=>isOpen?setOpen(null):startEditing(page)}>{isOpen?'Cancel':'Edit'}</button></td>
              </tr>
              {isOpen&&<tr key={`${page.slug}-edit`}><td colSpan="5">
                <div className="form-panel">
                  <div className="form-row">
                    <div>
                      <label>Meta title</label>
                      <input value={draft.meta_title||''} onChange={e=>setDraft({...draft,meta_title:e.target.value})} placeholder={page.fallbacks.title}/>
                      <small className="table-subline">
                        {`${(draft.meta_title||'').trim().length} characters`}
                        {titleOver(draft)&&` - over ${data.guidance_title_target}, so search results will truncate it`}
                        {!draft.meta_title?.trim()&&' - blank, so the built-in title is served'}
                      </small>
                    </div>
                    <div>
                      <label>Link preview image URL</label>
                      <input value={draft.og_image_url||''} onChange={e=>setDraft({...draft,og_image_url:e.target.value})} placeholder="https://..."/>
                      <small className="table-subline">Absolute URL. Blank shares without an image.</small>
                    </div>
                  </div>
                  <div>
                    <label>Meta description</label>
                    <textarea rows="3" value={draft.meta_description||''} onChange={e=>setDraft({...draft,meta_description:e.target.value})} placeholder={page.fallbacks.description}/>
                    <small className="table-subline">
                      {`${(draft.meta_description||'').trim().length} characters`}
                      {descOver(draft)&&` - over ${data.guidance_description_target}, so search results will truncate it`}
                      {!draft.meta_description?.trim()&&' - blank, so the built-in description is served'}
                    </small>
                  </div>
                  <label className="checkbox-label">
                    <input type="checkbox" checked={!!draft.noindex} onChange={e=>setDraft({...draft,noindex:e.target.checked})}/>
                    <span>Keep out of search engines<small className="table-subline">Adds <code>noindex, nofollow</code> and removes this URL from sitemap.xml.</small></span>
                  </label>
                  <div className="table-tools">
                    <button className="btn btn-primary compact" onClick={()=>save(page.slug)} disabled={saving}>{saving?'Saving...':'Save metadata'}</button>
                    <button className="btn btn-secondary compact" onClick={()=>useFallback(page)}>Reset to built-in</button>
                  </div>
                </div>
              </td></tr>}
            </>;
          })}
        </tbody>
      </table></div>
    </div>
  </div>;
}

function Plans({plans,onSave,onEdit}){
  const [editing,setEditing]=useState(null);
  return <div className="control-grid">
    {plans.map(p=> <div className="card" key={p.id}>
      <div className="section-head"><div><div className="eyebrow">Plan config</div><h2>{p.name} <small>({p.id})</small></h2><p>Price, limits and feature flags for the {p.name} plan.</p></div><span className={`admin-status ${p.active?'active':'pending'}`}>{p.active?'Active':'Inactive'}</span></div>
      {editing===p.id ? (
        <div className="plan-edit-form">
          <div className="form-row"><div><label>Name</label><input value={p.name} onChange={e=>{const np={...p,name:e.target.value};setEditing(np);onEdit(np);}}/></div><div><label>Monthly price</label><input type="number" min="0" step="0.01" value={p.monthly_price} onChange={e=>{const np={...p,monthly_price:Number(e.target.value)};setEditing(np);onEdit(np);}}/></div></div>
          <div className="form-row"><div><label>Annual price</label><input type="number" min="0" step="0.01" value={p.annual_price} onChange={e=>{const np={...p,annual_price:Number(e.target.value)};setEditing(np);onEdit(np);}}/></div><div><label>Order</label><input type="number" min="0" value={p.order} onChange={e=>{const np={...p,order:Number(e.target.value)};setEditing(np);onEdit(np);}}/></div></div>
          <div className="form-row"><div><label>Employee limit</label><input type="number" min="0" value={p.employee_limit??''} onChange={e=>{const v=e.target.value?Number(e.target.value):null;const np={...p,employee_limit:v};setEditing(np);onEdit(np);}}/></div><div><label>User limit</label><input type="number" min="0" value={p.user_limit??''} onChange={e=>{const v=e.target.value?Number(e.target.value):null;const np={...p,user_limit:v};setEditing(np);onEdit(np);}}/></div></div>
          <div className="form-row"><div><label className="checkbox-label"><input type="checkbox" checked={p.ai_enabled} onChange={e=>{const np={...p,ai_enabled:e.target.checked};setEditing(np);onEdit(np);}}/><strong>AI enabled</strong> (Professional+ only)</label></div><div><label className="checkbox-label"><input type="checkbox" checked={p.highlight} onChange={e=>{const np={...p,highlight:e.target.checked};setEditing(np);onEdit(np);}}/><strong>Highlight in UI</strong></label></div><div><label className="checkbox-label"><input type="checkbox" checked={p.active} onChange={e=>{const np={...p,active:e.target.checked};setEditing(np);onEdit(np);}}/><strong>Active</strong></label></div></div>
          <div className="modal-actions"><button className="btn btn-secondary" onClick={()=>setEditing(null)}>Cancel</button><button className="btn btn-primary" onClick={()=>{onSave(p);setEditing(null)}}>Save</button></div>
        </div>
      ) : (
        <div className="plan-view">
          <div className="plan-meta"><div><strong>Monthly:</strong> {p.monthly_price} | <strong>Annual:</strong> {p.annual_price}</div><div><strong>Employees:</strong> {p.employee_limit!==null?p.employee_limit:'Unlimited'} | <strong>Users:</strong> {p.user_limit!==null?p.user_limit:'Unlimited'}</div><div><strong>AI:</strong> {p.ai_enabled?'Enabled':'Disabled'} | <strong>Highlight:</strong> {p.highlight?'Yes':'No'} | <strong>Active:</strong> {p.active?'Yes':'No'} | <strong>Order:</strong> {p.order}</div></div>
          <div className="modal-actions"><button className="btn btn-primary" onClick={()=>setEditing(p)}>Edit plan</button></div>
        </div>
      )}
    </div>)}
  </div>
}

export default function PlatformAdmin(){
  const [tab,setTab]=useState('overview'); const [dashboard,setDashboard]=useState(null); const [data,setData]=useState({companies:[],users:[],subscriptions:[],usage:[],onboarding:[],support:[],notifications:[],audit:[],analytics:null,providers:[],transactions:[],security:null,health:null,flags:[],marketingPages:[],branding:null,plans:[]});
  const [search,setSearch]=useState(''); const [globalResults,setGlobalResults]=useState(null); const [company360,setCompany360]=useState(null); const [busy,setBusy]=useState(false); const [error,setError]=useState(''); const [message,setMessage]=useState(''); const [showCreate,setShowCreate]=useState(false); const [form,setForm]=useState(EMPTY); const [suspend,setSuspend]=useState(null); const [selectedCompany,setSelectedCompany]=useState(null); const [noticeForm,setNoticeForm]=useState({title:'',message:'',level:'info',company_id:''}); const [ticketForm,setTicketForm]=useState({company_id:'',subject:'',description:'',priority:'normal'}); const [deleteTarget,setDeleteTarget]=useState(null);
  const [planEdit,setPlanEdit]=useState(null);

  async function load(){setBusy(true); setError(''); try{
    const [d,c,u,s,usage,onboard,support,notifications,audit,analytics,providers,transactions,security,health,flags,marketingPages,aiConfig,branding,plans,emailConfig]=await Promise.all([
      api.get('/auth/platform/dashboard/'),api.get('/auth/platform/companies/'),api.get('/auth/platform/users/'),api.get('/auth/platform/subscriptions/'),api.get('/auth/platform/usage/'),api.get('/auth/platform/onboarding/'),api.get('/auth/platform/support/'),api.get('/auth/platform/notifications/'),api.get('/auth/platform/audit-logs/'),api.get('/auth/platform/analytics/'),api.get('/auth/platform/payment-providers/'),api.get('/auth/platform/payment-transactions/'),api.get('/auth/platform/security-center/'),api.get('/auth/platform/system-health/'),api.get('/auth/platform/feature-flags/'),api.get('/auth/platform/marketing-pages/'),api.get('/auth/platform/ai-config/').catch(()=>({configured:false,provider:'nvidia_nim'})),api.get('/auth/platform/site-branding/').catch(()=>null),api.get('/auth/platform/billing-plans/'),api.get('/auth/platform/email-config/').catch(()=>({configured:false,in_use:false,password_set:false}))
    ]); setDashboard(d); setData({companies:c,users:u,subscriptions:s,usage,onboarding:onboard,support,notifications,audit,analytics,providers,transactions,security,health,flags,marketingPages,aiConfig,branding,plans,emailConfig});
  }catch(e){setError(e.message||'Could not load the control center.')} finally{setBusy(false)}}
  useEffect(()=>{load()},[]);
  useEffect(()=>{const q=search.trim(); if(q.length<2){setGlobalResults(null);return;} const t=setTimeout(async()=>{try{setGlobalResults(await api.get(`/auth/platform/search/?q=${encodeURIComponent(q)}`))}catch{setGlobalResults(null)}},300); return()=>clearTimeout(t)},[search]);
  const notify=(m)=>{setMessage(m);setError('');setTimeout(()=>setMessage(''),3200)};
  async function action(path,body,msg,method){try{await (method==='patch'?api.patch(path,body||{}):api.post(path,body||{}));await load();notify(msg)}catch(e){setError(e.message||'Action failed')}}
  async function createCompany(e){e.preventDefault();setBusy(true);try{const r=await api.post('/auth/platform/companies/',form);setForm(EMPTY);setShowCreate(false);await load();notify(`Created ${r.company.name}.`)}catch(e){setError(e.message||'Could not create company')}finally{setBusy(false)}}
  async function updateCompany(c,field,value){try{await api.patch(`/auth/platform/companies/${c.id}/`,{[field]:value});await load();notify(`${c.name} updated.`)}catch(e){setError(e.message||'Update failed')}}
  async function createNotification(e){e.preventDefault();try{await api.post('/auth/platform/notifications/',{...noticeForm,company_id:noticeForm.company_id||null});setNoticeForm({title:'',message:'',level:'info',company_id:''});await load();notify('Notification published.')}catch(e){setError(e.message||'Could not publish notification')}}
  async function createTicket(e){e.preventDefault();try{await api.post('/auth/platform/support/',ticketForm);setTicketForm({company_id:'',subject:'',description:'',priority:'normal'});await load();notify('Support ticket created.')}catch(e){setError(e.message||'Could not create support ticket')}}
  async function updateTicket(id,payload){try{await api.patch(`/auth/platform/support/${id}/`,payload);await load();notify('Support ticket updated.')}catch(e){setError(e.message||'Could not update support ticket')}}
  async function deleteUser(u){
    setBusy(true);
    try{const r=await api.del(`/auth/platform/users/${u.id}/`,{confirm_username:u.username});setDeleteTarget(null);await load();notify(r.detail||`Deleted ${u.username}.`)}
    catch(e){/* The modal owns the 409 payload, so re-throw it there. */throw e}
    finally{setBusy(false)}}
  async function deactivateUser(u){setBusy(true);try{await api.patch(`/auth/platform/users/${u.id}/`,{is_active:false});setDeleteTarget(null);await load();notify(`${u.username} deactivated. Their access ends immediately.`)}catch(e){setError(e.message||'Could not deactivate.')}finally{setBusy(false)}}
  const companies=data.companies; const users=data.users;
  const filteredCompanies=useMemo(()=>{const q=search.toLowerCase().trim();return q?companies.filter(c=>`${c.name} ${c.email} ${c.country||''} ${c.owner_name||''}`.toLowerCase().includes(q)):companies},[companies,search]);
  const filteredUsers=useMemo(()=>{const q=search.toLowerCase().trim();return q?users.filter(u=>`${u.username} ${u.email} ${u.company_name||''} ${u.role}`.toLowerCase().includes(q)):users},[users,search]);
  const navGroups=[
    ['COMMAND CENTER',[['overview','Overview','grid'],['content','Marketing content','file'],['seo','Search (SEO)','search']]],
    ['TENANT OPERATIONS',[['companies','Companies','building'],['subscriptions','Billing','wallet'],['plans','Plans','file'],['usage','Usage','trend'],['onboarding','Onboarding','calendar']]],
    ['CUSTOMER SUCCESS',[['support','Support','file'],['notifications','Communications','bell']]],
    ['GOVERNANCE',[['users','Users','users'],['branding','Site icon','grid'],['audit','Audit & security','file'],['security','Security center','shield'],['analytics','Analytics','trend']]],
    ['OPERATIONS',[['payments','Transactions','wallet'],['support','Support','file'],['health','System health','activity'],['flags','Feature flags','settings']]],
    ['PLATFORM',[['integrations','Payments & API keys','settings'],['ai','AI / NVIDIA NIM','sparkles'],['email','Email / SMTP','mail']]],
  ];

  async function handlePlanSave(p){
    try{await api.put('/auth/platform/billing-plans/',p);await load();notify('Plan updated.')}catch(e){setError(e.message||'Could not update plan')}
  }

  return <div className="platform-admin-shell">
    <aside className="platform-admin-sidebar">
      <div className="platform-brand"><div className="platform-brand-mark">H</div><div><strong>HRCloudPay</strong><small>Platform Admin</small></div></div>
      <div className="platform-nav">{navGroups.map(([group,items])=><div key={group} className="platform-nav-group"><span>{group}</span>{items.map(([k,l,icon])=><button key={k} className={tab===k?'active':''} onClick={()=>{setTab(k);setSearch('')}}><Icon name={icon} size={16}/>{l}</button>)}</div>)}</div>
      <div className="platform-sidebar-footer"><div className="platform-secure"><span></span><div><strong>Platform secure</strong><small>Audit logging enabled</small></div></div><button onClick={()=>setTab('integrations')}><Icon name="settings" size={15}/> Platform settings</button><Link className="platform-exit" to="/dashboard"><Icon name="arrow" size={15}/> Back to workspace</Link></div>
    </aside>
    <main className="platform-admin-main">
      {/* Every public signup depends on this and nothing else in the console
          fails when it is missing: activation mail goes to the container log,
          the company registers, and the person waiting for the link has no way
          to know why it never arrived. A buyer who hits this on a fresh install
          would otherwise file a ticket instead of flipping one switch. */}
      {data?.emailConfig && !data.emailConfig.in_use && (
        <div className="alert alert-warning platform-mail-warning">
          <div><strong>This installation cannot send email.</strong> Company
          activation links, password resets and invitations go to the container log
          instead of the recipient, and a company registered through the public form
          can never be activated.</div>
          <button className="btn btn-primary compact" onClick={()=>{setTab('email');setSearch('')}}>Configure email</button>
        </div>
      )}
      <header className="platform-admin-topbar"><div className="platform-breadcrumb"><span>Platform</span><b>/</b><strong>{tabs.find(([k])=>k===tab)?.[1]||'Overview'}</strong></div><div className="platform-top-actions"><div className="platform-global-search-wrap"><div className="platform-global-search"><Icon name="search" size={16}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search companies, users, payments…"/></div>{globalResults&&<GlobalSearchResults results={globalResults} onNavigate={(t)=>{setTab(t);setSearch('')}} onCompany={(id)=>{setTab('companies');setSearch('');api.get(`/auth/platform/companies/${id}/360/`).then(setCompany360).catch(e=>{setCompany360(null);setError(e.message||'Could not load the company 360 view.')})}}/>}</div><button className="platform-icon-action" title="Refresh" onClick={load}><Icon name="clock" size={17}/></button><button className="btn btn-primary admin-create-btn" onClick={()=>setShowCreate(true)}><Icon name="plus" size={16}/> Add company</button></div></header>
      <div className="platform-admin-content">
        <div className="page-header platform-page-header"><div><div className="eyebrow">SaaS command center</div><h1>{tab==='overview'?'Platform overview':tabs.find(([k])=>k===tab)?.[1]}</h1><p className="page-subtitle">Run HRCloudPay as a product: tenants, revenue, access, security, support and integrations.</p></div><div className="platform-live"><span></span> Live control plane</div></div>
        {error&&<div className="alert alert-error">{error}</div>}{message&&<div className="alert alert-success">{message}</div>}
        {tab==='overview'&&<PlatformOverview dashboard={dashboard} companies={companies} usage={data.usage} subscriptions={data.subscriptions} support={data.support} audit={data.audit} onCreate={()=>setShowCreate(true)} onCompanies={()=>setTab('companies')} onBilling={()=>setTab('subscriptions')}/>} 
        {tab==='companies'&&<Companies companies={filteredCompanies} search={search} setSearch={setSearch} onSelect={setSelectedCompany} onToggle={(c)=>c.is_active?setSuspend(c):action(`/auth/platform/companies/${c.id}/activate/`,{},`${c.name} activated.`)} onPlan={updateCompany} onResend={(c)=>action(`/auth/platform/companies/${c.id}/resend-activation/`,{},`Activation link regenerated for ${c.name}.`)} />}
        {tab==='subscriptions'&&<Subscriptions items={data.subscriptions} companies={companies} onSave={async (s)=>{try{await api.post('/auth/platform/subscriptions/',s);await load();notify('Billing profile updated.')}catch(e){setError(e.message)}}}/>} 
        {tab==='usage'&&<Usage items={data.usage}/>} 
        {tab==='content'&&<MarketingContent
          payload={data.marketingPages}
          onSave={async(slug,payload,actionName)=>{await api.patch(`/auth/platform/marketing-pages/${slug}/`,{...payload,action:actionName||'save_draft'});await load();}}
          onCreate={async(payload)=>{const created=await api.post('/auth/platform/marketing-pages/',payload);await load();return created;}}
          onDelete={async(slug)=>{await api.del(`/auth/platform/marketing-pages/${slug}/`);await load();}}
          onNotice={notify}
        />} 
        {tab==='onboarding'&&<Onboarding items={data.onboarding}/>} 
        {tab==='support'&&<Support items={data.support} companies={companies} users={users.filter(u=>u.is_staff)} form={ticketForm} setForm={setTicketForm} onSubmit={createTicket} onUpdate={updateTicket}/>} 
        {tab==='notifications'&&<Notifications items={data.notifications} companies={companies} form={noticeForm} setForm={setNoticeForm} onSubmit={createNotification}/>} 
        {tab==='payments'&&<PaymentTransactions items={data.transactions}/>}
        {tab==='audit'&&<Audit items={data.audit}/>} 
        {tab==='security'&&<SecurityCenter data={data.security}/>} 
        {tab==='analytics'&&<Analytics data={data.analytics}/>} 
        {tab==='health'&&<SystemHealth data={data.health} onRefresh={load}/>}
        {tab==='flags'&&<FeatureFlags items={data.flags} onCreate={async(payload)=>{try{await api.post('/auth/platform/feature-flags/',payload);await load();notify('Feature flag created.')}catch(e){setError(e.message||'Could not create feature flag')}}} onSave={async(id,payload)=>{try{await api.patch(`/auth/platform/feature-flags/${id}/`,payload);await load();notify('Feature flag updated.')}catch(e){setError(e.message)}}}/>} 
        {tab==='branding'&&<SiteBranding state={data.branding} onChanged={async(s)=>{setData({...data,branding:s});notify('Site icon updated.')}} onError={setError}/>}
        {tab==='seo'&&<SeoEditor onError={setError}/>}
      {deleteTarget&&<DeleteUserModal user={deleteTarget} busy={busy} onDeactivate={()=>deactivateUser(deleteTarget)} onDeleted={()=>deleteUser(deleteTarget)} onClose={()=>setDeleteTarget(null)}/>}
      {tab==='ai'&&<AISettings config={data.aiConfig} onSave={async(payload)=>{try{const r=await api.post('/auth/platform/ai-config/',payload);setData({...data,aiConfig:r});notify('NVIDIA AI configuration saved.')}catch(e){setError(e.message||'Could not save AI configuration')}}} onTest={async()=>{try{const r=await api.post('/auth/platform/ai-config/test/',{});notify(r.message||'NVIDIA AI connection successful.')}catch(e){setError(e.message||'NVIDIA AI connection failed')}}}/>}
        {tab==='email'&&<EmailSettings config={data.emailConfig} onSave={async(payload)=>{try{const r=await api.post('/auth/platform/email-config/',payload);setData({...data,emailConfig:r});notify(r.in_use?'Email settings saved and now in use.':'Email settings saved. Not active yet.');}catch(e){setError(e.message||'Could not save email settings')}}} onTest={async(to)=>{try{const r=await api.post('/auth/platform/email-config/test/',to?{to}:{});notify(r.detail||'Test message sent.');}catch(e){setError(e.message||'Test send failed')}}}/>} 
        {tab==='integrations'&&<Integrations items={data.providers} onSave={async (payload)=>{try{await api.post('/auth/platform/payment-providers/',payload);await load();notify(`${payload.provider} payment settings saved.`)}catch(e){setError(e.message||'Could not save provider settings')}}} onToggle={async (provider,enabled)=>{try{await api.post(`/auth/platform/payment-providers/${provider}/toggle/`,{enabled});await load();notify(`${provider} ${enabled?'enabled':'disabled'}.`)}catch(e){setError(e.message||'Could not change provider state')}}}/>}
        {tab==='users'&&<Users items={filteredUsers} search={search} setSearch={setSearch} onDelete={setDeleteTarget} onToggle={(u)=>action(`/auth/platform/users/${u.id}/`,{is_active:!u.is_active},`${u.username} is now ${u.is_active?'inactive':'active'}.`,'patch')}/>} 
      {tab==='plans'&&<Plans plans={data.plans} onSave={handlePlanSave} onEdit={setPlanEdit}/>} 
      </div>
    </main>

    {showCreate&&<div className="admin-modal-backdrop"><div className="admin-modal"><div className="modal-head"><div><h2>Add company</h2><p>Create a tenant and its first owner account.</p></div><button className="icon-btn" onClick={()=>setShowCreate(false)}>×</button></div><form onSubmit={createCompany}><div className="form-row"><div><label>Company name</label><input required value={form.company_name} onChange={e=>setForm({...form,company_name:e.target.value})}/></div><div><label>Country</label><input value={form.country} onChange={e=>setForm({...form,country:e.target.value})}/></div></div><div className="form-row"><div><label>Company email</label><input required type="email" value={form.company_email} onChange={e=>setForm({...form,company_email:e.target.value})}/></div><div><label>Phone</label><input value={form.phone} onChange={e=>setForm({...form,phone:e.target.value})}/></div></div><div className="form-row"><div><label>Plan</label><select value={form.plan} onChange={e=>setForm({...form,plan:e.target.value})}>{Object.entries(PLANS).map(([v,l])=><option value={v} key={v}>{l}</option>)}</select></div><div><label>Owner username</label><input required value={form.owner_username} onChange={e=>setForm({...form,owner_username:e.target.value})}/></div></div><div className="form-row"><div><label>Owner email</label><input required type="email" value={form.owner_email} onChange={e=>setForm({...form,owner_email:e.target.value})}/></div><div><label>Temporary password</label><input required type="password" value={form.owner_password} onChange={e=>setForm({...form,owner_password:e.target.value})}/></div></div><label className="checkbox-label"><input type="checkbox" checked={form.activate_immediately} onChange={e=>setForm({...form,activate_immediately:e.target.checked})}/> Activate immediately</label><label className="checkbox-label"><input type="checkbox" checked={form.payroll_configured} onChange={e=>setForm({...form,payroll_configured:e.target.checked})}/> Mark payroll setup complete</label><div className="modal-actions"><button type="button" className="btn btn-secondary" onClick={()=>setShowCreate(false)}>Cancel</button><button className="btn btn-primary admin-submit" disabled={busy}>{busy?'Creating…':'Create company'}</button></div></form></div></div>}
    {selectedCompany&&<CompanyDrawer company={selectedCompany} usage={data.usage.find(x=>x.company_id===selectedCompany.id)} subscription={data.subscriptions.find(x=>x.company_id===selectedCompany.id)} onClose={()=>setSelectedCompany(null)} onBilling={()=>{setSelectedCompany(null);setTab('subscriptions')}} onOpen360={()=>api.get(`/auth/platform/companies/${selectedCompany.id}/360/`).then(setCompany360).catch(e=>setError(e.message))}/>}
    {company360&&<Company360Drawer data={company360} onClose={()=>setCompany360(null)}/>}
    {suspend&&<div className="admin-modal-backdrop"><div className="admin-modal compact"><div className="modal-head"><div><h2>Suspend {suspend.name}</h2><p>Record why the tenant is being suspended. This creates an audit event.</p></div><button className="icon-btn" onClick={()=>setSuspend(null)}>×</button></div><label>Reason</label><input id="sreason" defaultValue="Administrative suspension"/><label>Notes</label><textarea id="snotes" rows="4" placeholder="Optional internal notes"/><div className="modal-actions"><button className="btn btn-secondary" onClick={()=>setSuspend(null)}>Cancel</button><button className="btn btn-danger" onClick={async()=>{const reason=document.getElementById('sreason').value;const notes=document.getElementById('snotes').value;await action(`/auth/platform/companies/${suspend.id}/suspend/`,{reason,notes},`${suspend.name} suspended.`);setSuspend(null)}}>Suspend company</button></div></div></div>}
  </div>
}

function PlatformOverview({dashboard,companies,usage,subscriptions,support,audit,onCreate,onCompanies,onBilling}){
  if(!dashboard)return <div className="card page-loading">Loading platform metrics…</div>;
  const avg=usage.length?Math.round(usage.reduce((a,x)=>a+(x.employee_limit?Math.min(x.employees/x.employee_limit*100,100):0),0)/usage.length):0;
  const activeSubs=(subscriptions||[]).filter(x=>x.status==='active').length;
  const pastDue=(subscriptions||[]).filter(x=>['past_due','grace'].includes(x.status)).length;
  const urgentTickets=(support||[]).filter(x=>x.priority==='urgent'&&x.status!=='resolved').length;
  const recentAudit=(audit||[]).slice(0,6);
  return <><div className="admin-stats platform-kpis">
    <div className="admin-stat"><span className="admin-stat-icon"><Icon name="building"/></span><div><strong>{dashboard.companies_total}</strong><span>Total tenants</span><small>{dashboard.companies_active} active</small></div></div>
    <div className="admin-stat"><span className="admin-stat-icon"><Icon name="wallet"/></span><div><strong>{dashboard.revenue_monthly||0}</strong><span>Monthly recurring value</span><small>Current subscription base</small></div></div>
    <div className="admin-stat"><span className="admin-stat-icon"><Icon name="trend"/></span><div><strong>{activeSubs}</strong><span>Active subscriptions</span><small>{pastDue} need attention</small></div></div>
    <div className="admin-stat"><span className="admin-stat-icon"><Icon name="users"/></span><div><strong>{dashboard.users_total}</strong><span>Platform users</span><small>{dashboard.users_active} active</small></div></div>
    <div className="admin-stat"><span className="admin-stat-icon"><Icon name="calendar"/></span><div><strong>{dashboard.companies_payroll_ready}</strong><span>Payroll ready</span><small>of {dashboard.companies_total} tenants</small></div></div>
    <div className="admin-stat"><span className="admin-stat-icon"><Icon name="file"/></span><div><strong>{dashboard.open_tickets}</strong><span>Open support</span><small>{urgentTickets} urgent</small></div></div>
    <div className="admin-stat"><span className="admin-stat-icon"><Icon name="settings"/></span><div><strong>{dashboard.payment_providers_enabled}</strong><span>Payment providers</span><small>Enabled integrations</small></div></div>
  </div>
  <div className="admin-quick-actions"><button onClick={onCreate}><Icon name="plus" size={17}/><div><strong>Create tenant</strong><small>Provision a new company</small></div></button><button onClick={onCompanies}><Icon name="building" size={17}/><div><strong>Manage tenants</strong><small>Search, suspend and change plans</small></div></button><button onClick={onBilling}><Icon name="wallet" size={17}/><div><strong>Billing operations</strong><small>Trials, grace and subscriptions</small></div></button></div>
  <div className="platform-overview-grid">
    <div className="card"><div className="section-head"><div><h2>Tenant health</h2><p>Operational state across your customer base.</p></div><button className="btn btn-secondary btn-sm" onClick={onCompanies}>View all</button></div><div className="health-list">{companies.slice(0,7).map(c=><div className="health-row" key={c.id}><div className="company-avatar">{c.name.slice(0,1).toUpperCase()}</div><div className="grow"><strong>{c.name}</strong><small>{c.owner_name||'No owner'} · {c.country||'Country not set'}</small></div><span className={`admin-status ${c.is_active?'active':'pending'}`}>{c.is_active?'Active':'Pending'}</span><span className={`health-dot ${c.payroll_configured?'good':'warn'}`}>{c.payroll_configured?'Payroll ready':'Setup needed'}</span></div>)}</div></div>
    <div className="card"><div className="section-head"><div><h2>Plan distribution</h2><p>Portfolio mix by current plan.</p></div></div>{Object.entries(dashboard.plans).map(([p,n])=><div className="meter-row" key={p}><span>{PLANS[p]||p}</span><strong>{n}</strong><div><i style={{width:`${companies.length?Math.max(n/companies.length*100,n?5:0):0}%`}}/></div></div>)}<div className="platform-health-summary"><span className="health-dot good">● Platform operational</span><span>{avg}% avg employee capacity used</span></div></div>
  </div>
  <div className="platform-overview-grid lower">
    <div className="card"><div className="section-head"><div><h2>Recent platform activity</h2><p>High-value administrative actions.</p></div></div><div className="audit-list">{recentAudit.map(x=><div className="audit-row" key={x.id}><span className="audit-action">{x.action}</span><div className="grow"><strong>{x.message}</strong><small>{x.actor} · {x.company||'Platform'} · {new Date(x.created_at).toLocaleString()}</small></div></div>)}{!recentAudit.length&&<div className="empty-row">No platform activity yet.</div>}</div></div>
    <div className="card"><div className="section-head"><div><h2>Needs attention</h2><p>Items your operations team should review.</p></div></div><div className="attention-list"><div><strong>{dashboard.companies_pending}</strong><span>Pending tenant activations</span></div><div><strong>{pastDue}</strong><span>Past-due / grace subscriptions</span></div><div><strong>{urgentTickets}</strong><span>Urgent support tickets</span></div><div><strong>{dashboard.companies_total-dashboard.companies_payroll_ready}</strong><span>Tenants without payroll setup</span></div></div></div>
  </div></> }

function CompanyDrawer({company,usage,subscription,onClose,onBilling,onOpen360}){return <div className="admin-drawer-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}><aside className="admin-drawer"><div className="drawer-head"><div><div className="company-avatar drawer-avatar">{company.name.slice(0,1).toUpperCase()}</div></div><div className="grow"><h2>{company.name}</h2><p>{company.email}</p></div><button className="icon-btn" onClick={onClose}>×</button></div><div className="drawer-status"><span className={`admin-status ${company.is_active?'active':'pending'}`}>{company.is_active?'Active':'Pending'}</span><span className="role-pill">{PLANS[company.plan]}</span></div><div className="drawer-grid"><div><small>Country</small><strong>{company.country||'—'}</strong></div><div><small>Owner</small><strong>{company.owner_name||'—'}</strong></div><div><small>Employees</small><strong>{usage?`${usage.employees}/${usage.employee_limit??'∞'}`:'—'}</strong></div><div><small>Active users</small><strong>{usage?.active_users??company.user_count??'—'}</strong></div></div><div className="drawer-section"><span>Subscription</span><div className="drawer-card"><strong>{subscription?PLANS[subscription.plan]:'No subscription'}</strong><small>{subscription?`${subscription.status} · ${subscription.provider||'manual'} · ${subscription.currency||'USD'} ${subscription.monthly_price||0}`:'Billing profile not found'}</small></div></div><div className="drawer-section"><span>Operations</span><div className="drawer-checks"><span className={company.payroll_configured?'done':''}>{company.payroll_configured?'✓':'○'} Payroll configured</span><span className={company.activation_token?'':'done'}>{company.is_active?'✓':'○'} Account active</span></div></div><div className="drawer-actions"><button className="btn btn-primary" onClick={onOpen360}>Open Company 360</button><button className="btn btn-secondary" onClick={onBilling}>Open billing</button><button className="btn btn-secondary" onClick={onClose}>Close</button></div></aside></div>}

function Companies({companies,search,setSearch,onToggle,onPlan,onResend,onSelect}){return <div className="card"><div className="section-head"><div><h2>Companies</h2><p>Every HRCloudPay tenant, its plan and operational status.</p></div><input className="admin-search" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search company, owner or country…"/></div><div className="table-wrap"><table className="data-table admin-table"><thead><tr><th>Company</th><th>Status</th><th>Plan</th><th>Employees</th><th>Users</th><th>Payroll</th><th>Actions</th></tr></thead><tbody>{companies.map(c=><tr key={c.id}><td><button className="table-link" onClick={()=>onSelect(c)}><strong>{c.name}</strong><small>{c.email}</small></button></td><td><span className={`admin-status ${c.is_active?'active':'pending'}`}>{c.is_active?'Active':'Pending'}</span></td><td><select className="inline-select" value={c.plan} onChange={e=>onPlan(c,'plan',e.target.value)}>{Object.entries(PLANS).map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></td><td>{c.employee_count}/{c.employee_limit??'∞'}</td><td>{c.user_count}</td><td>{c.payroll_configured?'Ready':'Needs setup'}</td><td><div className="row-actions"><button className="btn btn-secondary btn-sm" onClick={()=>onToggle(c)}>{c.is_active?'Suspend':'Activate'}</button>{!c.is_active&&<button className="btn btn-secondary btn-sm" onClick={()=>onResend(c)}>Resend</button>}</div></td></tr>)}</tbody></table></div></div>}

function Subscriptions({items,onSave}){return <div className="card"><div className="section-head"><div><h2>Billing & subscriptions</h2><p>Control plans, trials, payment state, grace periods and billing providers.</p></div></div><div className="table-wrap"><table className="data-table admin-table"><thead><tr><th>Company</th><th>Plan</th><th>Status</th><th>Provider</th><th>Cycle</th><th>Price</th><th>Trial / grace</th><th>Actions</th></tr></thead><tbody>{items.map(s=><tr key={s.id}><td><strong>{s.company_name}</strong></td><td>{PLANS[s.plan]||s.plan}</td><td><select className="inline-select" value={s.status} onChange={e=>onSave({company_id:s.company_id,status:e.target.value})}>{['trial','active','past_due','cancelled'].map(x=><option key={x}>{x}</option>)}</select></td><td><select className="inline-select" value={s.provider||'manual'} onChange={e=>onSave({company_id:s.company_id,provider:e.target.value})}><option value="manual">Manual</option><option value="flutterwave">Flutterwave</option><option value="paystack">Paystack</option><option value="stripe">Stripe</option><option value="paddle">Paddle</option></select></td><td><select className="inline-select" value={s.billing_cycle} onChange={e=>onSave({company_id:s.company_id,billing_cycle:e.target.value})}><option>monthly</option><option>annual</option></select></td><td>{s.currency} {s.monthly_price}</td><td><small>{s.trial_ends_at?`Trial: ${new Date(s.trial_ends_at).toLocaleDateString()}`:'No trial date'}<br/>{s.grace_ends_at?`Grace: ${new Date(s.grace_ends_at).toLocaleDateString()}`:'No grace'}</small></td><td><div className="row-actions"><button className="btn btn-secondary btn-sm" onClick={()=>onSave({company_id:s.company_id,status:'trial',trial_days:14})}>14d trial</button><button className="btn btn-secondary btn-sm" onClick={()=>onSave({company_id:s.company_id,grace_days:7})}>7d grace</button></div></td></tr>)}</tbody></table></div>{!items.length&&<div className="empty-row">No subscription records yet.</div>}</div>}
function Usage({items}){return <div className="card"><div className="section-head"><div><h2>Usage & limits</h2><p>Monitor plan capacity before tenants hit limits.</p></div></div>{items.map(x=><div className="usage-card" key={x.company_id}><div className="usage-head"><div><strong>{x.company}</strong><small>{PLANS[x.plan]}</small></div><span>{x.employees}/{x.employee_limit??'∞'} employees</span></div>{x.employee_limit?<div className="usage-bar"><i style={{width:`${Math.min(x.employee_utilization_percent,100)}%`}}/></div>:<div className="usage-unlimited">Unlimited employee capacity</div>}<div className="usage-meta"><span>{x.active_users} active users</span><span>{x.departments} departments</span><span>{x.payroll_configured?'Payroll configured':'Payroll setup incomplete'}</span></div></div>)}</div>}
function Onboarding({items}){return <div className="card"><div className="section-head"><div><h2>Company onboarding</h2><p>See where each tenant is in the activation journey.</p></div></div><div className="onboard-grid">{items.map(x=><div className="onboard-card" key={x.company_id}><div className="onboard-top"><strong>{x.company_name}</strong><span>{x.completion_percent}%</span></div><div className="usage-bar"><i style={{width:`${x.completion_percent}%`}}/></div><div className="check-list">{Object.entries(x.checks).map(([k,v])=><span className={v?'done':''} key={k}>{v?'✓':'○'} {k.replaceAll('_',' ')}</span>)}</div></div>)}</div></div>}
function Support({items,companies,users,form,setForm,onSubmit,onUpdate}){return <div className="control-grid"><div className="card"><div className="section-head"><div><h2>New support ticket</h2><p>Create an internal support case for a customer.</p></div></div><form onSubmit={onSubmit}><label>Company</label><select required value={form.company_id} onChange={e=>setForm({...form,company_id:e.target.value})}><option value="">Select company</option>{companies.map(c=><option value={c.id} key={c.id}>{c.name}</option>)}</select><label>Subject</label><input required value={form.subject} onChange={e=>setForm({...form,subject:e.target.value})}/><label>Priority</label><select value={form.priority} onChange={e=>setForm({...form,priority:e.target.value})}>{['low','normal','high','urgent'].map(x=><option key={x}>{x}</option>)}</select><label>Description</label><textarea required rows="5" value={form.description} onChange={e=>setForm({...form,description:e.target.value})}/><button className="btn btn-primary">Create ticket</button></form></div><div className="card"><div className="section-head"><div><h2>Support queue</h2><p>{items.length} recent tickets.</p></div></div><div className="ticket-list">{items.map(t=><div className="ticket-row" key={t.id}><div className="grow"><strong>{t.subject}</strong><small>{t.company_name} · {new Date(t.created_at).toLocaleString()}</small></div><select className="inline-select" value={t.status} onChange={e=>onUpdate(t.id,{status:e.target.value})}><option value="open">Open</option><option value="in_progress">In progress</option><option value="waiting">Waiting</option><option value="resolved">Resolved</option></select><select className="inline-select" value={t.priority} onChange={e=>onUpdate(t.id,{priority:e.target.value})}>{['low','normal','high','urgent'].map(x=><option key={x}>{x}</option>)}</select><select className="inline-select" value={t.assigned_to||''} onChange={e=>onUpdate(t.id,{assigned_to:e.target.value||null})}><option value="">Unassigned</option>{users.map(u=><option value={u.id} key={u.id}>{u.username}</option>)}</select></div>)}</div></div></div>}
function Notifications({items,companies,form,setForm,onSubmit}){return <div className="control-grid"><div className="card"><div className="section-head"><div><h2>Broadcast notification</h2><p>Prepare platform messages for every tenant or one company.</p></div></div><form onSubmit={onSubmit}><label>Audience</label><select value={form.company_id} onChange={e=>setForm({...form,company_id:e.target.value})}><option value="">All companies</option>{companies.map(c=><option value={c.id} key={c.id}>{c.name}</option>)}</select><label>Level</label><select value={form.level} onChange={e=>setForm({...form,level:e.target.value})}>{['info','success','warning','danger'].map(x=><option key={x}>{x}</option>)}</select><label>Title</label><input required value={form.title} onChange={e=>setForm({...form,title:e.target.value})}/><label>Message</label><textarea required rows="5" value={form.message} onChange={e=>setForm({...form,message:e.target.value})}/><button className="btn btn-primary">Publish notification</button></form></div><div className="card"><div className="section-head"><div><h2>Recent notifications</h2></div></div>{items.map(n=><div className="notification-row" key={n.id}><span className={`notice-level ${n.level}`}>{n.level}</span><div className="grow"><strong>{n.title}</strong><small>{n.company_name} · {new Date(n.created_at).toLocaleString()}</small><p>{n.message}</p></div></div>)}</div></div>}
function Audit({items}){return <div className="card"><div className="section-head"><div><h2>Audit log</h2><p>Platform actions are recorded with actor, tenant and timestamp.</p></div></div><div className="audit-list">{items.map(x=><div className="audit-row" key={x.id}><span className="audit-action">{x.action}</span><div className="grow"><strong>{x.message}</strong><small>{x.actor} · {x.company} · {new Date(x.created_at).toLocaleString()}</small></div></div>)}</div></div>}
function Analytics({data}){if(!data)return <div className="card page-loading">Loading analytics…</div>;return <><div className="admin-stats"><div className="admin-stat"><div><strong>{data.active_rate}%</strong><span>Activation rate</span></div></div><div className="admin-stat"><div><strong>{data.payroll_ready_rate}%</strong><span>Payroll-ready</span></div></div><div className="admin-stat"><div><strong>{data.employees_total}</strong><span>Total employees</span></div></div></div><div className="card"><div className="section-head"><div><h2>Platform analytics</h2><p>Current portfolio health and plan distribution.</p></div></div>{Object.entries(data.plan_distribution||{}).map(([p,n])=><div className="meter-row" key={p}><span>{PLANS[p]||p}</span><strong>{n}</strong><div><i style={{width:`${Math.max(n/Math.max(Object.values(data.plan_distribution).reduce((a,b)=>a+b,0),1)*100, n?5:0)}%`}}/></div></div>)}</div></>}
function Users({items,search,setSearch,onToggle,onDelete}){return <div className="card"><div className="section-head"><div><h2>Platform users</h2><p>Global user inventory and platform access.</p></div><input className="admin-search" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search users…"/></div><div className="table-wrap"><table className="data-table admin-table"><thead><tr><th>User</th><th>Company</th><th>Role</th><th>Access</th><th>Status</th><th/></tr></thead><tbody>{items.map(u=><tr key={u.id}><td><strong>{u.username}</strong><small>{u.email}</small></td><td>{u.company_name||'Platform'}</td><td><span className="role-pill">{u.role.replaceAll('_',' ')}</span></td><td>{u.is_superuser?'Superuser':u.is_staff?'Staff admin':'Tenant user'}</td><td><span className={`admin-status ${u.is_active?'active':'pending'}`}>{u.is_active?'Active':'Inactive'}</span></td><td><div className="user-row-actions"><button className="btn btn-secondary btn-sm" onClick={()=>onToggle(u)}>{u.is_active?'Deactivate':'Activate'}</button><button className="btn btn-danger btn-sm" onClick={()=>onDelete(u)}>Delete</button></div></td></tr>)}</tbody></table></div></div>}



function DeleteUserModal({user,busy,onClose,onDeleted,onDeactivate}){
  // A hard delete is irreversible and is not recoverable from any backup taken
  // before it, so it needs the administrator to retype the exact username.
  // Matching is case-sensitive on purpose - accepting a near-miss would defeat
  // the point of the confirmation.
  const [typed,setTyped]=useState('');
  const [error,setError]=useState('');
  const [blockers,setBlockers]=useState(null);
  const matches=typed===user.username;
  async function submit(){
    setError(''); setBlockers(null);
    try{await onDeleted()}
    catch(e){setBlockers(e.data?.blockers||null); setError(e.message||'Could not delete this user.')}
  }
  return <div className="modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget&&!busy)onClose()}}>
    <div className="modal-card" role="dialog" aria-modal="true">
      <div className="modal-head"><h2>Delete {user.username}</h2></div>
      <p>This permanently removes the login, its sessions and its MFA devices. It cannot be undone.</p>
      <p><strong>Usually you want Deactivate instead.</strong> Deactivating ends the person's access immediately and keeps every payroll approval, document and audit entry they are named on. Deleting is for accounts that should never have existed, such as a test account or a mistaken signup.</p>
      {blockers&&<div className="alert alert-error">
        <strong>This account cannot be deleted.</strong>
        <ul className="delete-blockers">{blockers.map(b=><li key={`${b.model}.${b.field}`}><strong>{b.count} {b.what}</strong><br/>{b.why}</li>)}</ul>
      </div>}
      {!blockers&&<>
        <label>Type <code>{user.username}</code> to confirm</label>
        <input value={typed} onChange={e=>setTyped(e.target.value)} autoComplete="off" spellCheck="false"/>
        {error&&<div className="alert alert-error">{error}</div>}
      </>}
      {error&&blockers&&<div className="alert alert-warning">{error}</div>}
      <div className="modal-actions">
        <button className="btn btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
        {blockers
          ?<button className="btn btn-primary" onClick={onDeactivate} disabled={busy}>{user.is_active?'Deactivate instead':'Deactivated already'}</button>
          :<button className="btn btn-danger" onClick={submit} disabled={!matches||busy}>Delete permanently</button>}
      </div>
    </div>
  </div>
}

function SiteBranding({state,onChanged,onError}){
  const [busy,setBusy]=useState(false);
  // Cache-busting key, bumped after every successful upload. The icon routes
  // send no-cache with an ETag, which a conforming browser revalidates - but
  // browsers and corporate proxies are inconsistent about favicons in
  // particular, and an administrator who cannot see their own change will
  // reasonably conclude the upload failed.
  const [stamp,setStamp]=useState(0);
  const faviconInput=useRef(null); const appleInput=useRef(null);
  const bust=(url)=>stamp?`${url}?v=${stamp}`:url;

  async function upload(field,file,input){
    if(!file)return;
    setBusy(true);
    try{
      const fd=new FormData(); fd.append(field,file);
      const next=await api.upload('/auth/platform/site-branding/',fd);
      input.current.value='';
      setStamp(Date.now());
      onChanged(next);
    }catch(e){onError(e.message||'Could not upload the icon.')}
    finally{setBusy(false)}
  }
  async function remove(field){
    setBusy(true);
    try{
      const next=await api.del(`/auth/platform/site-branding/?field=${field}`);
      setStamp(Date.now());
      onChanged(next);
    }catch(e){onError(e.message||'Could not remove the icon.')}
    finally{setBusy(false)}
  }
  const limits=state?.limits||{};
  return <div className="control-grid">
    <div className="card">
      <div className="section-head"><div><div className="eyebrow">Site identity</div><h2>Browser tab icon</h2><p>Shown beside the page title in a browser tab. Serves to every visitor, signed in or not, so it applies to the whole site rather than to any one company.</p></div><span className={`admin-status ${state?.has_favicon?'active':'pending'}`}>{state?.has_favicon?'Set':'Not set'}</span></div>
      <div className="icon-preview-row">
        <div className="icon-preview-favicon">{state?.has_favicon&&<img src={bust(state.favicon_url)} alt="Current browser tab icon"/>}</div>
        <div className="grow">
          <strong>{state?.has_favicon?'Favicon in use':'No favicon uploaded'}</strong>
          <small>Browsers fall back to their own default icon until one is set.</small>
          {state?.updated_at&&<small>Last changed {new Date(state.updated_at).toLocaleString()}{state.updated_by?` by ${state.updated_by}`:''}</small>}
        </div>
      </div>
      <input ref={faviconInput} type="file" accept="image/png,image/jpeg,image/webp,image/gif,image/x-icon" disabled={busy} onChange={e=>upload('favicon',e.target.files?.[0],faviconInput)}/>
      <div className="modal-actions">
        <button className="btn btn-primary" onClick={()=>faviconInput.current?.click()} disabled={busy}>{busy?'Working…':'Upload favicon'}</button>
        {state?.has_favicon&&<button className="btn btn-danger" onClick={()=>remove('favicon')} disabled={busy}>Remove</button>}
      </div>
    </div>
    <div className="card">
      <div className="section-head"><div><h2>iOS home-screen icon</h2><p>Used when someone adds the site to an iPhone or iPad home screen. Rendered at 180×180.</p></div><span className={`admin-status ${state?.has_apple_touch_icon?'active':'pending'}`}>{state?.has_apple_touch_icon?'Set':'Not set'}</span></div>
      <div className="icon-preview-row">
        <div className="icon-preview-apple">{state?.has_apple_touch_icon&&<img src={bust(state.apple_touch_icon_url)} alt="Current iOS home-screen icon"/>}</div>
        <div className="grow">
          <strong>{state?.has_apple_touch_icon?'Home-screen icon in use':'No home-screen icon uploaded'}</strong>
          <small>A wide or tall image is padded onto a square rather than stretched.</small>
        </div>
      </div>
      <input ref={appleInput} type="file" accept="image/png,image/jpeg,image/webp" disabled={busy} onChange={e=>upload('apple_touch_icon',e.target.files?.[0],appleInput)}/>
      <div className="modal-actions">
        <button className="btn btn-primary" onClick={()=>appleInput.current?.click()} disabled={busy}>{busy?'Working…':'Upload home-screen icon'}</button>
        {state?.has_apple_touch_icon&&<button className="btn btn-danger" onClick={()=>remove('apple_touch_icon')} disabled={busy}>Remove</button>}
      </div>
    </div>
    <div className="card">
      <div className="section-head"><div><h2>How these are handled</h2><p>Worth knowing before uploading anything.</p></div></div>
      <div className="drawer-mini-list">
        <div><strong>Accepted</strong><small>{limits.accepted_formats||'PNG, JPEG, WebP, GIF or ICO'}</small></div>
        <div><strong>Size limit</strong><small>{limits.max_upload_bytes?`${Math.round(limits.max_upload_bytes/1024)} KB`:`${Math.round(512/1)} KB`} per file</small></div>
        <div><strong>SVG is refused</strong><small>An SVG can carry a &lt;script&gt; tag, and this icon is served to every visitor in the site's own origin. Raster images render identically at these sizes.</small></div>
        <div><strong>Re-encoded on upload and again on every request</strong><small>What you see is regenerated PNG. Any embedded metadata is discarded and a file that is both a valid image and valid markup cannot be served.</small></div>
        <div><strong>No rebuild needed</strong><small>The icon path is fixed in the page markup, so replacing the file takes effect on the next page load.</small></div>
      </div>
    </div>
  </div>
}

function AISettings({config,onSave,onTest}){
  const [form,setForm]=useState(null);
  useEffect(()=>{if(config)setForm({...config,api_key:''})},[config]);
  if(!form)return <div className="card page-loading">Loading NVIDIA AI configuration…</div>;
  const set=(key,value)=>setForm({...form,[key]:value});
  return <div className="control-grid">
    <div className="card">
      <div className="section-head"><div><div className="eyebrow">Platform AI</div><h2>NVIDIA NIM configuration</h2><p>All HRCloudPay AI credentials and model settings are controlled by the site administrator. Tenant users never see the API key.</p></div><span className={`admin-status ${form.configured?'active':'pending'}`}>{form.configured?'Configured':'Not configured'}</span></div>
      <div className="form-row"><div><label>Provider</label><input value="NVIDIA NIM" disabled/></div><div><label>Display name</label><input value={form.display_name||''} onChange={e=>set('display_name',e.target.value)}/></div></div>
      <label>API key</label><input type="password" value={form.api_key||''} onChange={e=>set('api_key',e.target.value)} placeholder={form.api_key_set?'Leave blank to keep current key':'Paste NVIDIA API key'}/>
      <div className="form-row"><div><label>Chat API URL</label><input value={form.chat_api_url||''} onChange={e=>set('chat_api_url',e.target.value)}/></div><div><label>Embeddings API URL</label><input value={form.embeddings_api_url||''} onChange={e=>set('embeddings_api_url',e.target.value)}/></div></div>
      <div className="form-row"><div><label>Chat model</label><input value={form.chat_model||''} onChange={e=>set('chat_model',e.target.value)}/></div><div><label>Embedding model</label><input value={form.embedding_model||''} onChange={e=>set('embedding_model',e.target.value)}/></div></div>
      <div className="form-row"><div><label>Temperature</label><input type="number" min="0" max="2" step="0.1" value={form.temperature??0.3} onChange={e=>set('temperature',Number(e.target.value))}/></div><div><label>Max tokens</label><input type="number" min="1" value={form.max_tokens??1200} onChange={e=>set('max_tokens',Number(e.target.value))}/></div></div>
      <div className="form-row"><div><label>Request timeout (seconds)</label><input type="number" min="5" value={form.request_timeout_seconds??90} onChange={e=>set('request_timeout_seconds',Number(e.target.value))}/></div><div><label className="checkbox-label"><input type="checkbox" checked={Boolean(form.is_active)} onChange={e=>set('is_active',e.target.checked)}/> Enable NVIDIA AI for HRCloudPay</label></div></div>
      <div className="modal-actions"><button className="btn btn-secondary" onClick={onTest} disabled={!form.configured && !form.api_key}>Test connection</button><button className="btn btn-primary" onClick={()=>onSave(form)}>Save AI configuration</button></div>
    </div>
    <div className="card"><div className="section-head"><div><h2>Security</h2><p>How HRCloudPay handles the AI provider configuration.</p></div></div><div className="drawer-mini-list"><div><strong>API key</strong><small>Encrypted at rest with the Django SECRET_KEY. Never returned to the frontend.</small></div><div><strong>Access</strong><small>Only platform superusers can view or change these settings.</small></div><div><strong>Tenant isolation</strong><small>Company users cannot change the provider, model, endpoint, or credentials.</small></div><div><strong>Audit</strong><small>Configuration changes and connection tests are recorded in the platform audit log.</small></div></div></div>
  </div>
}

function EmailSettings({config,onSave,onTest}){
  const [form,setForm]=useState(null);
  const [to,setTo]=useState('');
  useEffect(()=>{if(config)setForm({...config,password:''})},[config]);
  if(!form)return <div className="card page-loading">Loading email configuration...</div>;
  const set=(key,value)=>setForm({...form,[key]:value});
  // smtplib cannot negotiate STARTTLS on a socket that is already TLS, so the
  // two are exclusive. Enforced here rather than only on the server so the admin
  // is not offered a combination that is guaranteed to fail.
  const setTls=(on)=>setForm({...form,use_tls:on,use_ssl:on?false:form.use_ssl});
  const setSsl=(on)=>setForm({...form,use_ssl:on,use_tls:on?false:form.use_tls});
  // `.admin-status` only defines active / pending / danger. Using a class it does
  // not have would render an unstyled pill, so an unconfigured server borrows
  // `danger` - it is the state that needs acting on.
  const status=form.in_use?'active':form.configured?'pending':'danger';
  const statusLabel=form.in_use?'In use':form.configured?'Saved, not active':'Not configured';
  return <div className="control-grid">
    <div className="card">
      <div className="section-head"><div><div className="eyebrow">Platform email</div><h2>SMTP configuration</h2><p>HRCloudPay sends activation links, password resets and invitations through this server. Until it is active, mail is printed to the application log instead of being delivered.</p></div><span className={`admin-status ${status}`}>{statusLabel}</span></div>
      <div className="form-row"><div><label>SMTP host</label><input value={form.host||''} onChange={e=>set('host',e.target.value)} placeholder="smtp.yourprovider.com"/></div><div><label>Port</label><input type="number" min="1" max="65535" value={form.port??587} onChange={e=>set('port',Number(e.target.value))}/></div></div>
      <div className="form-row"><div><label>Username</label><input value={form.username||''} onChange={e=>set('username',e.target.value)} autoComplete="off"/></div><div><label>Password</label><input type="password" value={form.password||''} onChange={e=>set('password',e.target.value)} placeholder={form.password_set?'Leave blank to keep current password':'SMTP password or app password'} autoComplete="new-password"/></div></div>
      <div className="form-row"><div><label>From address</label><input type="email" value={form.from_email||''} onChange={e=>set('from_email',e.target.value)} placeholder="no-reply@hrcloudpay.com"/></div><div><label>Timeout (seconds)</label><input type="number" min="1" max="300" value={form.timeout_seconds??30} onChange={e=>set('timeout_seconds',Number(e.target.value))}/></div></div>
      <div className="form-row"><div><label className="checkbox-label"><input type="checkbox" checked={Boolean(form.use_tls)} onChange={e=>setTls(e.target.checked)}/> Use STARTTLS (usually port 587)</label></div><div><label className="checkbox-label"><input type="checkbox" checked={Boolean(form.use_ssl)} onChange={e=>setSsl(e.target.checked)}/> Use SSL / implicit TLS (usually port 465)</label></div></div>
      <label className="checkbox-label"><input type="checkbox" checked={Boolean(form.is_active)} onChange={e=>set('is_active',e.target.checked)}/> Use these settings for sending</label>
      <div className="modal-actions"><button className="btn btn-secondary" onClick={()=>onTest(to.trim()||undefined)} disabled={!form.in_use}>Send test message</button><button className="btn btn-primary" onClick={()=>onSave(form)}>Save email settings</button></div>
      <label>Send a test to</label><input type="email" value={to} onChange={e=>setTo(e.target.value)} placeholder="Defaults to your own account email"/>
    </div>
    <div className="card">
      <div className="section-head"><div><h2>Before you activate</h2><p>Two things to check, in this order.</p></div></div>
      <div className="drawer-mini-list">
        <div><strong>1. Save, then send a test</strong><small>A test button only works once the settings are saved and active. A wrong password found here costs nothing; found later it means a customer cannot activate their account.</small></div>
        <div><strong>2. Check the from address</strong><small>Many providers reject a message whose From address they cannot verify, and the rejection looks like a send that succeeded.</small></div>
        <div><strong>Encrypted at rest</strong><small>The SMTP password is encrypted with the same key used for payment provider secrets. It is never sent to the browser, and the audit log records only that it changed.</small></div>
        <div><strong>Access</strong><small>Only platform superusers can read or change these settings. Company users cannot see them.</small></div>
        <div><strong>Audit</strong><small>Saving settings and sending a test are both recorded in the platform audit log.</small></div>
      </div>
    </div>
  </div>;
}

function Integrations({items,onSave,onToggle}){
  const [draft,setDraft]=useState({});
  const [oauth,setOauth]=useState([]);
  const [oauthDraft,setOauthDraft]=useState({});
  const [oauthError,setOauthError]=useState('');
  const update=(provider,key,value)=>setDraft({...draft,[provider]:{...(draft[provider]||{}),[key]:value}});
  const loadOAuth=async()=>{try{setOauth(await api.get('/integrations/platform/provider-config/'));}catch(e){setOauthError(e.message||'Could not load OAuth configuration.');}};
  useEffect(()=>{loadOAuth();},[]);
  const updateOAuth=(provider,key,value)=>setOauthDraft({...oauthDraft,[provider]:{...(oauthDraft[provider]||{}),[key]:value}});
  const saveOAuth=async(p)=>{try{const d=oauthDraft[p.provider]||{};const r=await api.post('/integrations/platform/provider-config/',{provider:p.provider,client_id:d.client_id??p.client_id,client_secret:d.client_secret||'',environment:d.environment||p.environment,enabled:p.enabled});setOauth(oauth.map(x=>x.provider===p.provider?{...x,...r}:x));setOauthError('');}catch(e){setOauthError(e.message||'Could not save OAuth configuration.');}};
  const toggleOAuth=async(p)=>{try{const r=await api.post(`/integrations/platform/provider-config/${p.provider}/toggle/`,{enabled:!p.enabled});setOauth(oauth.map(x=>x.provider===p.provider?{...x,enabled:r.enabled}:x));}catch(e){setOauthError(e.message||'Could not change OAuth provider state.');}};
  return <div>
    <div className="control-grid">
      {items.map(p=>{const d=draft[p.provider]||{}; return <div className="card" key={p.provider}>
        <div className="section-head"><div><div className="eyebrow">Payment provider</div><h2>{p.name}</h2><p>Configure platform API credentials used for subscription billing. Secrets are never returned to the browser after saving.</p></div><span className={`admin-status ${p.enabled?'active':'pending'}`}>{p.enabled?'Enabled':'Disabled'}</span></div>
        <label>Environment</label><select value={d.environment||p.environment} onChange={e=>update(p.provider,'environment',e.target.value)}><option value="test">Test / Sandbox</option><option value="live">Live</option></select>
        <label>Public / API key</label><input value={d.public_key??p.public_key} onChange={e=>update(p.provider,'public_key',e.target.value)} placeholder="Public key"/>
        <label>Secret / API secret {p.has_secret&&<small>Already configured — leave blank to keep it</small>}</label><input type="password" value={d.secret_key||''} onChange={e=>update(p.provider,'secret_key',e.target.value)} placeholder={p.has_secret?'••••••••••••••••':'Paste secret key'}/>
        <label>Webhook secret {p.has_webhook_secret&&<small>Already configured — leave blank to keep it</small>}</label><input type="password" value={d.webhook_secret||''} onChange={e=>update(p.provider,'webhook_secret',e.target.value)} placeholder={p.has_webhook_secret?'••••••••••••••••':'Optional webhook secret'}/>
        <div className="modal-actions"><button className="btn btn-secondary" onClick={()=>onSave({provider:p.provider,environment:d.environment||p.environment,public_key:d.public_key??p.public_key,secret_key:d.secret_key||'',webhook_secret:d.webhook_secret||''})}>Save credentials</button><button className={`btn ${p.enabled?'btn-danger':'btn-primary'}`} onClick={()=>onToggle(p.provider,!p.enabled)}>{p.enabled?'Disable provider':'Enable provider'}</button></div>
        <div className="usage-meta"><span>{p.has_secret?'Secret configured':'Secret not configured'}</span><span>{p.configured_at?`Configured ${new Date(p.configured_at).toLocaleDateString()}`:'Not configured'}</span></div>
      </div>})}
    </div>
    <div className="card" style={{marginTop:16}}>
      <div className="section-head"><div><div className="eyebrow">CENTRAL INTEGRATION CONTROL</div><h2>OAuth provider credentials</h2><p>Platform Admin controls the application credentials used when companies connect QuickBooks, Microsoft 365 or Xero. Company admins never enter OAuth client secrets.</p></div></div>
      {oauthError&&<div className="alert alert-error">{oauthError}</div>}
      <div className="control-grid">{oauth.map(p=>{const d=oauthDraft[p.provider]||{};return <div className="card" key={p.provider}>
        <div className="section-head"><div><h3>{p.name}</h3><p>{p.provider==='microsoft365'?'Microsoft Graph / Entra ID':p.provider==='quickbooks'?'Intuit OAuth 2.0':'Xero OAuth 2.0'}</p></div><span className={`admin-status ${p.enabled?'active':'pending'}`}>{p.enabled?'Enabled':'Disabled'}</span></div>
        <label>Environment</label><select value={d.environment||p.environment} onChange={e=>updateOAuth(p.provider,'environment',e.target.value)}><option value="production">Production</option><option value="sandbox">Sandbox</option></select>
        <label>OAuth client ID</label><input value={d.client_id??p.client_id} onChange={e=>updateOAuth(p.provider,'client_id',e.target.value)} placeholder="Application client ID"/>
        <label>OAuth client secret {p.has_secret&&<small>Already configured — leave blank to keep it</small>}</label><input type="password" value={d.client_secret||''} onChange={e=>updateOAuth(p.provider,'client_secret',e.target.value)} placeholder={p.has_secret?'••••••••••••••••':'Paste client secret'}/>
        <div className="modal-actions"><button className="btn btn-secondary" onClick={()=>saveOAuth(p)}>Save OAuth configuration</button><button className={`btn ${p.enabled?'btn-danger':'btn-primary'}`} onClick={()=>toggleOAuth(p)}>{p.enabled?'Disable':'Enable'}</button></div>
        <div className="usage-meta"><span>{p.has_secret?'Secret stored encrypted':'Secret not configured'}</span><span>{p.configured_at?`Configured ${new Date(p.configured_at).toLocaleDateString()}`:'Not configured'}</span></div>
      </div>})}</div>
      <div className="drawer-mini-list" style={{marginTop:12}}><div><strong>Security boundary</strong><small>OAuth client secrets are encrypted at rest and never returned to the company frontend. Tenant connections store only their encrypted access/refresh tokens.</small></div></div>
    </div>
  </div>
}

function GlobalSearchResults({results,onCompany,onNavigate}){const total=(results.companies?.length||0)+(results.users?.length||0)+(results.transactions?.length||0)+(results.tickets?.length||0);if(!total)return <div className="global-search-results"><small>No matches found.</small></div>;return <div className="global-search-results">{results.companies?.map(x=><button key={`c${x.id}`} onClick={()=>onCompany(x.id)}><span className="search-kind">Company</span><strong>{x.name}</strong><small>{x.email}</small></button>)}{results.users?.map(x=><button key={`u${x.id}`} onClick={()=>onNavigate('users')}><span className="search-kind">User</span><strong>{x.username}</strong><small>{x.company}</small></button>)}{results.transactions?.map(x=><button key={`t${x.id}`} onClick={()=>onNavigate('payments')}><span className="search-kind">Payment</span><strong>{x.reference}</strong><small>{x.company} · {x.status} · {x.currency} {x.amount}</small></button>)}{results.tickets?.map(x=><button key={`k${x.id}`} onClick={()=>onNavigate('support')}><span className="search-kind">Ticket</span><strong>{x.subject}</strong><small>{x.company} · {x.status}</small></button>)}</div>}

function Company360Drawer({data,onClose}){const c=data.company;return <div className="admin-drawer-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)onClose()}}><aside className="admin-drawer admin-drawer-wide"><div className="drawer-head"><div className="company-avatar drawer-avatar">{c.name.slice(0,1).toUpperCase()}</div><div className="grow"><h2>{c.name}</h2><p>{c.email} · {c.country||'Country not set'}</p></div><button className="icon-btn" onClick={onClose}>×</button></div><div className="drawer-status"><span className={`admin-status ${c.is_active?'active':'pending'}`}>{c.is_active?'Active':'Pending'}</span><span className="role-pill">{PLANS[c.plan]}</span><span className="role-pill">{data.subscription?.status||'No subscription'}</span></div><div className="drawer-metrics"><div><strong>{data.usage.employees}</strong><small>Employees</small></div><div><strong>{data.usage.active_users}</strong><small>Active users</small></div><div><strong>{data.usage.departments}</strong><small>Departments</small></div><div><strong>{data.tickets.length}</strong><small>Recent tickets</small></div></div><div className="drawer-section"><span>Subscription</span><div className="drawer-card"><strong>{data.subscription?`${PLANS[data.subscription.plan]} · ${data.subscription.provider}`:'Not configured'}</strong><small>{data.subscription?`${data.subscription.currency} ${data.subscription.monthly_price} · ${data.subscription.billing_cycle} · renews ${data.subscription.renews_at?new Date(data.subscription.renews_at).toLocaleDateString():'—'}`:'—'}</small></div></div><div className="drawer-section"><span>Users</span><div className="drawer-mini-list">{data.users.slice(0,6).map(u=><div key={u.id}><strong>{u.username}</strong><small>{u.role.replaceAll('_',' ')} · {u.is_active?'Active':'Inactive'}</small></div>)}</div></div><div className="drawer-section"><span>Recent payments</span><div className="drawer-mini-list">{data.transactions.slice(0,5).map(t=><div key={t.reference}><strong>{t.reference}</strong><small>{t.currency} {t.amount} · {t.status}</small></div>)}</div></div><div className="drawer-section"><span>Recent audit</span><div className="drawer-mini-list">{data.audit.slice(0,5).map(a=><div key={a.id}><strong>{a.action}</strong><small>{a.message} · {new Date(a.created_at).toLocaleString()}</small></div>)}</div></div></aside></div>}

function PaymentTransactions({items}){return <div className="card"><div className="section-head"><div><h2>Payment transaction center</h2><p>Every customer payment, verification and failure in one operational ledger.</p></div><span className="role-pill">{items.length} recent records</span></div><div className="table-wrap"><table className="data-table admin-table"><thead><tr><th>Reference</th><th>Company</th><th>Provider</th><th>Plan</th><th>Amount</th><th>Status</th><th>Paid</th></tr></thead><tbody>{items.map(t=><tr key={t.id}><td><strong>{t.reference}</strong><small>{t.provider_transaction_id||'No provider ID'}</small></td><td>{t.company_name}</td><td>{t.provider}</td><td>{PLANS[t.plan]||t.plan}<small>{t.billing_cycle}</small></td><td>{t.currency} {t.amount}</td><td><span className={`admin-status ${t.status==='paid'?'active':t.status==='failed'?'danger':'pending'}`}>{t.status}</span></td><td>{t.paid_at?new Date(t.paid_at).toLocaleString():'—'}</td></tr>)}</tbody></table></div></div>}

function SecurityCenter({data}){if(!data)return <div className="card page-loading">Loading security center…</div>;return <div className="control-grid"><div className="card"><div className="section-head"><div><h2>Security posture</h2><p>Platform-wide access and audit indicators.</p></div></div><div className="admin-stats security-stats"><div className="admin-stat"><div><strong>{data.active_staff_admins}</strong><span>Active staff admins</span></div></div><div className="admin-stat"><div><strong>{data.active_superusers}</strong><span>Superusers</span></div></div><div className="admin-stat"><div><strong>{data.failed_logins_total}</strong><span>Failed logins</span></div></div><div className="admin-stat"><div><strong>{data.immutable_audit_records}</strong><span>Audit records</span></div></div></div></div><div className="card"><div className="section-head"><div><h2>Security events</h2><p>Recent permission and authentication events.</p></div></div><div className="audit-list">{data.recent_events.map(x=><div className="audit-row" key={x.id}><span className="audit-action">{x.action}</span><div className="grow"><strong>{x.message}</strong><small>{x.actor} · {x.company} · {new Date(x.created_at).toLocaleString()}</small></div></div>)}</div></div></div>}

function SystemHealth({data,onRefresh}){if(!data)return <div className="card page-loading">Loading system health…</div>;return <div className="control-grid"><div className="card"><div className="section-head"><div><h2>System health</h2><p>Operational checks for the HRCloudPay control plane.</p></div><button className="btn btn-secondary btn-sm" onClick={onRefresh}>Refresh</button></div><div className="health-list">{data.checks.map(x=><div className="health-row" key={x.key}><span className={`health-dot ${x.status==='healthy'?'good':'warn'}`}>●</span><div className="grow"><strong>{x.name}</strong><small>{x.detail}</small></div><span className={`admin-status ${x.status==='healthy'?'active':'pending'}`}>{x.status}</span></div>)}</div></div><div className="card"><div className="section-head"><div><h2>Control plane</h2><p>Last health snapshot</p></div></div><div className="drawer-card"><strong>{data.status==='healthy'?'All systems operational':'Attention required'}</strong><small>{new Date(data.generated_at).toLocaleString()}</small></div></div></div>}

function FeatureFlags({items,onCreate,onSave}){const [newFlag,setNewFlag]=useState(null);return <div className="card"><div className="section-head"><div><h2>Feature flags</h2><p>Enable or disable product modules site-wide. New flags are seeded automatically (email payslips, overtime, advances, leave accruals, OAuth, etc.). Disable anything not configured yet to avoid errors for companies.</p></div><button className="btn btn-primary btn-sm" onClick={()=>setNewFlag({key:'',name:'',description:'',enabled:false,rollout_percent:100,environment:'all'})}>Add flag</button></div>{newFlag&&<div className="feature-flag-create"><input placeholder="key" value={newFlag.key} onChange={e=>setNewFlag({...newFlag,key:e.target.value})}/><input placeholder="Name" value={newFlag.name} onChange={e=>setNewFlag({...newFlag,name:e.target.value})}/><input placeholder="Description" value={newFlag.description} onChange={e=>setNewFlag({...newFlag,description:e.target.value})}/><button className="btn btn-primary btn-sm" onClick={async()=>{await onCreate(newFlag);setNewFlag(null)}}>Create</button></div>}<div className="flag-list">{items.map(f=><div className="flag-row" key={f.id}><div className="grow"><strong>{f.name}</strong><small>{f.key} · {f.description||'No description'}</small></div><select value={f.environment} onChange={e=>onSave(f.id,{environment:e.target.value})}><option value="all">All</option><option value="test">Test</option><option value="live">Live</option></select><label className="flag-switch"><input type="checkbox" checked={f.enabled} onChange={e=>onSave(f.id,{enabled:e.target.checked})}/><span>{f.enabled?'Enabled':'Disabled'}</span></label><select value={f.rollout_percent} onChange={e=>onSave(f.id,{rollout_percent:Number(e.target.value)})}>{[0,10,25,50,75,100].map(n=><option key={n} value={n}>{n}%</option>)}</select></div>)}</div>{!items.length&&<div className="empty-row">No feature flags configured.</div>}</div>}


// A thin pass-through so the tab stays declarative. `notify` is supplied by
// the caller rather than closed over: it lives in PlatformAdmin's scope, and
// reaching for it from here would be a ReferenceError at render time - which
// the error boundary turns into a blank control centre.
function MarketingContent({ payload, onSave, onCreate, onDelete, onNotice }) {
  return <MarketingEditor
    payload={payload}
    onSave={onSave}
    onCreate={onCreate}
    onDelete={onDelete}
    onNotice={onNotice}
  />;
}



