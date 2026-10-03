import { useEffect, useState } from 'react';
import { api } from '../api/client';

export default function RegionalOnboarding() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => { api.get('/regional/onboarding/').then(setData).catch(e => setError(e.message)); }, []);
  if (error) return <div className="page"><div className="alert alert-error">{error}</div></div>;
  if (!data) return <div className="page"><div className="page-header"><div><h1>Country setup</h1><p>Loading your regional HR experience…</p></div></div></div>;
  if (!data.configured) return <div className="page"><div className="page-header"><div><h1>Country setup</h1><p>Your company country profile is not configured.</p></div></div></div>;
  const c=data.company;
  return <div className="page">
    <div className="page-header"><div><span className="eyebrow">REGIONAL EXPERIENCE</span><h1>{c.country_name} company setup</h1><p>HRCloudPay is configured around the payroll and employee requirements for {c.country_name}.</p></div></div>
    <div className="stats-grid"><div className="stat-card"><span>Country</span><strong>{c.country_name}</strong></div><div className="stat-card"><span>Currency</span><strong>{c.currency}</strong></div><div className="stat-card"><span>Payroll</span><strong>{c.payroll_frequency}</strong></div><div className="stat-card"><span>Employees</span><strong>{data.employee_setup.count}</strong></div></div>
    <div className="profile-content-grid">
      <section className="card"><div className="section-heading"><div><span className="eyebrow">ONBOARDING</span><h2>Company setup</h2></div></div>{data.steps.map(s=><div className="line-list" key={s.key}><div><span>{s.label}</span><strong>{s.complete?'Complete':'Needs setup'}</strong></div></div>)}</section>
      <section className="card"><div className="section-heading"><div><span className="eyebrow">EMPLOYEE DATA</span><h2>{c.country_name} fields</h2></div></div>{data.employee_setup.required_fields.map(f=><div className="line-list" key={f.key}><div><span>{f.label}</span><strong>{f.required?'Required':'Optional'}</strong></div></div>)}</section>
      <section className="card"><div className="section-heading"><div><span className="eyebrow">COMPLIANCE</span><h2>Supported areas</h2></div></div><div className="tag-list">{data.compliance_domains.map(x=><span className="badge badge-paid" key={x}>{x}</span>)}</div></section>
      <section className="card"><div className="section-heading"><div><span className="eyebrow">INTEGRATIONS</span><h2>Available integrations</h2></div></div><div className="tag-list">{data.integrations.map(x=><span className="badge badge-pending" key={x}>{x}</span>)}</div></section>
    </div>
  </div>;
}
