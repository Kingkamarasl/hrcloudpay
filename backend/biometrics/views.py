from collections import Counter

from django.db import transaction
from django.utils import timezone

from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework.response import Response

from accounts.audit import audit
from accounts.permissions import IsCompanyMember, IsCompanyActive


class CanManageBiometrics(BasePermission):
    """Biometric device and enrollment management is company-wide, not
    per-employee, so `CanManageHROrDepartment`'s object-level check (which
    assumes an `.employee` attribute) does not apply. Owner, admin and HR may
    manage; department managers and employees may not.
    """
    def has_permission(self, request, view):
        return bool(
            request.user and request.user.is_authenticated
            and request.user.role in ('owner', 'admin', 'hr'))
from rest_framework.views import APIView

from accounts.permissions import CanManageHROrDepartment
from employees.models import Employee

from .models import BiometricDevice, BiometricEnrollment, BiometricPunch
from .serializers import (
    BiometricDeviceSerializer, BiometricDeviceCreateSerializer,
    BiometricEnrollmentSerializer, BiometricPunchSerializer)
from .services import process_punch, match_employee
from .throttling import AnonymousPunchThrottle, BiometricDeviceThrottle


# The punch log is a reconciliation view: an operator pages through it looking
# for the handful of punches that need a decision. The cap keeps one request
# from loading a terminal's entire history into the browser.
DEFAULT_PUNCH_PAGE_SIZE = 100
MAX_PUNCH_PAGE_SIZE = 500


def _int_or_none(raw):
    """Parse a query or body value as an integer, or None if it is not one.

    Filtering an integer column with a non-numeric string raises ValueError
    inside the ORM, which reaches the caller as a 500 on a request they could
    have corrected. Parsing first turns it into a 400 that names the parameter.
    """
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _bad_param(name, expected):
    return Response({'detail': '%s must be %s.' % (name, expected)},
                    status=status.HTTP_400_BAD_REQUEST)


def _punch_response(punch, duplicate=False):
    """One punch's outcome, in the shape the device and the log both read."""
    return {
        'punch_id': punch.id,
        'status': punch.status,
        'error': punch.error,
        'attendance_record': punch.attendance_record_id,
        'employee': punch.employee.full_name if punch.employee else None,
        'matched_by': punch.matched_by,
        'duplicate': duplicate,
    }


# A queue flush is one request and one timeout, so a terminal that has been
# offline sends pages of this size rather than its whole backlog at once.
MAX_PUNCH_BATCH = 200


def _record_punch(device, payload):
    """Record one punch from `payload`, reported by `device`.

    Returns (body, kind). `kind` is 'recorded' when the punch became attendance,
    'needs_reconciliation' when it was kept for a person to decide on (an
    unmatched employee, a clock-out with no open shift), 'duplicate' when the
    terminal re-sent a punch already on file, or 'rejected' when the payload
    itself is unreadable - the only kind that stores nothing at all, because it
    is a device bug rather than an attendance event.
    """
    employee, matched_by = match_employee(device, payload.get('employee'))

    punch_time_raw = payload.get('punch_time')
    try:
        punch_time = timezone.datetime.fromisoformat(
            str(punch_time_raw).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return {'error': 'punch_time must be an ISO-8601 timestamp.'}, 'rejected'
    if timezone.is_naive(punch_time):
        punch_time = timezone.make_aware(punch_time)

    # Keep the offset the device reported its clock in, not just the instant.
    # Attendance is made of the wall clock, and a punch read back from the
    # database has lost the offset that says what it was.
    offset = punch_time.utcoffset()
    utc_offset_minutes = None
    if offset is not None:
        utc_offset_minutes = int(offset.total_seconds() / 60)

    punch_type = payload.get('punch_type', 'unknown')
    if punch_type not in ('in', 'out', 'unknown'):
        return {'error': 'punch_type must be in, out or unknown.'}, 'rejected'

    # A terminal with an offline queue re-sends punches it could not deliver (a
    # timeout, a dropped link). That is the same event, not a second one:
    # recording it again would log a bogus "already clocked in" or an orphaned
    # clock-out, and fill the reconciliation list with failures that describe a
    # network problem rather than an attendance one. The original outcome is
    # returned so the device stops retrying. Matching on the device, employee,
    # timestamp and type is exact: a terminal reports whole events, and two
    # genuine punches do not share all four.
    existing = BiometricPunch.objects.filter(
        device=device, employee=employee, punch_time=punch_time,
        punch_type=punch_type).order_by('id').first()
    if existing is not None:
        return _punch_response(existing, duplicate=True), 'duplicate'

    punch = BiometricPunch.objects.create(
        device=device, employee=employee, matched_by=matched_by,
        punch_time=punch_time,
        utc_offset_minutes=utc_offset_minutes, punch_type=punch_type,
        # Devices may send vendor-specific fields, including biometric
        # templates. Retain only the documented attendance fields so an
        # incidental template can never be persisted in the punch log.
        raw_payload={
            key: payload.get(key)
            for key in ('device_id', 'employee', 'punch_time', 'punch_type')
            if key in payload
        },
    )
    process_punch(punch)
    punch.refresh_from_db()
    return (_punch_response(punch), 'recorded'
            if punch.status == 'processed' else 'needs_reconciliation')


class BiometricDeviceViewSet(viewsets.ModelViewSet):
    """Register and manage the terminals that report attendance.

    Registration returns the device API key once. The key is hashed before
    storage, so a lost key means re-registering the device - the same
    discipline as a password, because a leaked key lets an attacker inject
    attendance for an entire company.
    """
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive,
                          CanManageBiometrics]
    pagination_class = None
    queryset = BiometricDevice.objects.none()

    def get_queryset(self):
        return BiometricDevice.objects.filter(
            company=self.request.user.company).order_by('name')

    def get_serializer_class(self):
        if self.action == 'create':
            return BiometricDeviceCreateSerializer
        return BiometricDeviceSerializer

    def perform_create(self, serializer):
        from django.db import IntegrityError
        from rest_framework.exceptions import ValidationError as DRFValidationError
        try:
            device, raw_key = BiometricDevice.create_with_key(
                company=self.request.user.company, **serializer.validated_data)
        except IntegrityError:
            raise DRFValidationError(
                {'device_id': 'A device with this ID already exists for your company.'})
        # Stash the raw key on the instance so the response can include it.
        device._raw_api_key = raw_key
        serializer.instance = device

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        device = serializer.instance
        data = BiometricDeviceCreateSerializer(device).data
        data['api_key'] = getattr(device, '_raw_api_key', None)
        headers = self.get_success_headers(data)
        return Response(data, status=status.HTTP_201_CREATED, headers=headers)


class BiometricEnrollmentViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive,
                          CanManageBiometrics]
    pagination_class = None
    serializer_class = BiometricEnrollmentSerializer

    def get_queryset(self):
        return BiometricEnrollment.objects.filter(
            employee__company=self.request.user.company).order_by('-enrolled_at')

    def perform_create(self, serializer):
        device = serializer.validated_data['device']
        employee = serializer.validated_data['employee']
        if (device.company_id != self.request.user.company_id
                or employee.company_id != self.request.user.company_id):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(
                'The employee and device must both belong to your company.')
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.revoke()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BiometricPunchListView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive,
                          CanManageBiometrics]

    def get(self, request):
        qs = BiometricPunch.objects.filter(
            device__company=request.user.company).order_by('-punch_time')
        device_id = request.query_params.get('device')
        if device_id:
            device_pk = _int_or_none(device_id)
            if device_pk is None:
                return _bad_param('device', 'a device row ID')
            qs = qs.filter(device_id=device_pk)
        employee_id = request.query_params.get('employee')
        if employee_id:
            employee_pk = _int_or_none(employee_id)
            if employee_pk is None:
                return _bad_param('employee', 'an employee row ID')
            qs = qs.filter(employee_id=employee_pk)
        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        limit = _int_or_none(
            request.query_params.get('limit', DEFAULT_PUNCH_PAGE_SIZE))
        if limit is None or limit < 1:
            return _bad_param('limit', 'a positive integer')
        return Response(BiometricPunchSerializer(
            qs[:min(limit, MAX_PUNCH_PAGE_SIZE)], many=True).data)


class BiometricPunchIngestView(APIView):
    """Receive a punch, or a page of queued punches, from a biometric device.

    Authentication is by device API key, not by user session: the device has no
    user account and no browser. The key identifies the device, and the device
    identifies the company, so a key from one tenant can never record attendance
    for another.

    Shape - one punch:
        {
          "device_id": "ZK-001",
          "employee": "CA0042" or 17,      # enrolment template ID, employee_code,
                                         #  or HRCloudPay PK if the device opted in
          "punch_time": "2026-10-25T08:02:14+02:00",
          "punch_type": "in" | "out" | "unknown"
        }

    Shape - a queue flush, to the same URL so a terminal has one thing to
    configure:
        {
          "device_id": "ZK-001",
          "punches": [ {punch}, {punch}, ... ]
        }

    A batch is capped at MAX_PUNCH_BATCH punches because a request is also one
    timeout: a terminal offline for a week sends pages rather than having its
    whole backlog refused. Each punch keeps its own outcome, so one unreadable
    entry cannot discard the rest of the queue, and each is written in its own
    transaction so a failure part-way through one punch cannot leave it
    half-recorded.

    Rate limiting is per device rather than per IP - see throttling.py.
    """
    permission_classes = []
    authentication_classes = []
    throttle_classes = [BiometricDeviceThrottle, AnonymousPunchThrottle]

    def post(self, request):
        device_id = request.data.get('device_id')
        raw_key = request.META.get('HTTP_X_BIOMETRIC_DEVICE_KEY', '')
        if not device_id or not raw_key:
            return Response(
                {'detail': 'device_id and X-Biometric-Device-Key are required.'},
                status=status.HTTP_400_BAD_REQUEST)

        device = BiometricDevice.authenticate(device_id, raw_key)
        if device is None:
            return Response({'detail': 'Unknown or unauthorised device.'},
                            status=status.HTTP_401_UNAUTHORIZED)
        if device.status != 'active':
            return Response({'detail': 'Device is not active.'},
                            status=status.HTTP_403_FORBIDDEN)

        device.touch()

        queued = request.data.get('punches')
        if queued is not None:
            return self._ingest_batch(device, queued)

        body, kind = _record_punch(device, request.data)
        if kind == 'rejected':
            return Response({'detail': body['error']},
                            status=status.HTTP_400_BAD_REQUEST)
        if kind == 'duplicate':
            return Response(body, status=status.HTTP_200_OK)
        return Response(body, status=status.HTTP_201_CREATED
                        if kind == 'recorded' else status.HTTP_202_ACCEPTED)

    def _ingest_batch(self, device, queued):
        if not isinstance(queued, list):
            return Response(
                {'detail': 'punches must be a list of punch objects.'},
                status=status.HTTP_400_BAD_REQUEST)
        if not queued:
            return Response({'detail': 'punches must not be empty.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if len(queued) > MAX_PUNCH_BATCH:
            return Response(
                {'detail': 'Send at most %d punches per request; split the '
                           'queue into pages.' % MAX_PUNCH_BATCH},
                status=status.HTTP_400_BAD_REQUEST)

        counts = Counter()
        results = []
        for index, item in enumerate(queued):
            if not isinstance(item, dict):
                counts['rejected'] += 1
                results.append({'index': index, 'status': 'rejected',
                                'error': 'Each punch must be an object.'})
                continue
            with transaction.atomic():
                body, kind = _record_punch(device, item)
            counts[kind] += 1
            entry = {'index': index, 'status': body.get('status', 'rejected')}
            for field in ('punch_id', 'error', 'duplicate'):
                if field in body:
                    entry[field] = body[field]
            results.append(entry)

        if counts['rejected'] == len(queued):
            # Every entry was unreadable. That is a broken integration, not a
            # quiet queue, and answering 200 would hide it behind a retry loop.
            return Response(
                {'detail': 'No punch in the batch could be read.',
                 'results': results},
                status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'received': len(queued),
            # Keyed by the kind _record_punch reports: 'duplicate', not
            # 'duplicates' - the response names the bucket, the counter names
            # the outcome, and the two were briefly not the same word.
            'recorded': counts['recorded'],
            'needs_reconciliation': counts['needs_reconciliation'],
            'duplicates': counts['duplicate'],
            'rejected': counts['rejected'],
            'results': results,
        }, status=status.HTTP_200_OK)


class BiometricPunchReconcileView(APIView):
    """Attach a punch to an employee and run it through processing again.

    A punch that could not be matched to anyone, or a clock-out that arrived
    with no shift to close, is kept as `ignored`/`failed` rather than guessed
    at - that restraint is the point of the punch log. But a punch nobody can
    act on is a dead row, and the reasons it exists are exactly the reasons an
    operator can fix by hand: the employee had no enrolment on that terminal
    yet, or their clock-in was recorded but not linked.

    So this is the decision the log was waiting for. `employee` is required for
    an unmatched punch; for a failed clock-out it is optional, because the
    punch already knows who it belongs to. A punch that has already produced an
    attendance record is refused: reprocessing it would rewrite hours a person
    may already have been paid for, and the attendance record itself is the
    place to correct that.
    """
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive,
                          CanManageBiometrics]

    def post(self, request, pk):
        punch = BiometricPunch.objects.filter(
            device__company=request.user.company, pk=pk,
        ).select_related('device', 'employee').first()
        if punch is None:
            return Response({'detail': 'Punch not found.'},
                            status=status.HTTP_404_NOT_FOUND)
        if punch.status == 'processed':
            return Response(
                {'detail': 'This punch is already recorded as attendance. '
                           'Correct the attendance record instead.'},
                status=status.HTTP_400_BAD_REQUEST)

        employee_id = request.data.get('employee')
        if employee_id in (None, ''):
            employee = punch.employee
        else:
            employee_pk = _int_or_none(employee_id)
            employee = None
            if employee_pk is not None:
                employee = Employee.objects.filter(
                    company=punch.device.company, pk=employee_pk).first()
            if employee is None:
                return Response(
                    {'detail': 'employee must be an employee of the terminal\'s '
                               'company.'},
                    status=status.HTTP_400_BAD_REQUEST)
        if employee is None:
            return Response(
                {'detail': 'employee is required to reconcile a punch that was '
                           'not matched to anyone.'},
                status=status.HTTP_400_BAD_REQUEST)

        # Reset to pending so processing re-runs from the same state a freshly
        # arrived punch would have, rather than reading the previous verdict.
        # A person attaching the employee is itself a matching decision, so it
        # is recorded as such - and only then: a clock-out being reprocessed for
        # the employee it already matched keeps the rule that matched it.
        fields = ['employee', 'status', 'error']
        if employee_id not in (None, ''):
            punch.matched_by = 'manual'
            fields.append('matched_by')
        punch.employee = employee
        punch.status = 'pending'
        punch.error = ''
        punch.save(update_fields=fields)
        process_punch(punch)
        punch.refresh_from_db()

        audit(
            actor=request.user, action='biometric.punch_reconciled',
            message='Biometric punch %s for %s reconciled to %s: %s.'
                    % (punch.id, punch.device.name, employee.full_name,
                       punch.status),
            company=request.user.company, target_type='BiometricPunch',
            target_id=punch.id,
            metadata={'employee_id': employee.id,
                      'result': punch.status,
                      'attendance_record': punch.attendance_record_id},
            request=request,
        )
        return Response(_punch_response(punch), status=status.HTTP_200_OK)
