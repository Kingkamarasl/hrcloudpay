# Milestone 35 — Statutory Payment & Filing Workflow

Adds a controlled workflow for each statutory filing:

Open → Review → Approve → Record Payment → Submit → Close

Payment evidence is stored separately from the filing and contains amount, payment date, method, transaction reference, receipt reference and notes. No banking credentials are stored.

Rules:
- Only owner/admin/finance can perform workflow actions.
- Filing must be reviewed before approval.
- Approval is required before payment.
- Payment amount must equal the statutory obligation amount.
- A successful payment and authority submission reference are required before a filing can be marked filed.
- Submitted payment evidence cannot be overwritten. Corrections require a separate reversal workflow.
- The legacy `/file/` endpoint is retired and returns `410 Gone`; it cannot bypass the workflow.
- Tenant isolation is enforced on every endpoint.
- Every state-changing action is audited.

Migration: `regional.0004_statutory_filing_workflow`

New endpoints:
- POST `/api/regional/filings/{id}/review/`
- POST `/api/regional/filings/{id}/approve/`
- POST `/api/regional/filings/{id}/payment/`
- POST `/api/regional/filings/{id}/submit/`
- POST `/api/regional/filings/{id}/close/`

Validation: `npm ci` and a production Vite build have been verified. Django checks,
migrations and tests still require a Python 3.11+ runtime in the execution environment.
