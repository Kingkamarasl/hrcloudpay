import hashlib
import json
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.response import Response

from .models import IdempotencyRecord

# How long a 'processing' row may sit before another identical request is
# allowed to take it over. Without this, a crash between begin() and complete()
# reserved the key forever: every retry got 409, so that payroll could never be
# processed again under the same key. Long enough that a genuinely slow run is
# not duplicated, short enough that a stuck one is not permanent.
DEFAULT_STALE_SECONDS = 900


def _stale_seconds():
    return getattr(settings, 'IDEMPOTENCY_STALE_SECONDS', DEFAULT_STALE_SECONDS)


def request_hash(request):
    payload = json.dumps(request.data, sort_keys=True, default=str, separators=(',', ':'))
    return hashlib.sha256(payload.encode()).hexdigest()


def _takeover(record, request, digest):
    """Re-arm a record whose attempt died before it could complete."""
    record.actor = request.user if request.user.is_authenticated else None
    record.request_hash = digest
    record.status = 'processing'
    record.response_status = None
    record.response_body = {}
    record.resource_type = ''
    record.resource_id = ''
    record.completed_at = None
    record.started_at = timezone.now()
    record.save(update_fields=[
        'actor', 'request_hash', 'status', 'response_status', 'response_body',
        'resource_type', 'resource_id', 'completed_at', 'started_at',
    ])


def begin(request, operation, company):
    key = str(request.headers.get('Idempotency-Key', '')).strip()
    if not key:
        return None, None
    if len(key) > 200:
        return None, Response({'detail': 'Idempotency-Key must be 200 characters or fewer.'}, status=400)
    digest = request_hash(request)
    # The lock has to cover the decision, not just the read: two requests
    # arriving at the same moment must not both decide a stale row is theirs
    # to take over and both process the same payroll. get_or_create() handles
    # the INSERT race itself by re-reading the winning row.
    with transaction.atomic():
        record, created = IdempotencyRecord.objects.select_for_update().get_or_create(
            company=company, key=key, operation=operation,
            defaults={'actor': request.user if request.user.is_authenticated else None, 'request_hash': digest},
        )
        if record.request_hash != digest:
            return None, Response({'detail': 'This Idempotency-Key was already used with a different request body.'}, status=409)
        if not created and record.status == 'completed':
            return record, Response(record.response_body, status=record.response_status or 200)
        if not created:
            stale_before = timezone.now() - timedelta(seconds=_stale_seconds())
            if record.started_at and record.started_at > stale_before:
                return None, Response({'detail': 'An identical request is already being processed.'}, status=409)
            _takeover(record, request, digest)
    return record, None


def complete(record, response, resource_type='', resource_id=''):
    if not record:
        return response
    record.status = 'completed'
    record.response_status = response.status_code
    record.response_body = response.data if isinstance(response.data, dict) else {'data': response.data}
    record.resource_type = resource_type
    record.resource_id = str(resource_id or '')
    record.completed_at = timezone.now()
    record.save(update_fields=['status', 'response_status', 'response_body', 'resource_type', 'resource_id', 'completed_at'])
    return response
