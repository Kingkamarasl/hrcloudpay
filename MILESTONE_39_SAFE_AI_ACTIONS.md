# Milestone 39 — Safe AI-assisted actions

Added a review-only drafting endpoint at `POST /api/ai/drafts/`.

Supported types:
- `employment_letter`
- `warning_letter`
- `payroll_explanation`
- `hr_report`

Request:
```json
{"type":"employment_letter","context":"Verified facts supplied by HRCloudPay..."}
```

Response includes `requires_review: true` and `saved: false`. The endpoint never writes employee, payroll, contract, attendance, or leave records. A human must review and manually perform any later action.
