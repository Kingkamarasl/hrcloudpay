from django.conf import settings
from django.http import JsonResponse
from .utils import client_ip

# Baseline policy. Tuned against what the built SPA actually loads:
#   - 'unsafe-inline' for styles is required because ~60 components set
#     element styles via style={{...}}; strict style-src would blank the UI.
#   - Google Fonts is the only external origin (see frontend_dist/index.html).
#   - No eval, no wasm, no plugins, and no framing (X-Frame-Options already
#     denies it; frame-ancestors is the modern equivalent and covers nested
#     frames that XFO misses).
CSP_DIRECTIVES = (
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com data:",
    "img-src 'self' data: blob:",
    # XHR/fetch targets. 'self' covers the same-origin /api base; the AI
    # provider calls are made server-side, never from the browser.
    "connect-src 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
)


def build_csp():
    override = getattr(settings, 'CSP_DIRECTIVES', None)
    if override is not None:
        return override if isinstance(override, str) else '; '.join(override)
    return '; '.join(CSP_DIRECTIVES)


class RequestSecurityMiddleware:
    def __init__(self, get_response): self.get_response = get_response
    def __call__(self, request):
        limit = getattr(settings, 'API_REQUEST_MAX_BYTES', 5*1024*1024)
        if request.path.startswith('/api/') and int(request.META.get('CONTENT_LENGTH') or 0) > limit:
            return JsonResponse({'detail':'Request payload exceeds the configured security limit.'},status=413)
        response = self.get_response(request)
        response['X-Content-Type-Options'] = 'nosniff'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['X-Frame-Options'] = 'DENY'
        # Content-Security-Policy was the one missing layer here: every other
        # header above is set, and this is the main XSS mitigation for an app
        # that renders user documents, AI output, and audit metadata.
        # Report-only is supported so a policy change can be staged before it
        # starts blocking anything.
        policy = build_csp()
        if getattr(settings, 'CSP_REPORT_ONLY', False):
            response['Content-Security-Policy-Report-Only'] = policy
        else:
            response['Content-Security-Policy'] = policy
        if getattr(settings, 'CSP_INCLUDE_REPORT_URI', False):
            report_uri = getattr(settings, 'CSP_REPORT_URI', '')
            if report_uri:
                suffix = f"report-uri {report_uri}"
                key = 'Content-Security-Policy-Report-Only' if getattr(settings, 'CSP_REPORT_ONLY', False) else 'Content-Security-Policy'
                response[key] = f'{response[key]}; {suffix}'
        return response
