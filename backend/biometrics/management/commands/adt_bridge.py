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

ADMS_TAB_RE = re.compile(
    r"^(\S+)\t([^\t]+)\t(\d+)\t(\d+)$"
)

ADMS_KV_RE = re.compile(
    r"(PIN|DateTime|Status|VerifyMode)\s*=\s*(\S+)",
    re.IGNORECASE,
)


def find_employee_by_pin(company_id: int, pin: str):
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
        return None
    employee = employees.first()
    return {
        "id": employee.id,
        "employee_code": employee.employee_code,
        "full_name": employee.full_name,
    }


def parse_adms_tab(raw: str) -> Optional[Dict[str, Any]]:
    m = ADMS_TAB_RE.match(raw.strip())
    if not m:
        return None
    pin, timestamp_str, status, verify_mode = m.groups()
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
        "status": int(status),
        "verify_mode": int(verify_mode),
    }


def parse_adms_kv(raw: str) -> Optional[Dict[str, Any]]:
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


def ingest_punch(raw_payload: str, company_id: int, device_id: str, device_key: str = "") -> Dict[str, Any]:
    parsed = parse_adms_tab(raw_payload) or parse_adms_kv(raw_payload)
    if parsed is None:
        return {
            "status": "rejected",
            "error": "Unable to parse ADMS payload",
            "raw": raw_payload[:120],
        }
    pin = parsed["pin"]
    punch_time = parsed["punch_time"]
    status = parsed["status"]
    employee = find_employee_by_pin(company_id, pin)
    if employee is None:
        return {
            "status": "needs_reconciliation",
            "error": f"No employee matched PIN '{pin}'",
            "matched_by": "pk",
            "employee_id": None,
        }
    punch_type = "in" if status == 0 else "out"
    punch_body = {
        "device_id": device_id,
        "employee": employee["employee_code"],
        "punch_time": punch_time.isoformat(),
        "punch_type": punch_type,
    }
    from urllib.request import Request, urlopen
    from urllib.error import URLError, HTTPError
    # Prefer an explicit API URL via env, fall back to the API server port
    # that is already running in this VM (3000).  The bridge runs in the same
    # process environment, so this is an easy way to wire it without configuring
    # Django settings for each deployment.
    api_base = os.getenv("ADM_BRIDGE_API_URL")
    if api_base:
        base = api_base.rstrip("/")
    else:
        # Default to the API server port already running in this VM.
        base = "http://127.0.0.1:3000"
    api_url = f"{base}/api/biometrics/punch/"
    try:
        body_bytes = json.dumps(punch_body).encode("utf-8")
        req = Request(api_url, data=body_bytes, method="POST")
        req.add_header("User-Agent", "ZKTeco-ADMS-Bridge/1.0")
        req.add_header("Content-Type", "application/json")
        if device_key:
            req.add_header("X-Biometric-Device-Key", device_key)
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


class Command(BaseCommand):
    """Django management command: ``python manage.py adt_bridge``."""

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
            help="Company email for employee lookup (e.g. 'demo@hrcloudpay.test'). "
                 "If omitted the first active company is used.",
        )
        parser.add_argument(
            "--device-key",
            type=str,
            default="",
            help="Default device key to forward to the API (overridden by request header).",
        )

    def handle(self, *args, **options):
        port = options["port"]
        tenant = options["tenant"]
        device_key = options.get("device_key", "") or ""

        from accounts.models import Company

        if tenant:
            try:
                company = Company.objects.get(email__iexact=tenant)
                company_id = company.id
            except Company.DoesNotExist:
                self.stderr.write(f"Company with email '{tenant}' not found.")
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
        _BridgeHandler.company_id = company_id
        _BridgeHandler.default_device_key = device_key

        self.stdout.write(f"Bridge active at http://0.0.0.0:{port}/punch/")

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            self.stdout.write("Bridge shutting down.")
            httpd.server_close()


class _BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_POST(self):
        if self.path != "/punch/":
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"detail": "not found"}).encode())
            return

        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length).decode("utf-8", errors="replace")

        device_key = self.headers.get("X-Biometric-Device-Key", "")
        # Fall back to the default device key from the command line if no header.
        if not device_key:
            device_key = getattr(self.__class__, "default_device_key", "")

        device_id = self.headers.get("X-Biometric-Device-Id", "unknown")

        from biometrics.management.commands.adt_bridge import ingest_punch

        outcome = ingest_punch(raw, self.company_id, device_id, device_key)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(outcome).encode())