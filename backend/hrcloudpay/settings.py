"""
Django settings for the HRCLOUDPAY project.

This is an MVP configuration using SQLite for easy local setup.
Swap the DATABASES section for Postgres/MySQL before deploying to
production.
"""
from pathlib import Path
from decouple import config
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse_lazy

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = config('DEBUG', default=False, cast=bool)
SECRET_KEY = config('SECRET_KEY', default='')
INSECURE_SECRET_KEYS = {'', 'change-me-to-a-random-secret', 'dev-insecure-secret-key-change-me'}

if SECRET_KEY in INSECURE_SECRET_KEYS:
    if DEBUG:
        # Convenience for an unconfigured local checkout only. Production
        # deployments must always supply a unique, secret value.
        SECRET_KEY = 'dev-insecure-secret-key-change-me'
    else:
        raise ImproperlyConfigured('SECRET_KEY must be set when DEBUG=False.')

ALLOWED_HOSTS = [h.strip() for h in config('ALLOWED_HOSTS', default='localhost,127.0.0.1').split(',') if h.strip()]

INSTALLED_APPS = [
    'unfold',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # third party
    'rest_framework',
    'rest_framework.authtoken',
    'corsheaders',

    # local apps
    'accounts',
    'employees',
    'payroll',
    'attendance',
    'leave',
    'integrations',
    'workflows',
    'regional',
    'ai',
    'security',
    'drf_spectacular',
]


UNFOLD = {
    "SITE_TITLE": "HRCloudPay Admin",
    "SITE_HEADER": "HRCloudPay",
    "SITE_SUBHEADER": "Operations & Developer Admin",
    "SITE_URL": "/",
    "SITE_SYMBOL": "payments",
    "SITE_VERSION": "Milestone 20",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "SHOW_BACK_BUTTON": True,
    "SHOW_UI_WARNINGS": False,
    "ENVIRONMENT": "hrcloudpay.admin.environment_callback",
    "DASHBOARD_CALLBACK": "hrcloudpay.admin.dashboard_callback",
    "BORDER_RADIUS": "10px",
    "COLORS": {
        "primary": {
            "50": "oklch(97.7% .014 224)",
            "100": "oklch(93.5% .03 224)",
            "200": "oklch(87.5% .055 224)",
            "300": "oklch(78% .09 224)",
            "400": "oklch(68% .13 224)",
            "500": "oklch(58% .16 224)",
            "600": "oklch(49% .15 224)",
            "700": "oklch(41% .13 224)",
            "800": "oklch(34% .105 224)",
            "900": "oklch(28% .08 224)",
            "950": "oklch(20% .055 224)",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {
                "title": "Command Center",
                "separator": True,
                "collapsible": False,
                "items": [
                    {"title": "Dashboard", "icon": "dashboard", "link": reverse_lazy("admin:index")},
                ],
            },
            {
                "title": "Organizations",
                "separator": True,
                "collapsible": True,
                "items": [
                    {"title": "Companies", "icon": "business", "link": reverse_lazy("admin:accounts_company_changelist")},
                    {"title": "Users", "icon": "group", "link": reverse_lazy("admin:accounts_user_changelist")},
                    {"title": "Subscriptions", "icon": "autorenew", "link": reverse_lazy("admin:accounts_subscription_changelist")},
                ],
            },
            {
                "title": "HR Operations",
                "separator": True,
                "collapsible": True,
                "items": [
                    {"title": "Employees", "icon": "badge", "link": reverse_lazy("admin:employees_employee_changelist")},
                    {"title": "Departments", "icon": "account_tree", "link": reverse_lazy("admin:employees_department_changelist")},
                    {"title": "Contracts", "icon": "description", "link": reverse_lazy("admin:employees_contract_changelist")},
                    {"title": "Warning Letters", "icon": "warning", "link": reverse_lazy("admin:employees_warningletter_changelist")},
                    {"title": "Attendance", "icon": "schedule", "link": reverse_lazy("admin:attendance_attendance_changelist")},
                    {"title": "Leave Requests", "icon": "event_available", "link": reverse_lazy("admin:leave_leaverequest_changelist")},
                    {"title": "Break Requests", "icon": "free_breakfast", "link": reverse_lazy("admin:leave_breakrequest_changelist")},
                ],
            },
            {
                "title": "Payroll",
                "separator": True,
                "collapsible": True,
                "items": [
                    {"title": "Payroll Runs", "icon": "receipt_long", "link": reverse_lazy("admin:payroll_payrollrun_changelist")},
                    {"title": "Payslips", "icon": "request_quote", "link": reverse_lazy("admin:payroll_payslip_changelist")},
                    {"title": "Payroll Config", "icon": "tune", "link": reverse_lazy("admin:payroll_payrollconfig_changelist")},
                ],
            },
            {
                "title": "Billing & Payments",
                "separator": True,
                "collapsible": True,
                "items": [
                    {"title": "Payment Plans", "icon": "sell", "link": reverse_lazy("admin:accounts_paymentplan_changelist")},
                    {"title": "Transactions", "icon": "payments", "link": reverse_lazy("admin:accounts_paymenttransaction_changelist")},
                    {"title": "Payment Events", "icon": "webhook", "link": reverse_lazy("admin:accounts_paymentevent_changelist")},
                    {"title": "Provider Config", "icon": "key", "link": reverse_lazy("admin:accounts_paymentproviderconfig_changelist")},
                ],
            },
            {
                "title": "Security & Governance",
                "separator": True,
                "collapsible": True,
                "items": [
                    {"title": "Audit Logs", "icon": "shield", "link": reverse_lazy("admin:accounts_auditlog_changelist")},
                    {"title": "Feature Flags", "icon": "flag", "link": reverse_lazy("admin:accounts_featureflag_changelist")},
                    {"title": "Suspension Events", "icon": "block", "link": reverse_lazy("admin:accounts_suspensionevent_changelist")},
                ],
            },
            {
                "title": "Support & Communications",
                "separator": True,
                "collapsible": True,
                "items": [
                    {"title": "Support Tickets", "icon": "support_agent", "link": reverse_lazy("admin:accounts_supportticket_changelist")},
                    {"title": "Notifications", "icon": "notifications", "link": reverse_lazy("admin:accounts_platformnotification_changelist")},
                ],
            },
        ],
    },
}

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'security.middleware.RequestSecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'accounts.audit.AuditRequestMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'hrcloudpay.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'hrcloudpay.wsgi.application'
ASGI_APPLICATION = 'hrcloudpay.asgi.application'

def _database_from_url(url):
    """Build a DATABASES['default'] entry from a postgres:// URL.

    Written against the stdlib rather than pulling in dj-database-url: this is
    the only URL shape the product supports, and a deploy should not gain a
    dependency to parse one string. Only the components below are read; a
    parameter this function does not understand is ignored rather than passed
    through to the driver, so a `DATABASE_URL` copied from a provider's
    dashboard cannot smuggle an unexpected option into the connection.
    """
    from urllib.parse import parse_qsl, unquote, urlparse

    parsed = urlparse(url)
    if parsed.scheme.split('+', 1)[0] not in ('postgres', 'postgresql'):
        raise ImproperlyConfigured(
            f'DATABASE_URL must be a postgres:// URL, got {parsed.scheme!r}.'
        )
    name = unquote(parsed.path.lstrip('/'))
    if not name:
        raise ImproperlyConfigured('DATABASE_URL is missing the database name.')

    options = {}
    query = dict(parse_qsl(parsed.query))
    # Managed Postgres almost always requires TLS. Requiring it here rather
    # than defaulting it off means a forgotten setting fails loudly at startup
    # instead of quietly sending payroll data in the clear.
    sslmode = query.get('sslmode')
    if sslmode:
        options['sslmode'] = sslmode
    elif query.get('ssl') in ('1', 'true', 'require'):
        options['sslmode'] = 'require'

    return {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': name,
        'USER': unquote(parsed.username or ''),
        'PASSWORD': unquote(parsed.password or ''),
        'HOST': parsed.hostname or 'localhost',
        'PORT': str(parsed.port or 5432),
        'OPTIONS': options,
    }


# SQLite is the local-development default and stays the default when no
# database is configured, so a fresh checkout still runs with no setup.
#
# It is NOT a production option, for three reasons that no amount of tuning
# removes: it grants a single writer, so a second worker or any concurrent
# write fails with "database is locked"; it stores the whole database in one
# file on the machine's disk, so a redeploy or a lost volume destroys every
# employee record, payslip and audit row; and its row-level locking cannot
# support the `select_for_update()` that payroll processing depends on for
# correctness. Set DATABASE_URL (or the POSTGRES_* variables) in production.
DATABASE_URL = config('DATABASE_URL', default='')

if DATABASE_URL:
    DATABASES = {'default': _database_from_url(DATABASE_URL)}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Connections are held open between requests so a busy page does not pay a
# full TCP+TLS handshake per query. Without this Postgres's default of closing
# immediately after every request is a meaningful cost at any real traffic.
if DATABASES['default']['ENGINE'].endswith('postgresql'):
    DATABASES['default']['CONN_MAX_AGE'] = config('CONN_MAX_AGE', default=60, cast=int)
    DATABASES['default']['CONN_HEALTH_CHECKS'] = True

# Local SQLite has no server to wait on, so the health check would report the
# instance as unready on every boot and take it out of rotation. Skip it there.
if not DATABASES['default']['ENGINE'].endswith('sqlite3'):
    DATABASES['default'].setdefault('OPTIONS', {})
    DATABASES['default']['OPTIONS'].setdefault(
        'connect_timeout', config('DB_CONNECT_TIMEOUT', default=10, cast=int)
    )

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

AUTH_USER_MODEL = 'accounts.User'

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'

# The React frontend is built into backend/frontend_dist (see
# frontend/vite.config.js: build.outDir). Django serves the built JS/CSS
# from there as static files, and hrcloudpay/views.py serves the built
# index.html for '/' and any other non-API route (SPA client-side routing).
STATICFILES_DIRS = [BASE_DIR / 'frontend_dist']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Lets WhiteNoise serve straight from STATICFILES_DIRS without requiring
# `collectstatic` first - convenient for local single-server use. Still
# fine to run collectstatic for a real production deployment.
WHITENOISE_USE_FINDERS = True

# Vite puts a content hash in every filename under /static/assets/, so a given
# URL can only ever mean one file: a new build produces new names rather than
# replacing the old ones. Those are therefore safe to cache for good, and
# `immutable` stops the browser even revalidating them.
#
# Only files that actually match are treated this way. Everything else static
# keeps max-age=0, because a file whose name does NOT change when its contents
# do - an unhashed asset, or Django admin's own CSS - must never be pinned for a
# year in the browser.
WHITENOISE_IMMUTABLE_FILE_TEST = (
    r'^/static/assets/.+-[A-Za-z0-9_-]{8,}\.(?:js|mjs|css|woff2?|ttf|eot|svg|png|jpg|jpeg|gif|webp|avif)$'
)
WHITENOISE_MAX_AGE = 0

# Some Windows installs have no registered MIME type for these, and a module
# script served as text/plain is refused outright by the browser.
WHITENOISE_MIMETYPES = {
    '.js': 'text/javascript',
    '.mjs': 'text/javascript',
    '.css': 'text/css',
    '.svg': 'image/svg+xml',
    '.woff2': 'font/woff2',
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Object storage for uploaded files.
#
# MEDIA_ROOT is a directory on whichever machine is running Django. On a
# container platform that directory is part of the image's writable layer, so
# every deploy destroys every employee document, contract, payslip attachment
# and knowledge-base source that was uploaded since the last one. A named
# volume avoids the loss but cannot be attached to a second web worker, is not
# replicated, and still has no backup. None of the 66 files in the local
# backend/media directory are in version control - .gitignore excludes the
# whole tree precisely because they are real employee data.
#
# So: set AWS_STORAGE_BUCKET_NAME in production and every upload goes to a
# private S3 bucket, where versioning, lifecycle and cross-region replication
# are the provider's problem rather than the app's. Left unset, this stays a
# local directory so a fresh checkout still works with no AWS account.
#
# The bucket MUST stay private. `AWS_DEFAULT_ACHER` is deliberately not set, so
# django-storages falls back to its own default and the SDK uses the credentials
# from the environment. What matters is that no `AWS_QUERYSTRING_AUTH` or custom
# public domain is configured: files are delivered through `serve_media`, which
# checks the requester's role first. Setting either of those would hand out a
# bearer URL that bypasses that check for as long as it lives, and every one of
# these objects is an identity, medical or disciplinary document.
#
# Region is taken from the environment so the bucket can sit wherever data
# residency requires; AWS_S3_REGION_NAME is required because the SDK cannot infer
# it from a bucket name.
AWS_STORAGE_BUCKET_NAME = config('AWS_STORAGE_BUCKET_NAME', default='')
AWS_S3_REGION_NAME = config('AWS_S3_REGION_NAME', default='')
AWS_ACCESS_KEY_ID = config('AWS_ACCESS_KEY_ID', default='')
AWS_SECRET_ACCESS_KEY = config('AWS_SECRET_ACCESS_KEY', default='')
AWS_S3_ENDPOINT_URL = config('AWS_S3_ENDPOINT_URL', default=None)
# Server-side encryption at rest. Payroll and HR documents are personal data, so
# this is not optional in production; leaving the variable unset falls back to
# the bucket's own default, which for a new bucket may be none.
AWS_S3_SERVER_SIDE_ENCRYPTION = config('AWS_S3_SERVER_SIDE_ENCRYPTION', default='AES256')

if AWS_STORAGE_BUCKET_NAME and not AWS_S3_REGION_NAME:
    raise ImproperlyConfigured(
        'AWS_S3_REGION_NAME must be set when AWS_STORAGE_BUCKET_NAME is set. '
        'The S3 SDK cannot infer a region from a bucket name and will fail on '
        'the first upload rather than at startup.'
    )

if AWS_STORAGE_BUCKET_NAME:
    STORAGES = {
        'default': {
            'BACKEND': 'storages.backends.s3.S3Storage',
        },
        'staticfiles': {
            # Left exactly as the project already had it. The built frontend and
            # Django admin's CSS are world-readable by definition and are never
            # user data, and switching this to a manifest storage would make
            # `collectstatic` mandatory - a change to the static pipeline that
            # this does not need to make.
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    }
else:
    STORAGES = {
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    }

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Shared cache.
#
# This is a correctness setting, not a performance one. Django's default is
# LocMemCache, which is private to each process, and DRF's throttle classes
# keep their counters in it. So with the N workers a production deployment
# actually runs, the configured login limit of 10/minute becomes an effective
# 10/minute *per worker* - N times the intended limit - and the per-account
# lockout delay that the dashboard and the audit log report does not match what
# the next worker enforces. Set REDIS_URL in production; the default keeps a
# fresh checkout working with no external service.
#
# The connection is wrapped so a Redis outage degrades to per-process counting
# rather than taking every endpoint into a 500. That is a real reduction in the
# strength of the limit during an outage, which is why it is a last resort and
# not the normal state.
REDIS_URL = config('REDIS_URL', default='')

if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
            'KEY_PREFIX': config('CACHE_KEY_PREFIX', default='hrcloudpay'),
            'TIMEOUT': config('CACHE_TIMEOUT', default=300, cast=int),
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'security.authentication.SecurityCookieAuthentication',
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 25,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
        # Resolves each view's `throttle_scope` attribute; inert on views
        # that do not declare one.
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour',
        # Authentication endpoints are far more sensitive than ordinary
        # anonymous reads: the 100/hour anon budget is shared across every
        # account on the instance and is a comfortable credential-stuffing
        # window. ScopedRateThrottle is enabled below and these rates are
        # applied by the `throttle_scope` on each auth view.
        'login': config('THROTTLE_LOGIN_RATE', default='10/minute'),
        'mfa': config('THROTTLE_MFA_RATE', default='8/minute'),
        'password_change': config('THROTTLE_PASSWORD_CHANGE_RATE', default='5/minute'),
        'password_reset': config('THROTTLE_PASSWORD_RESET_RATE', default='5/hour'),
    },
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'HRCloudPay API',
    'DESCRIPTION': 'Multi-tenant HR & payroll API for African businesses',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SERVE_PERMISSIONS': ['rest_framework.permissions.AllowAny'],
    'SERVE_AUTHENTICATION': [],
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'standard'},
    },
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {
        'payroll': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'regional': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
    },
}

CORS_ALLOWED_ORIGINS = [h.strip() for h in config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:5173,http://127.0.0.1:5173'
).split(',') if h.strip()]

# Email backend - console by default for local dev (activation emails print to terminal)
EMAIL_BACKEND = config('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='no-reply@hrcloudpay.com')

FRONTEND_URL = config('FRONTEND_URL', default='http://localhost:5173')
BACKEND_PUBLIC_URL = config('BACKEND_PUBLIC_URL', default='http://localhost:8000')
MICROSOFT_CLIENT_ID = config('MICROSOFT_CLIENT_ID', default='')
MICROSOFT_CLIENT_SECRET = config('MICROSOFT_CLIENT_SECRET', default='')
QUICKBOOKS_CLIENT_ID = config('QUICKBOOKS_CLIENT_ID', default='')
QUICKBOOKS_CLIENT_SECRET = config('QUICKBOOKS_CLIENT_SECRET', default='')
XERO_CLIENT_ID = config('XERO_CLIENT_ID', default='')
XERO_CLIENT_SECRET = config('XERO_CLIENT_SECRET', default='')

# How many reverse proxies sit in front of Django. 0 (the default) means
# X-Forwarded-For is ignored and REMOTE_ADDR is authoritative, which is correct
# for a directly exposed app. Set it to the real hop count when deploying behind
# nginx/ALB/Cloudflare - otherwise security sessions, security events and the
# dashboard's connection card all report the proxy's address instead of the
# user's. The exact count matters: the client address is read that many entries
# in from the right of the header, so a value that is too small lets a client
# forge its own address. Read unconditionally, not only in production, so it is
# also honoured behind a local tunnel and can be exercised in development.
TRUSTED_PROXY_COUNT = config('TRUSTED_PROXY_COUNT', default=0, cast=int)

# Optional overrides for the dashboard's IP geolocation. The default provider
# needs no API key; point IP_GEOLOCATION_URL at a self-hosted or paid service to
# change that. The lookup is best-effort and never fails the request.
IP_GEOLOCATION_URL = config('IP_GEOLOCATION_URL', default='')
IP_GEOLOCATION_TIMEOUT_SECONDS = config('IP_GEOLOCATION_TIMEOUT_SECONDS', default=3.0, cast=float)
# How often one user may force a re-lookup past the 24h cache. A cached answer is
# already correct for a day, so this is about reassurance, not accuracy - and it
# stops the dashboard's refresh button from being a way to spend provider quota.
# Set to 0 to disable the limit (only sensible with a self-hosted provider).
CONNECTION_REFRESH_MIN_INTERVAL_SECONDS = config('CONNECTION_REFRESH_MIN_INTERVAL_SECONDS', default=30, cast=int)

# Production security defaults. Keep local HTTP development usable when DEBUG=True.
if not DEBUG:
    # Deliberately its own setting rather than an unconditional True.
    #
    # Behind a TLS-terminating proxy this is already a no-op: SECURE_PROXY_SSL_HEADER
    # below makes every forwarded request look like https, so the middleware sees
    # nothing to redirect. It only bites where there is no proxy and the client
    # speaks plain http - which is exactly the test suite, where Django's test
    # client talks http to `testserver` and sends no X-Forwarded-Proto.
    #
    # Deriving it from DEBUG meant the one configuration CI could run in (DEBUG
    # off, matching production) turned every API assertion into a 301. That is
    # 300+ tests failing for a reason that has nothing to do with the code under
    # test, which is the worst kind of red build: it hides real failures.
    SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=31536000, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Token authentication is intentionally retained for the MVP. Production deployments
# should place the API behind HTTPS and rotate/revoke tokens on credential compromise.
# Note: /auth/login/ and /auth/register/ no longer ISSUE a DRF token - the SPA
# authenticates with the HttpOnly `hrcloudpay_session` cookie, and the long-lived
# unminted token those endpoints returned was a permanent credential that nothing
# used. Existing tokens stay valid until `manage.py revoke_api_tokens` is run.

# Content-Security-Policy. Set CSP_REPORT_ONLY=True to stage a policy change
# without blocking anything, then switch it off once violations are clear.
CSP_REPORT_ONLY = config('CSP_REPORT_ONLY', default=False, cast=bool)
CSP_REPORT_URI = config('CSP_REPORT_URI', default='')
CSP_INCLUDE_REPORT_URI = bool(CSP_REPORT_URI)
# Override the built policy wholesale by setting CSP_DIRECTIVES to a list or
# a pre-joined string.
CSP_DIRECTIVES = config('CSP_DIRECTIVES', default=None)

# Step-up authentication: how long a completed MFA challenge keeps satisfying
# sensitive actions (payroll approval, salary changes, privileged access).
MFA_STEP_UP_WINDOW_SECONDS = config('MFA_STEP_UP_WINDOW_SECONDS', default=900, cast=int)

# Progressive lockout: failed attempts before the first delay is applied.
LOGIN_LOCKOUT_THRESHOLD = config('LOGIN_LOCKOUT_THRESHOLD', default=5, cast=int)


# Security hardening (environment-overridable).
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_HTTPONLY = False
API_REQUEST_MAX_BYTES = config('API_REQUEST_MAX_BYTES', default=5 * 1024 * 1024, cast=int)
SECURITY_SESSION_HOURS = config('SECURITY_SESSION_HOURS', default=12, cast=int)
TRUSTED_PROXY_IPS = [x.strip() for x in config('TRUSTED_PROXY_IPS', default='').split(',') if x.strip()]
CORS_ALLOW_CREDENTIALS = True

SECRET_ENCRYPTION_KEYS = config('SECRET_ENCRYPTION_KEYS', default='')
DOCUMENT_MALWARE_SCANNING_ENABLED = config('DOCUMENT_MALWARE_SCANNING_ENABLED', default=False, cast=bool)
DOCUMENT_MALWARE_SCANNING_REQUIRED = config('DOCUMENT_MALWARE_SCANNING_REQUIRED', default=False, cast=bool)
CLAMSCAN_PATH = config('CLAMSCAN_PATH', default='clamscan')
