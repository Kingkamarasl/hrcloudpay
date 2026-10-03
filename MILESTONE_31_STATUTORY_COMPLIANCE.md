# HRCloudPay Milestone 31 — Statutory Compliance & Filing Calendar

## Scope
This milestone builds the compliance layer on top of the country-aware statutory engine and PAYE engines.

### Added
- Effective-dated `StatutoryFilingRule` country filing calendar.
- Tenant `StatutoryFiling` register with period, due date, status, amount, reference and payroll-run linkage.
- Country-aware filing calendar API.
- Filing generation API for a completed payroll period.
- Filing status workflow: open → ready → filed; overdue is calculated automatically.
- Generic reviewable CSV export with employee identifiers, gross salary, PAYE and statutory contribution amounts.
- Management command for monthly generation:
  `python manage.py generate_statutory_filings`
- Rule seed command:
  `python manage.py seed_filing_rules`
- Regional Statutory Compliance frontend workspace.
- Unfold admin for filing rules and filing records.
- Audit events when users generate or mark filings as filed.

## Verified deadline sources used for seeded rules
- Nigeria JRB 2026 PIT Guidelines: PAYE remittance by the 10th of the following month; annual employer return by 31 January.
- Ghana GRA: monthly PAYE by the 15th of the following month.
- Ghana SSNIT: 13.5% remittance to SSNIT within 14 days of the following month; contribution report by month-end.
- Sierra Leone NASSIT: total contribution due within 15 days after month-end.
- Liberia LRA: PIT/wage withholding due by the 10th of the succeeding month.
- The Gambia SSHFC: NPF and FPS contributions due by the 15th of the following month.

The sources are stored on each filing rule so the tenant can inspect the authority reference.

## Deliberate limitation
The CSV export is a generic reviewable export, **not** an assertion that it is an authority-upload-ready file. Each authority's current upload schema should be verified before an exact submission template is implemented.

NASSCORP was intentionally not assigned an automated payment deadline in this milestone because the current official material reviewed did not provide a sufficiently clear universal deadline. The obligation can be added through the filing-rule registry once verified.

## APIs
- `GET /api/regional/filing-calendar/?days=120`
- `GET /api/regional/filings/`
- `POST /api/regional/filings/generate/`
- `POST /api/regional/filings/{id}/file/`
- `GET /api/regional/filings/{id}/export/`

## Local setup
After applying migrations:

```text
python manage.py migrate
python manage.py seed_country_rules
python manage.py seed_filing_rules
```

For recurring monthly generation, run:

```text
python manage.py generate_statutory_filings
```

Use Windows Task Scheduler, cron, or a production scheduler to run the command monthly.

## Validation
- Python `compileall` passed.
- AST parsing of backend Python files passed.
- Full Django runtime/migration execution and Vite build were not claimed in this build environment.
