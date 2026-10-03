# Milestone 51 — Payroll Production Hardening

## Delivered
- Database uniqueness for company + payroll period already protects duplicate payroll periods.
- Payroll processing locks the payroll run inside a database transaction.
- Payroll approval now locks the run with `select_for_update()` to prevent concurrent approval races.
- Payroll payment now locks the run with `select_for_update()` to prevent duplicate concurrent payment transitions.
- Existing payslip uniqueness remains enforced per payroll run + employee.
- Sensitive payroll actions continue to emit audit records.

## Workflow
Draft → Processed → Approved → Paid.

Invalid state transitions are rejected by the API.
