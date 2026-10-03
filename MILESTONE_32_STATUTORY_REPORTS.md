# HRCloudPay Milestone 32 — Country Statutory Reports & Authority-Ready Exports

## Implemented

HRCloudPay now provides a country-specific statutory report catalog and Excel export layer for the five target markets:

- Nigeria: PAYE monthly employee schedule, pension contribution schedule
- Ghana: PAYE DT 107A-oriented employee schedule, SSNIT contribution schedule
- Sierra Leone: PAYE monthly schedule, NASSIT SS4A-oriented contribution schedule
- Liberia: payroll withholding schedule, NASSCORP contribution schedule
- The Gambia: PAYE schedule, NPF, FPS and IICF schedules

Reports are generated from the selected completed payroll period and use employee statutory profiles plus payroll payslip breakdowns.

## API

- `GET /api/regional/statutory-reports/`
- `GET /api/regional/statutory-reports/<report_code>/export/?period_start=YYYY-MM-DD&period_end=YYYY-MM-DD`

Exports are `.xlsx` files.

## Design principle

These are **authority-ready mapping reports**, not claims that HRCloudPay has reproduced an authority's exact upload file. Exact upload templates should only be marked as such after the current authority schema/template has been verified.

This matters because authorities can change portal schemas, required columns and validation rules independently of the HRCloudPay payroll engine.

## Official references reviewed

- Ghana GRA confirms monthly PAYE returns are due by the 15th and publishes DT 107/107A and uploadable employee formats.
- Sierra Leone NASSIT publishes the SS4A/contribution schedule requirements and 5% employee / 10% employer structure.
- Liberia NASSCORP publishes ePayroll submission instructions, payroll-record formats and contribution schedules.
- The Gambia SSHFC publishes NPF and FPS remittance schedules and required employee information.
- Nigeria JRB 2026 guidance establishes employer PAYE reporting/remittance requirements; exact state-level PAYE submission templates remain authority-specific.

## Security

Exports are tenant-scoped through the authenticated company and payroll run. No cross-company payroll records are exposed by the report endpoints.

## Validation

- Python compileall: PASS
- Python AST parse: PASS
- Full Django runtime/migration execution was not claimed in the build environment.
- Vite production build was not claimed because frontend dependencies/runtime are not available reliably in the build environment.
