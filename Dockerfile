# HRCloudPay - Production Dockerfile
# Three stages: frontend -> Python dependencies -> runtime.
#
# The dependency stage exists so the runtime image does not carry a compiler.
# gcc and libpq-dev are only needed to build psycopg from source, and
# psycopg[binary] ships prebuilt wheels, so at runtime they are ~250 MB of dead
# weight. They were in the final image in earlier revisions, which is most of
# why it weighed 1.36 GB.

# --- Stage 1: build the SPA -------------------------------------------------
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build -- --outDir /app/frontend/dist

# --- Stage 2: install Python dependencies ------------------------------------
FROM python:3.11-slim AS deps-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/requirements.txt ./
# --prefix keeps the install in one directory that the runtime stage copies
# wholesale, rather than scattering files across /usr/local that would then
# have to be diffed and deleted.
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Stage 3: runtime -------------------------------------------------------
FROM python:3.11-slim AS backend

# tesseract-ocr is the point of building an image rather than using a PaaS's
# language runtime: pytesseract is a wrapper around this binary, so without it
# scanned PDFs cannot be read. tesseract-ocr-eng is named explicitly because the
# bare package does not always pull the English language data, and HRCloudPay's
# documents are English.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

COPY --from=deps-builder /install /usr/local
COPY backend/ ./
COPY --from=frontend-builder /app/frontend/dist/ ./frontend_dist/

# collectstatic imports settings.py, which raises ImproperlyConfigured when
# DEBUG is false and SECRET_KEY is empty or one of the known-insecure values.
# That check exists to stop a real deployment running on a published key, so
# the build-time key below is a throwaway that never reaches a runtime: it is
# not an ARG, it is not an ENV, and the deployed container gets its key from
# the environment instead.
#
# The rm is not tidiness. With no DATABASE_URL set during the build, settings
# falls back to SQLite and at least one AppConfig.ready() opens a connection,
# so Django creates db.sqlite3 even though the build never writes to it. An
# image that ships an empty database boots cleanly when DATABASE_URL is missing
# at runtime and serves an empty application rather than failing - the one
# failure mode this file cannot afford.
RUN SECRET_KEY=v3rc3l-build-time-only-not-a-runtime-key \
    python manage.py collectstatic --noinput \
    && rm -f /app/backend/db.sqlite3

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Railway injects PORT and routes traffic to it, 8080 by default. A hardcoded
# 8000 builds cleanly and then 502s on every request, with nothing in the build
# log to explain why - the image is fine, it is listening on the wrong port.
EXPOSE 8000

CMD ["sh", "-c", "exec gunicorn hrcloudpay.wsgi --bind 0.0.0.0:${PORT:-8000} --workers 4 --access-logfile -"]

# Migrations and seeds deliberately do NOT run here.
#
# This stage has no DATABASE_URL, so settings.py falls back to SQLite and
# `migrate` would build a throwaway db.sqlite3 inside the image. The deployed
# container sets DATABASE_URL to Postgres, so those migrations never reached the
# real database - the step looked handled while silently doing nothing, and an
# operator had no reason to run it for real.
#
# Apply them as a pre-deploy step against the production database instead:
#   python manage.py migrate --noinput
#   python manage.py seed_country_rules     # not optional - see README
#   python manage.py seed_filing_rules
# See the "Release order" section of README.md. Note there is no `cd backend`:
# WORKDIR is already /app/backend, so that would resolve to a path that does not
# exist.