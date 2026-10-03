# HRCloudPay - Production Dockerfile
# Multi-stage build: frontend -> backend

# Stage 1: Build frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build -- --outDir /app/frontend/dist

# Stage 2: Backend
FROM python:3.11-slim AS backend

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

# Python dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ ./

# Copy built frontend from stage 1
COPY --from=frontend-builder /app/frontend/dist/ ./frontend_dist/

# Collect static files
# The rm matters. With no DATABASE_URL set during the build, settings falls back
# to SQLite and at least one AppConfig.ready() opens a connection, so Django
# creates db.sqlite3 even though nothing is ever written to it. An image that
# carries an empty database boots cleanly when DATABASE_URL is missing at
# runtime, and serves an empty application instead of failing - the one
# failure mode this image cannot afford.
RUN SECRET_KEY=v3rc3l-build-time-only-not-a-runtime-key \
    python manage.py collectstatic --noinput \
    && rm -f /app/backend/db.sqlite3

# Migrations and seeds deliberately do NOT run here.
#
# This stage has no DATABASE_URL, so settings.py falls back to SQLite and
# `migrate` would build a throwaway db.sqlite3 inside the image. The deployed
# container sets DATABASE_URL to Postgres, so those migrations never reached the
# real database - the step looked handled while silently doing nothing, and an
# operator had no reason to run it for real.
#
# Apply them as a release step against the production database instead:
#   python manage.py migrate --noinput
#   python manage.py seed_country_rules     # not optional - see README
#   python manage.py seed_filing_rules
# See the "Release order" section of README.md.

EXPOSE 8000

CMD ["gunicorn", "hrcloudpay.wsgi", "--bind", "0.0.0.0:8000", "--workers", "4"]
