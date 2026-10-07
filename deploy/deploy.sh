#!/usr/bin/env bash
# HRCloudPay production deploy for a single VM.
#
# Run from the repository root:
#     bash deploy/deploy.sh
#
# The order matters and is not negotiable. Migrations run before the new code
# serves traffic, and the audit chain is verified afterwards so a deploy that
# silently broke it is caught here rather than during a payroll investigation.

set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE="docker compose -f docker-compose.prod.yml"

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
fail() { printf '\n\033[31mFAILED: %s\033[0m\n' "$1" >&2; exit 1; }

say "Checking required configuration"
for var in SECRET_KEY DB_PASSWORD; do
  if [ -z "${!var:-}" ]; then
    echo "  $var is not set."
    if [ ! -f .env ]; then
      echo "  There is no .env file. Copy the template first:"
      echo "    cp deploy/.env.production.example .env"
      exit 1
    fi
    grep -q "^${var}=.\+" .env || fail "$var is missing or empty in .env"
  fi
done
echo "  ok"

say "Pulling latest code"
git pull --ff-only

say "Building image"
$COMPOSE build backend

say "Applying migrations"
# Runs as a one-off container against the same image and the same database, so
# the schema is updated by the code that is about to use it. Not baked into the
# image: an image build has no DATABASE_URL, so migrate there would build a
# throwaway SQLite database and look like it had worked.
$COMPOSE run --rm backend python manage.py migrate --noinput

say "Seeding statutory rules"
# country and filing tables are what a payslip is calculated from. An empty one
# produces a plausible payslip with the wrong numbers, so this is not optional.
$COMPOSE run --rm backend python manage.py seed_country_rules
$COMPOSE run --rm backend python manage.py seed_filing_rules

say "Starting services"
$COMPOSE up -d

say "Waiting for the app to answer"
for attempt in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' https://hrcloudpay.com/api/schema/ || true)
  if [ "$code" = "200" ]; then
    echo "  healthy after ${attempt} attempt(s)"
    break
  fi
  [ "$attempt" = "30" ] && fail "the app did not answer after 30 attempts (last HTTP $code)"
  sleep 4
done

say "Verifying the audit chain"
$COMPOSE exec -T backend python manage.py verify_audit_chain

say "Done"
echo "  Site:   https://hrcloudpay.com"
echo "  Admin:  https://hrcloudpay.com/admin/"
echo
echo "  If the certificate did not issue, check that ports 80 and 443 are open"
echo "  in your host firewall AND that the domain's A record already points"
echo "  at this host. ACME has to reach the site over plain HTTP to validate."
echo
echo "  Note: a company registered through the public form is inactive until its"
echo "  emailed activation link is used. A fresh database has no SMTP"
echo "  configuration at all, so that mail goes to the container log instead of"
echo "  the recipient and the company can never be activated."
echo
echo "  Configure it at Platform Admin -> PLATFORM -> Email / SMTP and press Send"
echo "  test message. Do NOT set EMAIL_BACKEND: doing so replaces the"
echo "  database-driven backend with one that reads settings this project does not"
echo "  define, which leaves the server refusing its own connections with nothing"
echo "  in any log to explain it."
echo
echo "  To activate one by hand, create a platform superuser:"
echo "    $COMPOSE exec backend python manage.py createsuperuser"
echo "  (leave Company blank - a superuser attached to a tenant is refused by"
echo "  the platform's own endpoints)"