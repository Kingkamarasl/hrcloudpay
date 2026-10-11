#!/bin/sh
# HRCloudPay - scheduled maintenance loop.
#
# Why this file exists
# -------------------
# `run_hr_automations`, `accrue_leave`, `check_document_expiry`,
# `process_contract_expiries`, `generate_statutory_filings`,
# `rotate_encrypted_secrets` and `run_due_integrations` are all implemented,
# all tested, and all correct. Nothing ran them.
#
# Django has no built-in scheduler, so every one of those commands was
# reachable only by someone SSHing into the server and typing it. The
# consequence is worse than a missing feature: the product advertised
# proactive HR alerts - expiring contracts, missing documents, statutory
# filing deadlines - and in production the only way to receive one was to
# open the Workflows page and press "Run now". A customer could subscribe
# to nothing and believe they were covered.
#
# Cron inside the backend container was rejected on purpose. A shell loop in
# a sidecar that reuses the same image needs no new dependency, survives a
# `docker compose up -d` restart, and keeps the web process free of anything
# that could block a request.
#
# How it decides what is due
# --------------------------
# Each command declares a minimum interval. A stamp file records when it last
# ran; the command runs when the stamp is older than its interval. That keeps
# the loop itself trivial (`SCHEDULER_TICK_SECONDS`) while still letting
# integrations tick hourly and HR automation tick daily.
#
# Two properties worth keeping:
#
#   * `set -e` is deliberately NOT used. One failing command must not take the
#     loop down with it, or a single transient database blip at 03:00 silently
#     stops every scheduled job until someone notices and restarts the stack.
#   * A failed command does not write its stamp, so it is retried on the next
#     tick instead of being marked done.

set -u

INTERVAL="${SCHEDULER_TICK_SECONDS:-300}"
STAMP_DIR="${SCHEDULER_STAMP_DIR:-/var/lib/hrcloudpay/scheduler}"
MANAGE="python manage.py"

mkdir -p "$STAMP_DIR"

log() {
    printf '%s scheduler: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

# run_every <command> <minimum-interval-seconds>
run_every() {
    _cmd="$1"
    _min="$2"
    _stamp="$STAMP_DIR/$_cmd"

    _now=$(date -u '+%s')
    if [ -f "$_stamp" ]; then
        _last=$(cat "$_stamp" 2>/dev/null || echo 0)
        if [ $((_now - _last)) -lt "$_min" ]; then
            return 0
        fi
    fi

    log "running $_cmd"
    if $MANAGE "$_cmd"; then
        log "$_cmd ok"
        echo "$_now" > "$_stamp"
    else
        # No stamp: the next tick tries again rather than waiting a full day.
        log "$_cmd FAILED - will retry on the next tick"
    fi
}

log "loop starting (tick ${INTERVAL}s)"

# Ordered cheapest-first so a slow database is still serving the cheap checks
# while it is degraded, rather than the whole batch failing on the first call.
run_every run_due_integrations      3600
run_every run_hr_automations        86400
run_every accrue_leave              86400
run_every check_document_expiry     86400
run_every process_contract_expiries 86400
run_every generate_statutory_filings 86400
run_every rotate_encrypted_secrets  604800

log "tick complete, sleeping ${INTERVAL}s"
sleep "$INTERVAL"