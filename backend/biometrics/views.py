from django.utils import timezone

from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework.response import Response

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
            qs = qs.filter(device_id=device_id)
        employee_id = request.query_params.get('employee')
        if employee_id:
            qs = qs.filter(employee_id=employee_id)
        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        limit = int(request.query_params.get('limit', 100))
        return Response(BiometricPunchSerializer(
            qs[:min(limit, 500)], many=True).data)


class BiometricPunchIngestView(APIView):
    """Receive a punch from a biometric device.

    Authentication is by device API key, not by user session: the device has no
    user account and no browser. The key identifies the device, and the device
    identifies the company, so a key from one tenant can never record attendance
    for another.

    Shape:
        {
          "device_id": "ZK-001",
          "employee": "CA0042" or 17,      # active enrollment template ID, employee_code or PK
          "punch_time": "2026-10-25T08:02:14+02:00",
          "punch_type": "in" | "out" | "unknown"
        }
    """
    permission_classes = []
    authentication_classes = []

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

        employee = match_employee(device, request.data.get('employee'))

        punch_time_raw = request.data.get('punch_time')
        try:
            punch_time = timezone.datetime.fromisoformat(
                str(punch_time_raw).replace('Z', '+00:00'))
        except (TypeError, ValueError):
            return Response({'detail': 'punch_time must be an ISO-8601 timestamp.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if timezone.is_naive(punch_time):
            punch_time = timezone.make_aware(punch_time)

        punch_type = request.data.get('punch_type', 'unknown')
        if punch_type not in ('in', 'out', 'unknown'):
            return Response({'detail': 'punch_type must be in, out or unknown.'},
                            status=status.HTTP_400_BAD_REQUEST)

        punch = BiometricPunch.objects.create(
            device=device, employee=employee, punch_time=punch_time,
            punch_type=punch_type,
            # Devices may send vendor-specific fields, including biometric
            # templates. Retain only the documented attendance fields so an
            # incidental template can never be persisted in the punch log.
            raw_payload={
                key: request.data.get(key)
                for key in ('device_id', 'employee', 'punch_time', 'punch_type')
                if key in request.data
            },
        )
        record = process_punch(punch)
        punch.refresh_from_db()

        return Response({
            'punch_id': punch.id,
            'status': punch.status,
            'error': punch.error,
            'attendance_record': record.id if record else None,
            'employee': employee.full_name if employee else None,
        }, status=status.HTTP_201_CREATED if punch.status == 'processed'
           else status.HTTP_202_ACCEPTED)
