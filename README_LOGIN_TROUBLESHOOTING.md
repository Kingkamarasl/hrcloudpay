# HRCloudPay Login Troubleshooting

From `backend` run:

```bat
python manage.py check
python manage.py showmigrations accounts
python manage.py showmigrations security
python manage.py migrate
python manage.py auth_diagnostics
```

For local development use `DEBUG=True` and a non-empty `SECRET_KEY`.

The secure login endpoint is `/api/auth/security/login/`. Security telemetry is deliberately non-blocking in development: a missing security event table cannot turn a bad password into HTTP 500. Production remains fail-closed for missing security infrastructure.
