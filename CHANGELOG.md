# Changelog

All notable changes to HRCloudPay. Dates are commit dates.

## 2026-10-28

### Added
- Biometric attendance ingestion end to end: device enrollment, authenticated punch ingestion, monthly attendance grid, and an optional ZKTeco ADMS bridge (`python manage.py adt_bridge`) that forwards terminal PINs and lets the server apply the match policy.
- Employee self-service portal: profile, documents, attendance, leave requests, and personal payslip PDF downloads, scoped to the linked employee record.
- AI Copilot with company knowledge: source-grounded answers, document extraction/OCR, role-aware retrieval, and HR draft generation for review.
- Platform user management and password reset by time-limited link (admins never set passwords directly).
- Idempotent payroll mutations with stale-processing takeover, so a crashed run can be retried safely.
- Durable notification outbox with bounded retries for onboarding, contract, compliance, and leave tasks.
- Legal pages (Terms of Service, Privacy Policy, Refund Policy) seeded as editable marketing pages.
- Marketing page builder usability: duplicate sections/items and confirm-before-remove.

### Changed
- Expanded employee status to five values (active, on leave, suspended, terminated, resigned); on-leave staff stay in payroll and leave accrual.
- Department-manager scoping now matches both the legacy department field and the new department reference, so rosters assigned through the UI are visible.
- Leave scoping hardened: unlinked employee accounts and managers without a department see no rows.
- Payslip and dashboard period labels now use the run's actual period dates.
- Privacy policy copy corrected to remove unsupported IP allow-listing and single-sign-on claims.
- Landing pages (Home, Security) updated to reflect biometric attendance, self-service, and AI.

### Fixed
- Plan editor: draft now lives next to its inputs; GET/PUT contract mismatch resolved.
- Payroll isolation and employee navigation hardening.
- Biometric punch honesty: break/OT states no longer close a shift; silent terminals surfaced.
- Attendance month grid backend and UI.

### Infrastructure
- Python 3.13 / Django 6.1 / DRF 3.18; React 19 / React Router 8 / Vite 8 / Vitest 5.
- CI on Node 24 and current GitHub Actions; frontend build in backend integration tests.
- 1,300+ automated tests; full suite green in CI.

## 2026-10-26

- Employee self-service dashboard, leave requests, and payslip access by role.
- Payroll preview and effective-dated configuration snapshots.
- Harden payroll isolation and employee navigation.
- Correct employee API calls and CI frontend tests.