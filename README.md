# HRCLOUDPAY

Simple, affordable HR and payroll system built for African businesses.

This is an MVP starter codebase: **Django REST Framework backend + React (Vite) frontend**.
It implements the core flow discussed:

1. A business registers a company account.
2. They activate it via an emailed link.
3. Immediately after activation, they fill in a **Payroll Setup** form declaring
   their own country's tax brackets, statutory contributions (pension, social
   security, etc.), currency, and pay frequency — no country is hardcoded.
4. From then on, payroll is calculated automatically using *that company's own
   configuration*, so the same codebase serves a business in Guinea, Nigeria,
   Kenya, or anywhere else in Africa without code changes.

## What's implemented (Starter/Business tier features)

- Company registration + email activation. **There is no public/independent
  user signup beyond this** — every other login (Admin, HR Manager, Finance
  Manager, Department Manager, Employee) is created by an owner/admin from
  the **Team Accounts** screen, under that company only.
- Role-based access control with five roles beyond the company owner:
  - **Admin** — same access as owner
  - **HR Manager** — manages employees, contracts, allowances/deductions,
    attendance, and leave company-wide; no payroll/financial access
  - **Finance Manager** — manages payroll setup, runs, approvals, payments,
    exports, and reports; no employee-record editing access
  - **Department Manager** — HR-lite access scoped only to employees in
    their assigned department (attendance, leave approval)
  - **Employee** — self-service only: their own profile, attendance, leave,
    and payslips, linked to a specific Employee record
- Token-based authentication (login/logout)
- Per-company **Payroll Setup** onboarding (currency, pay frequency, progressive
  tax brackets, statutory contributions — employee/employer split)
- Employee management (CRUD), with per-employee allowances & deductions
- Contracts (linked to employees, with file upload support)
- Payroll runs: create a run for a period, then "Run payroll" to auto-generate
  a payslip per active employee using the progressive tax + contributions engine
- Payroll approval and payment recording with payment method and reference
- Payroll CSV export and summary totals for gross, tax, contributions, deductions, and net
- Payroll dashboard with charts (amount by employee, pay-date trends, department
  breakdown, employer funding cost, recent runs table) — Finance/owner/admin only
- Payroll validation: rejects invalid tax brackets, invalid rates, reversed periods,
  and duplicate payroll periods; processing is atomic and protected against repeats
- Payslip PDF downloads from the payroll screen and authenticated API
- Attendance tracking, with Department Managers restricted to their own team
- Leave requests with approve/reject actions, department-scoped for Department Managers
- Plan-based employee limits (Starter 10 / Business 50 / Professional 150 / Enterprise unlimited)

## Not yet built (natural next steps)

- Email notifications beyond the activation email (e.g. payslip ready, leave approved,
  "your team account was created")
- Mobile-friendly employee self-service portal UI (backend scoping already supports it)
- Payment integration with mobile money / bank rails
- A real Department model (departments are currently a free-text field on Employee,
  matched by exact string against a Department Manager's `managed_department` — fine
  for an MVP, but worth normalizing into its own model once departments need their
  own settings or a company has many of them)

## Roles reference

| Role | Employees/Contracts | Attendance/Leave | Payroll | Team Accounts |
|---|---|---|---|---|
| Owner / Admin | Full | Full | Full | Full |
| HR Manager | Full | Full | None | None |
| Finance Manager | None | None | Full | None |
| Department Manager | Own department only | Own department only | None | None |
| Employee | Own record only | Own record only | Own payslips only | None |

Accounts for every role except Owner are created via `POST /api/auth/users/`
(owner/admin only) — see the **Team Accounts** page in the frontend.

## Project structure

```
hrcloudpay/
  backend/         Django + DRF API
    accounts/      Company + custom User model, register/activate/login
    employees/     Employee, Contract, Allowance, Deduction
    payroll/       PayrollConfig (per-company tax/contribution rules),
                    calculation engine (services.py), PayrollRun, Payslip
    attendance/     Attendance records
    leave/          Leave requests + approve/reject
  frontend/        React (Vite) SPA
    src/pages/      Login, Register, Activate, PayrollSetup, Dashboard,
                    Employees, Payroll, Attendance, LeaveRequests
```

## Running the backend

Requires Python 3.11+.

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env            # edit SECRET_KEY etc. as needed

python manage.py migrate
python manage.py createsuperuser   # optional, for /admin/

python manage.py runserver
```

The API will be live at `http://localhost:8000/api/`. Django admin at
`http://localhost:8000/admin/`.

By default, activation emails print to the console (dev email backend) — after
registering, check your terminal output for the activation link.

## Running the frontend

Requires Node.js 18+.

```bash
cd frontend
npm install
cp .env.example .env    # defaults to http://localhost:8000/api, adjust if needed
npm run dev
```

The app will be live at `http://localhost:5173`.

## Single-server mode (Django serves the frontend too)

If you'd rather run **one server and visit one URL** instead of two dev
servers, build the frontend and let Django serve it directly:

```bash
cd frontend
npm install
npm run build          # builds into backend/frontend_dist/

cd ../backend
python manage.py collectstatic --noinput   # optional, WhiteNoise can serve without this too
python manage.py runserver
```

Now visit **`http://127.0.0.1:8000/`** — that's the whole app: Django serves
the built React app for `/` and every other frontend route (`/employees`,
`/payroll`, `/activate/...`, etc.), while `/api/...` and `/admin/` keep
working exactly as before, from the same server.

Trade-off: in this mode you lose Vite's hot-reload — any frontend change
requires re-running `npm run build`. For active frontend development, use
the two-server setup above instead; switch to single-server mode when you
want to test or deploy the whole thing as one unit.

## Typical first run

1. Start the backend and frontend (above) — either the two-server dev setup,
   or single-server mode.
2. Go to `/register` (on whichever URL you're using), register a company + owner account.
3. Check the backend terminal for the activation link, open it (or paste the
   printed URL into your browser).
4. Log in, go to **Payroll Setup**, and fill in your country's tax brackets and
   statutory contributions.
5. Go to **Employees** and add a few employees with base salaries.
6. Go to **Payroll**, create a run for a period, and click **Run payroll** to
   generate payslips using your configured rules. Expand the processed run and
   click **PDF** beside a payslip to download it.

## Running tests

From the `backend` directory:

```bash
python manage.py test
```

The test suite covers progressive tax, contributions, invalid periods, duplicate
period protection, payroll processing, and PDF generation.

## A note on the payroll engine

`backend/payroll/services.py` is deliberately country-agnostic. It never
references a specific country's tax law — it just applies whatever tax
brackets and contribution rates the company itself declared during onboarding.
This is what lets HRCLOUDPAY serve the whole African market from one codebase
instead of maintaining separate logic per country. If you later want to speed
up onboarding by offering pre-filled country templates (e.g. "Nigeria PAYE
defaults"), that can be added as optional starting data for the same form
without changing this calculation engine.

## Current product positioning

HRCloudPay is now presented as a unified People + Payroll + AI + Knowledge + Compliance workspace. The public marketing homepage highlights payroll, Employee 360°, HRCloud AI, document intelligence, compliance/audit, and connected operations. See `MILESTONE_48_MARKETING_FRONT_PAGE.md` for the marketing architecture and messaging.

## Deploying

This MVP uses SQLite and Django's console email backend for easy local setup.
Before going live:
- Set `DATABASE_URL` to a Postgres URL with `sslmode=require` — `settings.py` reads
  it and falls back to SQLite when it is absent, so nothing in the source needs
  editing
- Set `REDIS_URL` if you run more than one worker. DRF's rate-limit counters live
  in the default cache, which is per-process, so with 4 workers the configured
  login limit of 10/minute silently becomes 40/minute
- Set `AWS_STORAGE_BUCKET_NAME` and `AWS_S3_REGION_NAME`. `MEDIA_ROOT` is a
  directory on whichever machine runs Django, so on a container platform **every
  deploy destroys every uploaded file** — employee documents, contracts,
  payslip attachments, knowledge-base sources. With the bucket set, uploads go
  to private S3 and versioning/replication become the provider's problem
- Configure a real `EMAIL_BACKEND` (e.g. SendGrid, Mailgun, SES) for activation emails
- Set `DEBUG=False`, a real `SECRET_KEY`, and proper `ALLOWED_HOSTS`
- Run `npm run build` (frontend) then `python manage.py collectstatic --noinput`
  (backend) and deploy the single Django app — WhiteNoise (already wired in)
  serves both the built frontend and static assets, so no separate Nginx/static
  host is required. Point your deploy platform at `backend/` and run it with
  something like `gunicorn hrcloudpay.wsgi`

**Deploy the frontend and backend as one origin.** The earlier advice to split
them across two *domains* (frontend on Vercel/Netlify, backend on a VM, with
`VITE_API_URL` set at build time) is wrong for this application. The session
cookie is `HttpOnly` and scoped to the API origin, so putting the SPA on a
different domain forces `SameSite=None; Secure` on it. That disables the
browser's automatic CSRF protection and makes every API call a CORS preflight.
Serving both from Django keeps the cookie `SameSite=Lax` and the CSRF defence
intact.

Note that this rules out two *domains*, not two *services*. `vercel.json`
declares Vercel Services — a Django service and a Vite service behind a single
routing table on **one domain**, with `/api`, `/site-icon/`, `/admin/`,
`/static/` and `/media/` rewritten to Django and everything else to the SPA.
The browser still sees one origin, so the cookie and CSRF reasoning above
holds unchanged and `VITE_API_URL` stays unset. What Services changes is who
builds and serves the assets, not where the browser thinks it is.

### Deploying to Vercel

1. Set the project's framework to **Services** in Build and Deployment
   settings. Both conditions are required — the framework setting *and* a
   `services` key in `vercel.json` — otherwise Vercel silently ignores the
   services block and builds the repo as a single app.
2. Add the environment variables from `.env.example`. `DATABASE_URL`,
   `SECRET_KEY`, `REDIS_URL`, `ALLOWED_HOSTS` and the `AWS_*` media variables
   are all required; each fails in a way that is easy to misread (SQLite, or
   per-worker rate limits, or files that vanish on redeploy).
3. Deploy. The frontend service builds with
   `npm run build -- --outDir dist --base /`, which puts assets under
   `/assets/` instead of the `/static/` that Django serves in single-server
   mode. Do not change `vite.config.js` — the default build is what the Docker
   and local single-server paths depend on.
4. Run the release order (`migrate`, then the two seeds, then
   `collectstatic`) as a separate step. Vercel does not run these, and putting
   them in a build command would race across concurrent and preview builds.

The backend runs as a **container**, built from `backend/Dockerfile`. That is
not a packaging preference, it is required by two features:

- **OCR.** `pytesseract` shells out to a `tesseract` binary. Vercel's Python
  runtime has no system packages, so scanned PDFs would silently extract no
  text at all. The image installs `tesseract-ocr`.
- **Request duration.** PDF generation and document ingestion run inside a
  function with a hard wall-clock limit, which a large payslip run or a bulk
  ingestion job can exceed.

The trade is a slower cold start. Going back to the Python runtime means
replacing the `runtime` key with a WSGI `entrypoint` of
`hrcloudpay.wsgi:application`, and it costs both features above.

Two things about the container are easy to get wrong:

- Its build context is `backend/`, not the repository root, so paths inside
  `backend/Dockerfile` are relative to `backend/` and that directory carries
  its own `.dockerignore`. A `COPY backend/...` line in that file resolves to
  `backend/backend/...` and fails the build.
- It builds the backend only. The root `Dockerfile` still builds frontend and
  backend into one image served entirely by Django, which is the right shape
  for a container host or a VM and is what `docker-compose` uses. The two
  coexist because they deploy different things: on Vercel the Vite service has
  already built and is already serving the SPA, so building it again into the
  backend image would add some fifty chunks that image never serves.

Uploaded files are served by `hrcloudpay.views.serve_media` in every environment,
not only under `DEBUG`. Under the old DEBUG-only `static()` route, production
served no uploaded file at all — company logos and employee photos 404 — and
merely enabling `static()` in production would have published every identity,
medical and disciplinary document to anyone holding the URL, since `static()`
performs no identity check. `serve_media` keeps the route and applies per-kind
role rules (see `backend/hrcloudpay/media_access.py`); `finance` cannot fetch an
employee's medical certificate, and no tenant can fetch another tenant's file.

Note that `create_backup` backs up the **database only** — the rows name each
uploaded file but do not contain it. Back up the bucket too, and restore both
into a scratch environment to confirm the documents actually open.

### Release order

Run these in this order. Steps 2 and 3 are not optional and neither is safe to
defer past the point where the new code serves traffic.

```
npm ci && npm run build                       # 1. frontend into backend/frontend_dist/
python manage.py migrate --noinput            # 2. must complete before anything serves
python manage.py seed_country_rules           # 3. must complete before any payroll is approved
python manage.py seed_filing_rules            # 4. populates the statutory filing calendar
python manage.py collectstatic --noinput
python manage.py check --deploy               # 5. reports regional.W001 if step 3 was skipped
python manage.py verify_audit_chain           # 6. must report a verified chain
gunicorn hrcloudpay.wsgi
```

**If step 6 reports `unchained_record`.** That means audit rows exist that were
written before `AuditLog.save()` began sealing them, which is every row on a
database that was in use before the chain writer landed. Run this once:

```
python manage.py seal_audit_backlog --dry-run   # see what would be sealed
python manage.py seal_audit_backlog
```

It enters those rows into the chain, in the order they were written. It does not
claim they were verified at the time — they were written when there was no
mechanism that could have detected tampering either way. What it does give you
is one unbroken chain, and detection of any modification from here on. A new
database never needs it.

Steps 2–5 run against the *deployed* database, so `DATABASE_URL` must point at
it. They deliberately do not run inside `Dockerfile`: that build stage has no
`DATABASE_URL`, so `migrate` would quietly build a throwaway SQLite file in the
image while the running container talks to Postgres — a step that looks handled
and migrates nothing.

**Why step 3 is not optional.** The statutory rates for the original country
packs are written by `seed_country_rules`, not by a migration, so `migrate`
alone leaves the `StatutoryRule` table empty. HRCloudPay refuses to present a
statutory figure it has no verified rule for, so on an unseeded deployment every
payslip for Nigeria, Ghana, Sierra Leone, Liberia and The Gambia carries a
**blocking** compliance gap and payroll runs cannot be approved. The payslip
totals still look correct right up until the approval step.

`manage.py check` reports this as `regional.W001` whenever the table is empty
while companies have a country profile. It is a warning rather than an error on
purpose, so that a fresh install can still be migrated and seeded.

Both seed commands are idempotent — they `update_or_create` on
`(country, code, effective_from)`, so re-running them will not duplicate rows
and will pick up amended rates in place. Both also print a list of the countries
they deliberately left unseeded. That is expected, not a failure: a country
without verified rates is blocked rather than guessed at.


## Milestone 14 — Sensitive-action auditing
Sensitive HR/payroll and authentication events are now recorded in the append-only AuditLog, including salary changes, employment termination, contracts, allowances/deductions, attendance, leave/break approvals, payroll processing/approval/payment, permission changes, login success/failure, and logout. Audit entries capture actor, company, target, timestamp, IP (when available), and structured before/after metadata for selected changes.


## Milestones 21B–21D
External integration OAuth foundations for Microsoft 365, QuickBooks Online, and Xero, plus encrypted credentials, external record mapping, sync jobs, and Microsoft 365 user synchronization into reviewable import jobs. The implementation is in `backend/integrations/`.

## Full documentation

This README is the current setup and deployment guide. Milestone implementation notes
available in this source bundle are kept at the repository root.

### Recent product documentation

- `MILESTONE_36_NVIDIA_AI.md` — NVIDIA-hosted AI foundation and dashboard assistant.
- `MILESTONE_41_AI_KNOWLEDGE_RAG.md` — company-specific AI knowledge retrieval.
- `MILESTONE_42_NVIDIA_SEMANTIC_RAG.md` — semantic embeddings and retrieval.
- `MILESTONE_43_PLATFORM_AI_CONFIGURATION.md` — centralized Platform Admin AI configuration.
- `MILESTONE_44_AI_CITATIONS.md` — AI source citations.
- `MILESTONE_45_AI_DOCUMENT_INTELLIGENCE.md` — PDF/DOCX document intelligence.
- `MILESTONE_46_OCR_ADVANCED_DOCUMENT_INTELLIGENCE.md` — OCR and advanced document metadata.
- `MILESTONE_47_DOCUMENT_LIFECYCLE_SECURITY.md` — document lifecycle, versioning, and role-based knowledge access.
- `MILESTONE_48_MARKETING_FRONT_PAGE.md` — public homepage positioning and marketing implementation.


## Milestone 27
Regional country-experience foundation added for 15 African countries (Nigeria, Ghana, Sierra Leone, Liberia, The Gambia, Kenya, Tanzania, Uganda, Rwanda, Zambia, Zimbabwe, Botswana, Namibia, South Africa and Egypt). The packs ship with no verified statutory rates - each country raises blocking compliance gaps until its rules are seeded with verified data and a source reference. See `MILESTONE_27_REGIONAL_FOUNDATION.md`.

## Milestones 49–53 — Productization & Production Operations

- **Milestone 49 — Knowledge Center & AI Experience 2.0:** dedicated company knowledge library, lifecycle/version visibility, role-aware access, upload/index/archive/restore/reindex workflows, and AI Copilot positioning.
- **Milestone 50 — Employee 360° Production Operations:** operational employee workspace connecting people, contracts, documents, compliance, warnings, requests, salary/position changes and activity history.
- **Milestone 51 — Payroll Production Hardening:** transactional processing plus row locking for approval/payment, duplicate-period protection and audit-ready state transitions.
- **Milestone 52 — Attendance & Leave Operations:** connected workforce operations entry point for attendance, leave, accruals, encashments and request tracking.
- **Milestone 53 — Platform Admin / SaaS Control Center:** centralized tenant, billing, usage, support, security, feature flags, system health, marketing, integrations and NVIDIA AI controls.

These phases preserve tenant isolation, Django-side authorization and the Platform Admin boundary for provider/API secrets.


## Milestone 54 — Production Billing & Subscriptions

Production-oriented subscription lifecycle, cancellation/reactivation controls, payment failure handling, billing-period tracking, and invoice records. See `MILESTONE_54_BILLING_SUBSCRIPTIONS.md`.

- Milestone 55 — Integrations & Data Migration: `MILESTONE_55_INTEGRATIONS_DATA_MIGRATION.md`

## Consolidated Security Architecture (Milestones 57-74)
The original HRCloudPay milestone 36-56 product is now extended with a unified security architecture covering secure browser sessions, MFA/TOTP, tenant isolation controls, file/document security, request and webhook hardening, centralized encryption/key rotation, security monitoring/SOC/SIEM foundations, threat detection, Zero Trust/device trust, privileged access management, IT/Security governance, SSO/SCIM configuration, access reviews, and DLP event controls. The operational UI is available at `/security-center` for owner/admin users.

Browser authentication uses an HttpOnly `hrcloudpay_session` cookie and CSRF protection. Token authentication remains available for non-browser API clients. Configure `SECRET_ENCRYPTION_KEYS` as a comma-separated key ring in production and rotate encrypted values with `python manage.py rotate_encrypted_secrets --dry-run` followed by the live command.
