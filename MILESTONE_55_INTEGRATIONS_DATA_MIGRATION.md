# Milestone 55 — Integrations & Data Migration

## Objective
Make HRCloudPay practical for companies moving from existing HR/accounting systems while keeping integration credentials under Platform Admin control.

## Included
- Central Platform Admin OAuth credential vault for QuickBooks Online, Microsoft 365 and Xero.
- Encrypted OAuth client secrets; secrets are never returned to tenant/company frontends.
- Provider enable/disable controls and environment selection.
- Tenant OAuth connection flow continues to use company-scoped encrypted access/refresh tokens.
- CSV and Excel employee import with field mapping, validation, duplicate detection and preview.
- Import execution with optional duplicate updates and rollback of records created by an import.
- External-record mapping for future two-way synchronization.
- Accounting catalog synchronization and payroll journal export foundations.
- Scheduled synchronization configuration.
- Provider webhook event capture and sync conflict resolution.
- Audit events for integration configuration, imports, rollback, payroll exports and conflict resolution.

## Security architecture
1. Platform Admin configures provider application credentials.
2. Tenant admin authorizes the company connection at the provider.
3. HRCloudPay stores tenant tokens encrypted at rest.
4. Provider credentials and tenant tokens are never exposed to React clients.
5. Company-scoped permissions and active-tenant checks remain mandatory.

## Migration workflow
**Upload → Analyze → Map → Validate → Preview → Import → Review → Roll back if necessary**

Supported employee import fields include employee ID, name, email, phone, job title, department, salary, hire date, employment status and ID-card/identifier.

## Provider roadmap
The integration abstraction is intentionally provider-based so additional accounting, identity, storage and HR systems can be added without changing the tenant data model.

## Validation
Run:
```bash
cd backend
python manage.py makemigrations --check
python manage.py check
python -m compileall -q integrations accounts
```

Frontend:
```bash
cd frontend
npm ci
npm run build
```
