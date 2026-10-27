import hashlib
import json
from datetime import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.response import Response

from .models import IdempotencyRecord


def request_hash(request):
    payload = json.dumps(request.data, sort_keys=True, default=str, separators=(',', ':'))
    return hashlib.sha256(payload.encode()).hexdigest()


def begin(request, operation, company):
    key = str(request.headers.get('Idempotency-Key', '')).strip()
    if not key:
        return None, None
    if len(key) > 200:
        return None, Response({'detail': 'Idempotency-Key must be 200 characters or fewer.'}, status=400)
    digest = request_hash(request)
    try:
        with transaction.atomic():
            record, created = IdempotencyRecord.objects.select_for_update().get_or_create(
                company=company, key=key, operation=operation,
                defaults={'actor': request.user if request.user.is_authenticated else None, 'request_hash': digest},
            )
    except IntegrityError:
        record = IdempotencyRecord.objects.select_for_update().get(company=company, key=key, operation=operation)
        created = False
    if record.request_hash != digest:
        return None, Response({'detail': 'This Idempotency-Key was already used with a different request body.'}, status=409)
    if not created and record.status == 'completed':
        return record, Response(record.response_body, status=record.response_status or 200)
    if not created:
        return None, Response({'detail': 'An identical request is already being processed.'}, status=409)
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
