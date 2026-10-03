# HRCloudPay — Production Dockerfile
# Multi-stage build: frontend → backend

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
RUN python manage.py collectstatic --noinput

# Run migrations + seed data
RUN python manage.py migrate --noinput && \
    python manage.py seed_country_rules && \
    python manage.py seed_filing_rules

EXPOSE 8000

CMD ["gunicorn", "hrcloudpay.wsgi", "--bind", "0.0.0.0:8000", "--workers", "4"]
