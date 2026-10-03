# HRCloudPay Security Operations — Milestones 57-74

## Security layers
1. Authentication hardening: secure HttpOnly browser sessions, CSRF, scoped rate limiting and progressive account lockout, MFA/TOTP and recovery-code storage model.
2. Step-up authentication: money and privilege actions re-confirm MFA (see below).
3. Tenant isolation: all security data is company-scoped; platform-level privileges are not assignable by tenant roles.
4. Document security: SHA-256 hashing, PDF/DOCX structural validation and optional ClamAV scanning service.
5. API/WAF: request-size middleware, strict security headers including Content-Security-Policy, signed/idempotent webhook architecture, trusted proxy configuration.
6. Audit integrity: a SHA-256 hash chain that is actively verified, not just written (see below).
7. Secrets: centralized Fernet encryption with a key ring and rotation command.
8. SOC/SIEM: security events, incidents, risk signals, threat indicators, response playbooks and structured security data for SIEM export.
9. Advanced detection: authentication bursts, risk scoring, device trust and controlled response.
10. Zero Trust: continuous trust score, MFA/device signals and adaptive access foundation.
11. PAM: time-limited privileged access, independent approval and emergency access architecture.
12. IT/Security governance: company security center, custom roles, SSO/SCIM configuration, access reviews and certification records.
13. DLP: bulk/external-sharing controls and security event/incident creation.
14. Resilience: encrypted-secret rotation and database backup/integrity verification commands.

## Audit chain integrity

Every `AuditLog` row is linked into a SHA-256 hash chain: each record stores the
digest of its own contents plus the previous record's digest, and the chain head
is tracked in `AuditChainState`.

**The chain is verified, not merely written.** `AuditLog.save()`/`delete()` refuse
to modify an existing record, but a database-level `UPDATE`, a `bulk_create` that
bypasses `save()`, or a deleted row would otherwise pass unnoticed. Run:

```
manage.py verify_audit_chain              # walk the entire chain
manage.py verify_audit_chain --limit 500  # sample the first N records
manage.py verify_audit_chain --json       # machine-readable
```

It exits non-zero on failure and reports, per record: `hash_mismatch` (a hashed
field was edited), `broken_link` (the back-reference no longer matches), 
`sequence_gap` (a row was inserted or deleted), `truncated_chain` (the tail was
removed), and `unchained_record` (written outside `save()`).

The Security Center's *System health → Audit chain* check recomputes digests for
a bounded sample (the full walk is O(rows), so this runs on a schedule via the
command above). It reports the exact scope it verified, e.g. "recomputed for the
first 200 records of N". A chain is only as trustworthy as the last time it was
checked — schedule the command.

## Step-up authentication (MFA on sensitive actions)

Login-time MFA proves who was present when a session opened. A session left open
or a stolen cookie would otherwise let an insider approve payroll or change a
salary hours later with no second factor. These actions therefore require an MFA
challenge completed within `MFA_STEP_UP_WINDOW_SECONDS` (default 15 minutes):

- Payroll run **approval** and **payment recording**.
- HR **salary/position change approval** (rejection is not gated — refusing a
  change cannot move money).
- **Privileged-access (PAM) approval**.

Callers without MFA enrolled are told to enable it rather than locked out
permanently. Token-authenticated API clients cannot satisfy step-up (a token has
no session to stamp) and are refused these actions explicitly — paying a payroll
run is meant to require a human with a second factor. The frontend wraps these
calls in `withStepUp(...)` (`frontend/src/api/stepUp.js`), which prompts for the
code and replays the request on a `403 mfa_required` response.

## Authentication limits

- **Per-IP:** `ScopedRateThrottle` on login (`THROTTLE_LOGIN_RATE`, default
  10/min), MFA verify/step-up (`THROTTLE_MFA_RATE`, 8/min), and password
  endpoints. This is DRF's throttle layer.
- **Per-account:** progressive lockout (`LOGIN_LOCKOUT_THRESHOLD`, default 5
  consecutive failures). Each further failure lengthens the delay (30s → 60s →
  5m → 15m → 1h, then held at 1h), so a determined attacker cannot push the
  penalty arbitrarily high (a DoS against a real user) and a user who mistypes a
  few times is only briefly delayed. A successful login clears the counter.

`/auth/login/` and `/auth/register/` no longer issue a long-lived API token. The
SPA authenticates with the HttpOnly `hrcloudpay_session` cookie; the previously
returned DRF token was a permanent, unrotatable credential that nothing used.
Tokens issued before this change stay valid until `manage.py revoke_api_tokens`
is run (use `--dry-run` first, `--user` to target one account).

## Production requirements
- HTTPS everywhere; configure `DEBUG=False`.
- Set a strong `SECRET_KEY` and a separate `SECRET_ENCRYPTION_KEYS` key ring.
- Use PostgreSQL for production and run backups to offsite immutable storage.
- Deploy ClamAV where document scanning is required.
- Put the application behind a managed WAF/reverse proxy and configure `TRUSTED_PROXY_IPS` precisely.
- Send security events to the organization's SIEM using the structured security API/export layer.
- Test restoration regularly and rotate credentials after a suspected compromise.
- Schedule `manage.py verify_audit_chain` (e.g. daily) alongside the existing
  `verify_backup`; investigate any non-zero exit as a security incident.
- Stage CSP changes with `CSP_REPORT_ONLY=True`, review violations, then enforce.
- Decide whether headless API integrations need payroll/salary actions; if so,
  they will be refused by step-up and must move to an interactive MFA session.
