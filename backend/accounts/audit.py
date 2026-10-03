from contextvars import ContextVar
import uuid
from django.forms.models import model_to_dict

from .net import client_ip

_request_user = ContextVar('hrcloudpay_audit_user', default=None)
_request_ip = ContextVar('hrcloudpay_audit_ip', default='')
_request_id = ContextVar('hrcloudpay_audit_request_id', default='')
_request_agent = ContextVar('hrcloudpay_audit_user_agent', default='')


def set_audit_context(user=None, ip='', request_id='', user_agent=''):
    _request_user.set(user)
    _request_ip.set(ip or '')
    _request_id.set(request_id or '')
    _request_agent.set(user_agent or '')


def get_audit_context():
    return _request_user.get(), _request_ip.get()


def audit(actor=None, action='system', message='', company=None, target_type='', target_id='', metadata=None, request=None):
    """Create an immutable audit record with safe request context metadata."""
    from .platform_models import AuditLog
    if actor is None:
        actor, ip = get_audit_context()
    else:
        _, ip = get_audit_context()
    request_id = _request_id.get()
    user_agent = _request_agent.get()
    if request is not None:
        request_id = getattr(request, '_audit_request_id', request_id)
        user_agent = request.META.get('HTTP_USER_AGENT', user_agent)[:500]
        ip = client_ip(request)
    AuditLog.objects.create(
        actor=actor if getattr(actor, 'is_authenticated', False) else None,
        company=company,
        action=action,
        target_type=target_type,
        target_id=str(target_id or ''),
        message=message[:500],
        metadata={**(metadata or {}), **({'ip_address': ip} if ip else {})},
        request_id=request_id, user_agent=user_agent,
    )


def snapshot_fields(instance, fields):
    """Capture the current values of `fields`.

    Must be called BEFORE mutating/saving the instance -- once `save()` has run
    the old values are gone, so they cannot be recovered afterwards.
    """
    return {field: getattr(instance, field, None) for field in fields}


def diff_fields(before, instance, fields):
    """Return {field: {before, after}} for fields that changed since `before`.

    `before` is a snapshot taken by snapshot_fields() prior to saving.
    """
    changes = {}
    for field in fields:
        old = before.get(field)
        new = getattr(instance, field, None)
        if old != new:
            changes[field] = {
                'before': str(old) if old is not None else None,
                'after': str(new) if new is not None else None,
            }
    return changes


def changed_fields(instance, fields, before=None):
    """Return {field: {before, after}} for fields that changed on `instance`.

    `before` must be a snapshot_fields() mapping captured prior to saving.
    Omitting it compares the instance against itself and always returns {}.
    """
    if before is None:
        raise ValueError(
            'changed_fields() needs a snapshot of the pre-save values. '
            'Call snapshot_fields(instance, fields) before serializer.save() '
            'and pass it in, otherwise before/after can never differ.'
        )
    return diff_fields(before, instance, fields)


class AuditRequestMiddleware:
    """Make the authenticated actor and source IP available to model-level auditing."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ip = client_ip(request)
        token_user = _request_user.set(getattr(request, 'user', None))
        token_ip = _request_ip.set(ip)
        request_id = str(uuid.uuid4())
        request._audit_request_id = request_id
        token_id = _request_id.set(request_id)
        token_agent = _request_agent.set(request.META.get('HTTP_USER_AGENT', '')[:500])
        try:
            return self.get_response(request)
        finally:
            _request_user.reset(token_user)
            _request_ip.reset(token_ip)
            _request_id.reset(token_id)
            _request_agent.reset(token_agent)
