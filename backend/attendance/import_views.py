"""Spreadsheet import: preview, then apply.

Two endpoints, on purpose.

`POST /api/attendance/imports/preview/` parses the file and returns a per-row
plan - create, update, unchanged, or error, with the reason. It writes nothing.

`POST /api/attendance/imports/apply/` takes the preview token and commits the
creates and updates inside one transaction.

The split exists because this is a bulk write into the table payroll reads,
submitted at the end of a period by someone who kept their own records, into
data nobody else has checked. A single "upload and done" endpoint would apply a
file with fifty typo'd employee codes and report success, and the discovery would
be at payday.

The token is a cache key holding what *the server* parsed, not a signed blob of
client-supplied data, so apply never trusts the caller about what the file said.
Scope is re-checked at apply time too: a manager's reach can change between the
two calls, and the spreadsheet on disk does not.
"""
import uuid
from datetime import date as date_cls
from datetime import time as time_cls

from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.audit import audit
from accounts.permissions import CanManageHROrDepartment, IsCompanyActive, IsCompanyMember

from .importers import SpreadsheetError, build_plan, build_template
from .models import Attendance

PREVIEW_TTL_SECONDS = 30 * 60
TOKEN_PREFIX = 'attendance-import:'
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def _cache_key(user, token):
    return f'{TOKEN_PREFIX}{user.pk}:{token}'


def _scope_checker(request):
    rule = CanManageHROrDepartment()
    return lambda employee: rule.employee_in_scope(request, employee)


def _uploaded_file(request):
    upload = request.FILES.get('file')
    if upload is None:
        raise ValidationError({'file': 'Attach a spreadsheet as "file".'})
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError({
            'file': 'That file is larger than 5 MB. Upload one '
                    'department-month at a time.',
        })
    return upload


def _apply_values(row, filename):
    """Exactly the values the preview showed.

    Blanks are applied as None rather than skipped. Filtering them out would
    mean a sheet with an empty check-in could not clear a time already on the
    record, so apply would quietly do less than the preview promised - the
    worst possible place for preview and apply to disagree.
    """
    return {
        'status': row['status'],
        'check_in': time_cls.fromisoformat(row['check_in']) if row['check_in'] else None,
        'check_out': time_cls.fromisoformat(row['check_out']) if row['check_out'] else None,
        'crossed_midnight': bool(row['crossed_midnight']),
        'notes': (row['notes'] or f'Imported from {filename}')[:255],
    }


class AttendanceImportPreviewView(APIView):
    """Parse a spreadsheet and report what importing it would do. Writes nothing."""

    permission_classes = [IsCompanyMember, IsCompanyActive]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        user = request.user
        if user.role == 'employee':
            raise PermissionDenied(
                'Attendance is imported by HR, an owner, or a department manager.')
        upload = _uploaded_file(request)
        try:
            plan = build_plan(
                user.company, upload, _scope_checker(request),
                filename=upload.name,
            )
        except SpreadsheetError as exc:
            raise ValidationError({'file': str(exc)})

        token = uuid.uuid4().hex
        cache.set(
            _cache_key(user, token),
            {'plan': plan, 'created_at': timezone.now().isoformat()},
            PREVIEW_TTL_SECONDS,
        )
        return Response({**plan, 'preview_token': token}, status=200)


class AttendanceImportApplyView(APIView):
    """Commit a previously previewed import."""

    permission_classes = [IsCompanyMember, IsCompanyActive]

    def post(self, request):
        from employees.models import Employee

        user = request.user
        token = request.data.get('preview_token')
        if not token:
            raise ValidationError({
                'preview_token': 'Preview the file first and send the token it '
                                 'returns.',
            })
        cached = cache.get(_cache_key(user, token))
        if not cached:
            raise ValidationError({
                'preview_token': 'That preview has expired or was never made. '
                                 'Upload the file again.',
            })

        plan = cached['plan']
        rule = CanManageHROrDepartment()
        filename = plan.get('filename') or 'the uploaded file'

        created, updated, refused, errors = [], [], [], []

        with transaction.atomic():
            for row in plan['rows']:
                if row['action'] == 'error':
                    refused.append(row)
                    continue
                if row['action'] not in ('create', 'update'):
                    continue

                employee = Employee.objects.filter(
                    id=row['employee_id'], company=user.company).first()
                if employee is None:
                    errors.append(
                        f"row {row['row']}: {row['employee_ref']} no longer "
                        'exists in this company')
                    continue
                if not rule.employee_in_scope(request, employee):
                    refused.append(row)
                    continue

                day = date_cls.fromisoformat(row['date'])
                values = _apply_values(row, filename)
                record = Attendance.objects.filter(
                    employee=employee, date=day).first()

                if record is None:
                    created.append(Attendance.objects.create(
                        employee=employee, date=day, **values))
                else:
                    for field, value in values.items():
                        setattr(record, field, value)
                    record.save()
                    updated.append(record)

        # Consumed either way. A replayable token would let one upload be
        # applied twice, and on an update "applied twice" means a second trail
        # of changes nobody can explain.
        cache.delete(_cache_key(user, str(token)))

        if created or updated:
            audit(
                request.user,
                'create' if created else 'update',
                f'Imported attendance from {filename}',
                user.company, 'attendance', '',
                {
                    'filename': filename,
                    'created': len(created),
                    'updated': len(updated),
                    'refused_rows': [r['row'] for r in refused],
                    'errors': errors,
                    'employee_ids': sorted({
                        r.employee_id for r in created + updated
                    }),
                },
                request=request,
            )

        return Response({
            'created': len(created),
            'updated': len(updated),
            'unchanged': plan['summary']['unchanged'],
            'refused': len(refused),
            'refused_rows': [
                {'row': r['row'], 'employee_ref': r['employee_ref'],
                 'errors': r['errors']}
                for r in refused
            ],
            'errors': errors,
        }, status=200)


class AttendanceImportTemplateView(APIView):
    """An .xlsx with the expected headings and a few example rows."""

    permission_classes = [IsCompanyMember, IsCompanyActive]

    def get(self, request):
        buffer = build_template()
        response = HttpResponse(
            buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.'
                         'spreadsheetml.sheet',
        )
        response['Content-Disposition'] = \
            'attachment; filename="attendance-template.xlsx"'
        return response