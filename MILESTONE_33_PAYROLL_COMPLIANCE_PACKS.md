# HRCloudPay Milestone 33 — Payroll Compliance Packs

## Purpose
Connect the payroll lifecycle to statutory compliance work. Approved and paid payroll runs can automatically create a country-specific compliance pack containing filing obligations and report exports.

## Lifecycle
Draft -> Processed -> Approved -> Paid

At Approved (and refreshed at Paid), HRCloudPay prepares:
- effective statutory filing obligations
- filing due dates
- filing amounts from the payroll run
- country-specific report catalog
- reviewable compliance-pack record

## API
- GET `/api/regional/compliance-packs/`
- POST `/api/regional/compliance-packs/generate/<run_id>/`
- GET `/api/regional/compliance-packs/<id>/export/`
- POST `/api/regional/compliance-packs/<id>/submit/`

## Scheduled maintenance
`python manage.py generate_compliance_packs` refreshes packs for approved/paid runs.

## ZIP contents
A downloaded pack contains `manifest.csv` and country-specific Excel reports generated from the attached payroll run.

## Status
`draft -> ready -> submitted -> closed` (closed is reserved for a future filing reconciliation workflow).

## Verification
Python compile/AST checks were performed. Full Django runtime, migrations, and Vite build were not claimed in this environment.
