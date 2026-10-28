"""ZKTeco ADMS punch bridge: receive ADMS lines, forward them as API punches.

A terminal speaks ADMS (``PIN=1001\tDateTime=...\tStatus=0``) and has no way to
sign a JSON request. The API speaks JSON and authenticates terminals by device
key. This command sits between the two so the terminal keeps its native protocol
and the API keeps one ingestion path - matching policy, duplicate detection and
reconciliation all still happen server-side.

Run it beside the API (the default binds loopback only):

    python manage.py adt_bridge \
        --device-id ZK-001 \
        --device-key "<key shown when the terminal was created>"

The bridge holds that key, so anyone who can POST to it can record punches as
that terminal. It therefore binds to 127.0.0.1 by default. Binding to a LAN
address requires ``--token`` (sent as ``X-Bridge-Token`` or ``?token=``);
``--insecure`` is the explicit escape hatch for a network protected elsewhere.

Status codes are chosen for the sender's retry logic: 400 for a line that can
never be read, 502 when the API could not be reached (so a queued punch is
retried rather than silently lost), 200 once the API has made a decision -
including "needs reconciliation", which is a stored punch, not a failure.
"""
import hmac
import json
import os
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand, CommandError

# Tab form: PIN <TAB> timestamp <TAB> status [<TAB> verify mode]
ADMS_TAB_RE = re.compile(r'^(\S+)\t([^\t]+)\t(\d+)(?:\t(\d+))?$')
# Key-value form, tab- or space-separated. ``.*?`` plus the lookahead keeps the
# space inside "DateTime=2026-10-25 08:02:14" from swallowing later keys.
ADMS_KV_RE = re.compile(
    r'(PIN|DateTime|Status|VerifyMode)\s*=\s*(.*?)'
    r'(?=\s*(?:PIN|DateTime|Status|VerifyMode)\s*=|[\t\r\n]|$)',
    re.IGNORECASE,
)

DEFAULT_API_URL = 'http://127.0.0.1:8000'
MAX_BODY_BYTES = 64 * 1024
LOOPBACK_HOSTS = {'127.0.0.1', 'localhost', '::1'}

# ADMS status 0/1 are clock-in/clock-out. 2..5 are break/OT states that our
# punch types do not model; forwarding them as "out" (the old behaviour) closed
# a shift at lunch. "unknown" lets the server infer from the open attendance
# record instead of guessing.
PUNCH_TYPES = {0: 'in', 1: 'out'}


def parse_timestamp(value):
    """Parse the timestamp formats terminals emit, or return None."""
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        pass
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_adms_tab(raw):
    match = ADMS_TAB_RE.match(raw.strip())
    if not match:
        return None
    pin, timestamp, status, verify_mode = match.groups()
    punch_time = parse_timestamp(timestamp)
    if punch_time is None:
        return None
    return {
        'pin': pin,
        'punch_time': punch_time,
        'status': int(status),
        'verify_mode': int(verify_mode) if verify_mode is not None else 0,
    }


def parse_adms_kv(raw):
    data = {}
    for key, value in ADMS_KV_RE.findall(raw):
        data[key.lower()] = value.strip()
    pin = data.get('pin')
    timestamp = data.get('datetime')
    if not pin or not timestamp:
        return None
    punch_time = parse_timestamp(timestamp)
    if punch_time is None:
        return None
    try:
        status = int(data.get('status', 0))
        verify_mode = int(data.get('verifymode', 0))
    except ValueError:
        return None
    return {
        'pin': pin,
        'punch_time': punch_time,
        'status': status,
        'verify_mode': verify_mode,
    }


def parse_adms(raw):
    return parse_adms_tab(raw) or parse_adms_kv(raw)


def token_ok(token, header_value, query):
    """Whether a request may use a bridge that is exposed beyond loopback."""
    if not token:
        return True
    supplied = header_value or (parse_qs(query).get('token') or [''])[0]
    return hmac.compare_digest(str(supplied), token)


def ingest_punch(raw_payload, device_id, device_key, api_url=DEFAULT_API_URL,
                 timeout=10):
    """Parse one ADMS line and forward it to the punch endpoint.

    The terminal's PIN is sent as ``employee`` and the *server* decides what it
    identifies (enrolment template, employee code, or - only if that terminal
    opted in - a primary key). Resolving it here against employee_code would
    bypass the terminal's match policy and could attribute hours to the wrong
    person.
    """
    parsed = parse_adms(raw_payload)
    if parsed is None:
        return {
            'status': 'rejected',
            'retryable': False,
            'error': 'Unable to parse ADMS payload',
            'raw': raw_payload[:120],
        }
    if not device_id:
        return {
            'status': 'rejected',
            'retryable': False,
            'error': 'No device id configured; pass --device-id.',
            'raw': raw_payload[:120],
        }

    punch_type = PUNCH_TYPES.get(parsed['status'], 'unknown')
    punch = {
        'device_id': device_id,
        'employee': parsed['pin'],
        'punch_time': parsed['punch_time'].isoformat(),
        'punch_type': punch_type,
    }
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'HRCloudPay-ADMS-Bridge/1.0',
    }
    if device_key:
        headers['X-Biometric-Device-Key'] = device_key
    request = Request(
        '%s/api/biometrics/punch/' % api_url.rstrip('/'),
        data=json.dumps(punch).encode('utf-8'),
        headers=headers,
        method='POST',
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            raw_response = response.read().decode('utf-8', errors='replace')
            http_status = response.status
    except HTTPError as exc:
        try:
            error_body = json.loads(exc.read().decode('utf-8'))
        except Exception:
            error_body = {}
        return {
            'status': 'rejected',
            # A 4xx means the API will answer the same way next time; a 5xx is
            # worth retrying.
            'retryable': exc.code >= 500,
            'http_status': exc.code,
            'error': error_body.get('detail', 'API returned HTTP %s.' % exc.code),
            'employee': parsed['pin'],
            'punch_time': punch['punch_time'],
            'punch_type': punch_type,
        }
    except URLError as exc:
        return {
            'status': 'rejected',
            'retryable': True,
            'error': 'Bridge forward failed: %s' % exc.reason,
            'employee': parsed['pin'],
            'punch_time': punch['punch_time'],
            'punch_type': punch_type,
        }
    except Exception as exc:
        return {
            'status': 'rejected',
            'retryable': True,
            'error': 'Bridge forward failed: %s' % exc,
            'employee': parsed['pin'],
            'punch_time': punch['punch_time'],
            'punch_type': punch_type,
        }

    try:
        data = json.loads(raw_response) if raw_response else {}
    except ValueError:
        data = {}
    return {
        'status': data.get('status', 'unknown'),
        'retryable': False,
        'http_status': http_status,
        'matched_by': data.get('matched_by', ''),
        'error': data.get('detail', '') or data.get('error', ''),
        'employee': parsed['pin'],
        'punch_time': punch['punch_time'],
        'punch_type': punch_type,
    }


class _BridgeHandler(BaseHTTPRequestHandler):
    config = {}

    def log_message(self, format, *args):
        pass

    def _reply(self, status, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parts = urlsplit(self.path)
        if parts.path not in ('/punch', '/punch/'):
            self._reply(404, {'detail': 'not found'})
            return
        if not token_ok(self.config.get('token', ''),
                        self.headers.get('X-Bridge-Token', ''), parts.query):
            self._reply(401, {'detail': 'Invalid bridge token.'})
            return
        try:
            length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            length = 0
        if length <= 0:
            self._reply(400, {'detail': 'A request body is required.'})
            return
        if length > MAX_BODY_BYTES:
            self._reply(413, {'detail': 'Punch payload is too large.'})
            return

        raw = self.rfile.read(length).decode('utf-8', errors='replace')
        outcome = ingest_punch(
            raw,
            self.config.get('device_id', ''),
            self.config.get('device_key', ''),
            self.config.get('api_url', DEFAULT_API_URL),
        )
        if outcome.get('retryable'):
            status = 502
        elif outcome.get('status') == 'rejected' and not outcome.get('http_status'):
            status = 400
        else:
            # The API made a decision. That includes needs_reconciliation -
            # the punch is stored and a retry would only duplicate it.
            status = 200
        self._reply(status, outcome)


class Command(BaseCommand):
    """Django management command: ``python manage.py adt_bridge``."""

    help = (
        'Run the ZKTeco ADMS bridge. Receives ADMS punch lines on /punch/ and '
        'forwards them to /api/biometrics/punch/ with the terminal device key.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--bind', default='127.0.0.1',
                            help='Address to listen on (default: 127.0.0.1).')
        parser.add_argument('--port', type=int, default=8001,
                            help='Port for the bridge HTTP server (default: 8001).')
        parser.add_argument('--device-id', default=os.getenv('ADMS_BRIDGE_DEVICE_ID', ''),
                            help='Device ID of the terminal in HRCloudPay.')
        parser.add_argument('--device-key', default=os.getenv('ADMS_BRIDGE_DEVICE_KEY', ''),
                            help='API key of that terminal (required).')
        parser.add_argument('--api-url', default=os.getenv('ADMS_BRIDGE_API_URL', DEFAULT_API_URL),
                            help='Base URL of the HRCloudPay API (default: %s).' % DEFAULT_API_URL)
        parser.add_argument('--token', default=os.getenv('ADMS_BRIDGE_TOKEN', ''),
                            help='Require this token on every bridged request.')
        parser.add_argument('--insecure', action='store_true',
                            help='Allow a non-loopback bind without --token.')

    def handle(self, *args, **options):
        device_id = (options['device_id'] or '').strip()
        device_key = (options['device_key'] or '').strip()
        if not device_id or not device_key:
            raise CommandError(
                'Both --device-id and --device-key are required. Create the '
                'terminal under Biometric terminals and copy the key shown when '
                'it was created; the API rejects unauthenticated punches.'
            )

        bind = options['bind']
        token = (options['token'] or '').strip()
        if bind not in LOOPBACK_HOSTS and not token and not options['insecure']:
            raise CommandError(
                'Refusing to listen on %s without authentication: this bridge '
                're-sends punches with a valid device key. Pass --token and '
                'give the sender the same value, or keep the default loopback '
                'bind behind a reverse proxy. --insecure disables this check.'
                % bind
            )

        handler = type('ConfiguredBridgeHandler', (_BridgeHandler,), {'config': {
            'device_id': device_id,
            'device_key': device_key,
            'api_url': options['api_url'],
            'token': token,
        }})
        httpd = ThreadingHTTPServer((bind, options['port']), handler)
        self.stdout.write(
            'ADMS bridge listening on http://%s:%s/punch/ (device %s)'
            % (bind, options['port'], device_id))
        if not token:
            self.stdout.write(
                'No bridge token: any host that can reach this address may '
                'submit punches as that terminal.')
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            self.stdout.write('Bridge shutting down.')
        finally:
            httpd.server_close()
