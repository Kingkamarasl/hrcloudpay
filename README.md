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
- Set the SMTP details at Platform Admin -> Email / SMTP for activation emails
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

This is why the deployment is one service rather than two. A platform *can* run
a Django service and a Vite service behind one routing table on one domain, with
`/api`, `/site-icon/`, `/admin/`, `/static/` and `/media/` rewritten to Django
and everything else to the SPA - the browser still sees a single origin, and the
cookie and CSRF reasoning above holds unchanged. That arrangement was used here
once and has since been removed in favour of building the SPA inside the
container image, which is one service and one routing table instead of two and
one. The rule that matters is the one above: one *origin*. How many services
produce it is an implementation detail.

### Deploying to Railway

One service, one image, built from the root `Dockerfile`. That file is a
multi-stage build: Node compiles the SPA into `/app/frontend/dist`, the Python
stage copies it to `frontend_dist/`, and `serve_frontend` plus WhiteNoise serve
both the app and its assets from one origin. So there is no second frontend
service, no rewrite table and no CORS to configure.

Two things the image deliberately does *not* do, both of which matter more here
than anywhere else:

- **Migrations do not run in the build.** This stage has no `DATABASE_URL`, so
  `settings.py` falls back to SQLite and `migrate` would build a throwaway
  database inside the image that never reaches production. Migrations belong in
  a release step - see below.
- **`db.sqlite3` is removed after `collectstatic`.** At least one
  `AppConfig.ready()` opens a connection, so Django creates the file even though
  nothing is written to it. An image carrying an empty database boots cleanly
  when `DATABASE_URL` is missing at runtime and serves an empty application
  rather than failing loudly.

#### Service settings

| Setting | Value |
|---|---|
| Root directory | repository root (`/`) |
| Builder | Dockerfile (Railway detects it) |
| Start command | leave empty - the Dockerfile `CMD` binds `$PORT` |
| Release command | see below |

Railway injects `PORT` and routes traffic to it, 8080 by default. The `CMD`
reads `${PORT:-8000}`. A hardcoded port builds successfully and then 502s on
every request with nothing in the build log to explain it.

#### Variables

Add the Postgres plugin first. Railway then injects `DATABASE_URL` for you as a
reference to the plugin - do not paste the connection string in by hand, or the
next database replacement leaves the app pointing at the old one. The same
applies to the Redis plugin.

Set the rest as service variables:

```
SECRET_KEY=<generate: python -c "from django.core.management.utils import get_random_secret_key as k; print(k())">
DEBUG=False
ALLOWED_HOSTS=hrcloudpay.com
FRONTEND_URL=https://hrcloudpay.com
BACKEND_PUBLIC_URL=https://hrcloudpay.com
SECURE_SSL_REDIRECT=True
DEFAULT_FROM_EMAIL=no-reply@hrcloudpay.com
AWS_STORAGE_BUCKET_NAME=<bucket>
AWS_S3_REGION_NAME=<region>
AWS_ACCESS_KEY_ID=<key>
AWS_SECRET_ACCESS_KEY=<secret>
# Outbound email is NOT configured here. Leave EMAIL_BACKEND unset and
# set the SMTP details at Platform Admin -> PLATFORM -> Email / SMTP. There
# are deliberately no EMAIL_HOST / EMAIL_PORT / EMAIL_USE_TLS variables -
# this project does not read them, so setting them changes nothing.
CORS_ALLOWED_ORIGINS=
```

**`FRONTEND_URL` is the value that bites**, and it ships undocumented as a plain
`http://localhost:5173`. It builds company activation links
(`accounts/views.py`, `accounts/platform.py`), the post-payment redirect
(`accounts/payment_services.py`) and OAuth return URLs (`integrations/oauth.py`).
A deployment that copied `.env.example` faithfully sends every activation email
to a link that resolves nowhere, and no account can be activated. Set it to
`https://hrcloudpay.com` with no trailing slash.

`CORS_ALLOWED_ORIGINS` can be empty: the SPA and the API share an origin, so no
cross-origin request is ever made. Leaving the localhost default is harmless but
misleading.

Set `AWS_STORAGE_BUCKET_NAME`. `MEDIA_ROOT` is a directory on whichever machine
runs Django, so without the bucket every uploaded file is lost on the next
deploy - employee documents, contracts, payslip attachments and knowledge-base
sources.

#### Release command

This runs against the real database before traffic shifts, which is the only
place `migrate` can safely live:

```
cd backend && python manage.py migrate --noinput && python manage.py seed_country_rules && python manage.py seed_filing_rules
```

`seed_country_rules` and `seed_filing_rules` are not optional - tax and filing
tables are what a payslip is calculated from, and an empty one produces a
plausible payslip with the wrong numbers.

Once, on the first deploy only, seal the audit backlog:

```
python manage.py seal_audit_backlog
```

It is a management command rather than a data migration on purpose. A migration
would fire implicitly on every deploy and would imply the historical rows had
been verified, which they have not.

#### Custom domain

Attach `hrcloudpay.com` to the service and set the DNS records Railway shows
you. **Pick one hostname.** Serving both `hrcloudpay.com` and
`www.hrcloudpay.com` splits sessions and duplicates every page - a visitor
bounces between them mid-session and the cookie is set twice. Redirect `www` to
the apex.

#### The first company on a new database

Verified against a freshly migrated database, because it is the step that has no
documentation and no error message.

`RegisterSerializer.create` inserts a `Company` with `is_active` at its model
default, which is **False** (`accounts/models.py`). The owner account is active,
so the person registers and logs in successfully - and then `IsCompanyActive`
refuses every core HR and payroll route with *"Your company account is not yet
activated."*

The public registration path **does** send an activation email
(`RegisterView.post`, `accounts/views.py`) - but with `fail_silently=True`, so
a mail failure is invisible. With the console backend it appears in the logs; on
a server with no SMTP configured it goes nowhere at all and registration still
returns 201 with "check your email to activate your account". Configure
`EMAIL_BACKEND`, or set it from Platform Admin -> Email / SMTP, or every
self-service signup produces a company that can never be activated and no error
anywhere says why.

Bootstrap a platform superuser and activate it:

```
railway run python manage.py createsuperuser     # company: leave blank
railway run python manage.py shell -c "from accounts.models import Company; \
  Company.objects.update(is_active=True); print(Company.objects.count(), 'activated')"
```

A superuser's `company` must be null - the platform's own endpoints reject a
superuser attached to a tenant, and `admin` in a seeded dev database is a
frequent source of confusing 403s for the same reason.

**Do not set `EMAIL_BACKEND`.** It defaults to
`hrcloudpay.email_backend.PlatformEmailBackend`, which reads the SMTP host,
port, credentials and sender from the `EmailConfig` row saved at Platform
Admin -> PLATFORM -> Email / SMTP. Setting `EMAIL_BACKEND` yourself replaces
that with a backend which reads settings this project does not define, so it
connects to `localhost:25` and every message is refused. There are no
`EMAIL_HOST` / `EMAIL_PORT` / `EMAIL_USE_TLS` variables here because nothing
reads them; an operator who sets all of them correctly still gets refused
connections.

With no saved configuration the backend falls back to the console, which on a
container writes to stdout that nobody reads. Failures are logged at ERROR
rather than swallowed, so check `docker compose logs backend` before assuming
a signup went out.

#### Health checks

Leave the healthcheck path empty. The obvious candidate,
`/api/auth/platform/system-health/`, requires `IsAdminUser`, so an
unauthenticated probe gets a 403 and Railway would mark a perfectly healthy
service as down. That endpoint is an operator tool, not a liveness probe.

#### What this host does not have

Nothing, compared with a container platform - tesseract is installed in the
image, so OCR of scanned documents works. That is the one capability a shared
host cannot provide and the reason this deployment target is a better fit than
one.

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
