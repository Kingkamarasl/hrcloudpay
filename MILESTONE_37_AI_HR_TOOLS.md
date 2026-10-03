# Milestone 37 — HRCloudPay AI Read-Only Tools

The dashboard chatbot now has a permission-aware server-side tool layer.

## Implemented tools
- Employee count/summary
- Employee lookup (safe profile fields only)
- Current approved leave
- Contracts expiring within a requested number of days (default 30)
- Current-month attendance summary
- Today's attendance records
- Latest payroll overview for authorized payroll roles

## Security model
- Every query is scoped to `request.user.company`.
- Employee users are restricted to their own employee record.
- Department managers are restricted to their managed department.
- HR roles can access workforce/leave/attendance tools but not payroll/compensation tools.
- Finance can access payroll tools but not general employee editing.
- Owner/admin can access all read-only tools.
- Tools are read-only. The model cannot create, approve, pay, terminate, or modify records.
- Tool results are inserted into the model context as verified server-side data.
- The UI marks responses that used verified HRCloudPay data.

## Important design choice
The first tool layer uses deterministic intent routing before the model call. This keeps database access explicit and auditable while we validate the workflow. A later stage can add NVIDIA tool/function calling without giving the model unrestricted database access.
