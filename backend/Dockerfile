# HRCloudPay - backend container for the Vercel Services deployment.
#
# This is deliberately NOT the root Dockerfile. That one builds the frontend
# too and serves everything from Django, which is the right shape for a single
# container or a VM. Under Vercel Services the SPA is a separate Vite service
# that has already built and is already serving it, so building it a second
# time here would duplicate ~50 chunks into an image that never serves them.
#
# Runtime, not just packaging: the Vercel Python runtime has no `tesseract`
# binary, so OCR of scanned documents fails there. Installing it here is the
# reason to prefer a container over the default runtime at all. It also removes
# the serverless wall-clock limit that PDF generation and document ingestion
# can exceed.

FROM python:3.11-slim

# libpq-dev + gcc are only needed to build psycopg from source; the `binary`
# extra ships prebuilt wheels, so they are a safety net rather than a
# requirement. tesseract-ocr and its language packs are the point of this file.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        tesseract-ocr \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The build context is this service's root (backend/), NOT the repository root,
# so every path below is relative to backend/. Writing `COPY backend/...` here
# would resolve to backend/backend/... and fail the build.
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

# collectstatic imports settings.py, which raises ImproperlyConfigured when
# DEBUG is false and SECRET_KEY is empty or one of the known-insecure values.
# That check exists to stop a real deployment running on a published key, so
# the build-time key below is a throwaway that never reaches a runtime: it is
# not an ARG, it is not an ENV, and the deployed container gets its key from the
# environment instead.
#
# The rm is not tidiness. With no DATABASE_URL set during the build, settings
# falls back to SQLite, and at least one AppConfig.ready() opens a connection -
# which is what the RuntimeWarning on stderr during every build is. Django
# creates the file even though the build never writes to it, so without this the
# image ships an empty database. A container that then starts without
# DATABASE_URL would boot cleanly against it and serve an empty application
# rather than failing loudly, which is the one failure mode this file cannot
# afford.
RUN SECRET_KEY=v3rc3l-build-time-only-not-a-runtime-key \
    python manage.py collectstatic --noinput \
    && rm -f /app/db.sqlite3

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Vercel supplies PORT and expects the container to bind it. The fallback keeps
# the image usable under a plain `docker run` for a smoke test.
EXPOSE 8000

CMD ["sh", "-c", "exec gunicorn hrcloudpay.wsgi --bind 0.0.0.0:${PORT:-8000} --workers 2 --access-logfile -"]