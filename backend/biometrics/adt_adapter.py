"""
ZKTeco ADMS listener bridge.

Accepts punch records from ZKTeco terminals speaking the ADMS/iClock protocol
(tab-separated or key-value lines) and re-posts them to our /api/biometrics/punch/
endpoint so they enter the normal reconciliation flow.

Usage (Django management command):
    python manage.py adt_bridge --port 8001 --tenant acme

The bridge expects to be configured with a tenant company subdomain so it can
look up the correct employee records.  When ``--tenant`` is omitted it attempts
to resolve the current Django tenant (useful when run from ``manage.py`` in a
multi-tenant setup).
"""

from http.server import BaseHTTPRequestHandler, HTTPServer

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone as tz

# ---------------------------------------------------------------------------
# ADMS payload formats
# ---------------------------------------------------------------------------

# Tab-separated:  "PIN\tTimestamp\tStatus\tVerifyMode"
# Example:        "1001\t2025-09-02 08:30:00\t0\t1"
# KV lines:       "PIN=1001 DateTime=2025-09-02 08:30:00 Status=0 VerifyMode=1"

ADMS_TAB_RE = re.compile(
    r"^(\S+)\t([^\t]+)\t(\d+)\t(\d+)$"
)

ADMS_KV_RE = re.compile(
    r"(PIN|DateTime|Status|VerifyMode)\s*=\s*(\S+)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Employee lookup
# ---------------------------------------------------------------------------

def find_employee_by_pin(company_id: int, pin: str):
    """
    Resolve a vendor PIN to our Employee record.

    The bridge is configured so that the terminal's user number (PIN) is set to
    the employee's HRCloudPay ``employee_code`` at enrolment time.  Because
    ``employee_code`` is DB-unique per company, this mapping is unambiguous.
    """
    from employees.models import Employee

    try:
        employees = Employee.objects.filter(
            company_id=company_id, employee_code=pin
        )
    except Exception:
        return None

    if not employees.exists():
        return None

    if employees.count() > 1:
        # employee_code has a unique constraint per company — guard against
        # data corruption rather than silently picking one.
        return None

    employee = employees.first()

    return {
        "id": employee.id,
        "employee_code": employee.employee_code,
        "full_name": employee.full_name,
    }


# ---------------------------------------------------------------------------
# Payload parsers
# ---------------------------------------------------------------------------

def parse_adms_tab(raw: str) -> Optional[Dict[str, Any]]:
    """Parse tab-separated ADMS line: PIN\tTimestamp\tStatus\tVerifyMode."""
    m = ADMS_TAB_RE.match(raw.strip())
    if not m:
        return None
    pin, timestamp_str, status, verify_mode = m.groups()
    # Normalise timestamp.
    try:
        punch_time = datetime.fromisoformat(
            timestamp_str.replace(" ", "T").replace("Z", "+00:00")
        )
    except (ValueError, TypeError):
        punch_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        punch_time = tz.make_aware(punch_time)

    return {
        "pin": pin,
        "punch_time": punch_time,
        "status": int(status),   # 0=in, 1=out per ZKTeco convention
        "verify_mode": int(verify_mode),
    }


def parse_adms_kv(raw: str) -> Optional[Dict[str, Any]]:
    """Parse key-value ADMS lines: PIN=1001 DateTime=... Status=... VerifyMode=..."""
    data = {}
    for key, value in ADMS_KV_RE.findall(raw):
        key_lower = key.lower()
        if key_lower in ("pin", "status", "verify_mode"):
            data[key_lower] = value
        elif key_lower == "datetime":
            data["timestamp"] = value

    if "pin" not in data or "timestamp" not in data:
        return None

    try:
        status = int(data["status"])
    except ValueError:
        return None

    try:
        punch_time = datetime.fromisoformat(
            data["timestamp"].replace(" ", "T").replace("Z", "+00:00")
        )
    except (ValueError, TypeError):
        return None

    return {
        "pin": data["pin"],
        "punch_time": punch_time,
        "status": status,
    }


# ---------------------------------------------------------------------------
# Core bridge logic
# ---------------------------------------------------------------------------

def ingest_punch(raw_payload: str, company_id: int, device_id: str) -> Dict[str, Any]:
    """
    Parse one ADMS payload and forward it to our punch endpoint.

    Returns a dict describing the outcome, mirroring what ``_record_punch``
    would produce.
    """
    # Try tab format first; fall back to KV.
    parsed = parse_adms_tab(raw_payload) or parse_adms_kv(raw_payload)
    if parsed is None:
        return {
            "status": "rejected",
            "error": "Unable to parse ADMS payload",
            "raw": raw_payload[:120],
        }

    pin = parsed["pin"]
    punch_time = parsed["punch_time"]
    status = parsed["status"]  # 0 = in, 1 = out

    # Resolve employee.
    employee = find_employee_by_pin(company_id, pin)
    if employee is None:
        return {
            "status": "needs_reconciliation",
            "error": f"No employee matched PIN '{pin}'",
            "matched_by": "pk",
            "employee_id": None,
        }

    # Map ZKTeco status to our punch_type.
    punch_type = "in" if status == 0 else "out"

    # Build the payload our endpoint expects.
    punch_body = {
        "device_id": device_id,
        "employee": employee["employee_code"],  # our identifier, not the PIN
        "punch_time": punch_time.isoformat(),
        "punch_type": punch_type,
    }

    # Forward to our API using urllib (stdlib, no extra dependency).
    from urllib.request import Request, urlopen
    from urllib.error import URLError, HTTPError

    # Use the SITE_URL setting if it looks like a full URL, otherwise build
    # from the 127.0.0.1 host this bridge runs on.
    site_url = getattr(settings, "SITE_URL", None)
    if site_url and site_url.startswith("http"):
        base = site_url.rstrip("/")
    else:
        base = "http://127.0.0.1"

    api_url = f"{base}/api/biometrics/punch/"

    try:
        req = Request(api_url, json=punch_body, method="POST")
        req.add_header("User-Agent", "ZKTeco-ADMS-Bridge/1.0")
        resp = urlopen(req, timeout=10)
        raw_resp = resp.read().decode("utf-8")
        data = json.loads(raw_resp) if raw_resp else {}
    except HTTPError as exc:
        try:
            error_body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            error_body = {"detail": str(exc)}
        return {
            "status": "rejected",
            "error": f"Bridge forward HTTP {exc.code}: {error_body}",
            "raw": raw_payload[:120],
        }
    except URLError as exc:
        return {
            "status": "rejected",
            "error": f"Bridge forward failed: {exc.reason}",
            "raw": raw_payload[:120],
        }
    except Exception as exc:
        return {
            "status": "rejected",
            "error": f"Bridge forward unexpected: {exc}",
            "raw": raw_payload[:120],
        }

    # Mirror the shape our internal _record_punch returns.
    outcome = data.get("status", "unknown")
    matched_by = data.get("matched_by", "")
    error = data.get("error", "")

    return {
        "status": outcome,
        "matched_by": matched_by,
        "error": error,
        "employee": employee["employee_code"],
        "punch_time": punch_time.isoformat(),
        "punch_type": punch_type,
    }


# ---------------------------------------------------------------------------
# HTTP request handler (used by the management command's server)
# ---------------------------------------------------------------------------

class _BridgeHandler(BaseHTTPRequestHandler):
    """Minimal handler that receives ADMS payloads and forwards them."""

    def log_message(self, format, *args):  # noqa: ANN001
        # Suppress default stderr logging; let the management command capture it.
        pass

    def do_POST(self):  # type: ignore[override]
        if self.path != "/punch/":
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"detail": "not found"}).encode())
            return

        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length).decode("utf-8", errors="replace")

        # The company_id is captured from the outer scope (management command).
        # We delegate to the pure-function logic above.
        from biometrics.adt_adapter import ingest_punch

        # The device_id comes from the terminal's configuration; we use a
        # placeholder here because the bridge is meant to be run per-tenant
        # where one device is typical, or the caller can inject it.
        device_id = self.headers.get("X-Biometric-Device-Id", "unknown")

        outcome = ingest_punch(raw, self.company_id, device_id)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(outcome).encode())


# ---------------------------------------------------------------------------
# Django management command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = (
        "Run the ZKTeco ADMS bridge server.  Receives ADMS punch payloads on"
        " ``/punch/`` and forwards them to our /api/biometrics/punch/ endpoint."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--port",
            type=int,
            default=8001,
            help="Port for the bridge HTTP server (default: 8001)",
        )
        parser.add_argument(
            "--tenant",
            type=str,
            default=None,
            help="Company subdomain for employee lookup (e.g. 'acme'). "
                 "If omitted the first active company is used.",
        )

    def handle(self, *args, **options):
        port = options["port"]
        tenant = options["tenant"]

        # Resolve the company we are bridging for.
        from accounts.models import Company

        if tenant:
            try:
                company = Company.objects.get(subdomain=tenant)
                company_id = company.id
            except Company.DoesNotExist:
                self.stderr.write(f"Company with subdomain '{tenant}' not found.")
                return
        else:
            try:
                company = Company.objects.get(is_active=True)
                company_id = company.id
            except Company.DoesNotExist:
                self.stderr.write("No active company found.")
                return

        self.stdout.write(
            f"ZKTeco ADMS bridge listening on port {port} (tenant: {company.name}, id={company_id})"
        )

        httpd = HTTPServer(("0.0.0.0", port), _BridgeHandler)
        # Attach company_id to the handler class so request handlers can use it.
        _BridgeHandler.company_id = company_id

        self.stdout.write(f"Bridge active at http://0.0.0.0:{port}/punch/")

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            self.stdout.write("Bridge shutting down.")
            httpd.server_close()