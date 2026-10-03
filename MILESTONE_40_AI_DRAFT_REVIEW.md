# Milestone 40 — AI Draft Review Studio

HRCloudPay AI drafts are now persisted as tenant-scoped review records and surfaced inside the dashboard chatbot.

## Features
- Generate employment letters, warning letters, payroll explanations, and HR reports from the chatbot.
- Persist drafts in `ai.AIDraft` with `pending`, `approved`, and `rejected` review status.
- Dashboard preview of generated draft content.
- Review status actions are workflow-only; they do not send, publish, or modify employee/payroll records.
- Every generation and review is written to the existing audit log.
- Company isolation is enforced on draft retrieval and updates.

## Run
`python manage.py migrate`

Then build the frontend normally with `npm run build`.
