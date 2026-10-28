# Codester listing — "What's included" (copy-paste into the listing)

## What you get

HRCloudPay is a self-hosted HR and payroll web application. You receive the full source code (Django + React) and deploy it on your own server. No per-employee fees, no SaaS lock-in.

### Core modules
- **People**: employee records, contracts, allowances/deductions, documents, compliance requirements, Employee 360° view.
- **Payroll**: configuration snapshots, preview before processing, process/approve/pay workflow, payslip PDFs, CSV exports, finance dashboards, idempotent runs (safe retries).
- **Attendance**: check-in/out, logs, timesheets, shifts, monthly attendance grid, department-scoped views.
- **Biometric attendance**: register fingerprint/face/iris/card terminals, enrolment references, authenticated punch ingestion, optional ZKTeco ADMS bridge. Templates stay on the device.
- **Leave**: types, balances, requests, approvals, accruals, encashments, workflow automation.
- **Compliance**: country profiles, statutory rules, filing calendars, compliance packs, reconciliation.
- **AI Copilot**: natural-language HR questions, company knowledge search with citations, document extraction/OCR, HR draft generation for review.
- **Self-service portal**: employees view profile, documents, attendance, leave, and payslips.
- **Platform admin**: multi-tenant companies, users, roles, billing/plans, feature flags, marketing content, audit log, security center, system health.

### Security & access
- Role-based access: Owner/Admin, HR Manager, Finance Manager, Department Manager, Employee, Platform Admin.
- Tenant isolation: data scoped per company.
- MFA (per-account enrollment), API tokens, secure HttpOnly cookie sessions with CSRF protection.
- Append-only audit chain with actor, target, timestamp, IP context.
- Role-aware knowledge retrieval; AI drafts require human review.

### Technical
- Backend: Python 3.13, Django 6.1, Django REST Framework 3.18, PostgreSQL, Redis.
- Frontend: React 19, React Router 8, Vite 8, TypeScript.
- Docker Compose production build; GitHub Actions CI; 1,300+ automated tests.
- Multi-country ready: currency, pay rules, contributions, statutory gaps surfaced (not guessed).

### What's NOT included (do not claim)
- No single sign-on (SSO) login route.
- No IP allow-listing.
- No data-retention controls beyond the audit chain.
- No end-to-end encryption (server verifies credentials).
- No native mobile app (web self-service only).
- Payroll records payment status; it does not move money through bank/mobile-money rails.
- Regional statutory rules require verified data; unseeded countries show compliance gaps.

### Support & updates
- Self-hosted licence: you run your own instance and are the data controller.
- Terms, Privacy, and Refund policies included as editable pages.