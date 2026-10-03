import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { useToast } from '../context/ToastContext';

const ALLOWED_EXT = 'jpg,jpeg,png,gif,webp';

export default function CompanySettings() {
  const toast = useToast();
  const [company, setCompany] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [logoFile, setLogoFile] = useState(null);

  async function load() {
    setLoading(true);
    try {
      const data = await api.get('/auth/company/');
      setCompany(data);
    } catch (err) {
      setError(err.message || 'Unable to load company profile.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  // Keep the in-memory company in sync after a successful save or logo change.
  function refresh() { load(); }

  async function saveProfile(e) {
    e.preventDefault();
    setError('');
    setSaving(true);
    try {
      await api.patch('/auth/company/', {
        name: company.name,
        address: company.address,
        phone: company.phone,
      });
      toast.success('Company profile saved');
      await refresh();
    } catch (err) {
      setError(err.message || 'Failed to save company profile.');
    } finally {
      setSaving(false);
    }
  }

  async function uploadLogo(e) {
    e.preventDefault();
    setError('');
    const file = logoFile;
    if (!file) return setError('Choose a logo image first.');
    const ext = file.name.split('.').pop().toLowerCase();
    if (!ALLOWED_EXT.split(',').includes(ext)) {
      return setError(`Use a ${ALLOWED_EXT} image.`);
    }
    if (file.size > 5 * 1024 * 1024) {
      return setError('Logo must be 5 MB or smaller.');
    }
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('logo', file);
      await api.upload('/auth/company/logo/', fd);
      setLogoFile(null);
      e.target.reset();
      toast.success('Company logo updated');
      await refresh();
    } catch (err) {
      setError(err.message || 'Logo upload failed.');
    } finally {
      setUploading(false);
    }
  }

  async function removeLogo() {
    if (!window.confirm('Remove your company logo? It will no longer appear on payslips or break forms.')) return;
    setError('');
    try {
      await api.del('/auth/company/logo/');
      toast.success('Company logo removed');
      await refresh();
    } catch (err) {
      setError(err.message || 'Could not remove logo.');
    }
  }

  if (loading) return <p>Loading company profile…</p>;
  if (!company) return null;

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="eyebrow">COMPANY</div>
          <h1>Company profile</h1>
          <p className="page-subtitle">
            Your company name, address and logo. The logo is rendered on payslips
            and break-request forms so every printed document carries your branding.
          </p>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <h2>Company logo</h2>
        <p className="hint">
          Upload a JPG, PNG, GIF or WebP image (max 5 MB). Recommended: a wide logo
          or wordmark. It appears at the top of payslips and break-request forms.
        </p>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: '1rem' }}>
          <div className="company-logo-preview">
            {company.logo_url ? (
              <img src={company.logo_url} alt={`${company.name} logo`} />
            ) : (
              <span className="company-logo-placeholder">No logo</span>
            )}
          </div>
          <form onSubmit={uploadLogo} style={{ display: 'flex', alignItems: 'flex-end', gap: '0.75rem' }}>
            <input
              type="file"
              accept={`.${ALLOWED_EXT}`}
              onChange={(e) => setLogoFile(e.target.files?.[0] || null)}
              required
            />
            <button className="btn btn-primary compact" type="submit" disabled={uploading}>
              {uploading ? 'Uploading…' : 'Upload logo'}
            </button>
          </form>
          {company.logo_url && (
            <button className="btn btn-secondary compact" type="button" onClick={removeLogo}>
              Remove
            </button>
          )}
        </div>
      </div>

      <form className="card" onSubmit={saveProfile}>
        <h2>Profile</h2>
        <p className="hint">Company-wide contact details. These appear on payslips and printed HR forms.</p>
        <div className="form-row">
          <div>
            <label>Company name</label>
            <input
              value={company.name || ''}
              onChange={(e) => setCompany({ ...company, name: e.target.value })}
              required
            />
          </div>
          <div>
            <label>Phone</label>
            <input
              value={company.phone || ''}
              onChange={(e) => setCompany({ ...company, phone: e.target.value })}
            />
          </div>
        </div>
        <div className="form-row">
          <div style={{ flex: '1 1 100%' }}>
            <label>Address</label>
            <input
              value={company.address || ''}
              onChange={(e) => setCompany({ ...company, address: e.target.value })}
              placeholder="Shown on payslips and break forms"
            />
          </div>
        </div>
        <button className="btn btn-primary" type="submit" disabled={saving} style={{ marginTop: '1rem' }}>
          {saving ? 'Saving…' : 'Save profile'}
        </button>
      </form>
    </div>
  );
}
