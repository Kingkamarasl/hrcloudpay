from rest_framework import serializers

from .models import (
    BiometricDevice, BiometricEnrollment, BiometricPunch)
from .services import device_health


class BiometricDeviceSerializer(serializers.ModelSerializer):
    """Device rows carry whether they are still reporting, and which
    identifiers the terminal is allowed to match punches by.

    See biometrics.services.device_health (§ why silence is a signal). Health is
    computed per row rather than stored, because 'silent' is a statement about
    now: a stored flag would be wrong from the moment the next punch arrived.
    ``match_policy`` is stored - it is a configuration decision, and it decides
    whose hours end up on whose payslip.
    """
    health = serializers.SerializerMethodField()

    class Meta:
        model = BiometricDevice
        fields = ('id', 'name', 'device_id', 'device_type', 'location',
                  'status', 'match_policy', 'last_seen_at', 'last_sync_at',
                  'health', 'created_at')
        read_only_fields = ('id', 'last_seen_at', 'last_sync_at', 'health',
                            'created_at')

    def get_health(self, obj):
        return device_health(obj)


class BiometricDeviceCreateSerializer(serializers.ModelSerializer):
    """Registration returns the raw API key exactly once.

    The key is hashed before storage, so this is the only moment it exists in
    readable form. The operator copies it into the device; if they lose it, the
    device must be re-registered. That is the same discipline as a password
    reset, and it is why the key is never returned by the list endpoint.
    """
    api_key = serializers.CharField(read_only=True)

    class Meta:
        model = BiometricDevice
        fields = ('id', 'name', 'device_id', 'device_type', 'location',
                  'status', 'match_policy', 'api_key', 'created_at')
        read_only_fields = ('id', 'api_key', 'created_at')


class BiometricEnrollmentSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source='employee.full_name', read_only=True)

    class Meta:
        model = BiometricEnrollment
        fields = ('id', 'employee', 'employee_name', 'device', 'method',
                  'template_id', 'status', 'enrolled_at', 'revoked_at')
        read_only_fields = ('id', 'enrolled_at', 'revoked_at')


class BiometricPunchSerializer(serializers.ModelSerializer):
    """``matched_by`` is the punch's provenance: which rule decided the
    employee. It is what makes a wrong match traceable later, instead of a
    name in the log with no explanation of how it got there.
    """
    employee_name = serializers.SerializerMethodField()
    device_name = serializers.CharField(source='device.name', read_only=True)

    class Meta:
        model = BiometricPunch
        fields = ('id', 'device', 'device_name', 'employee', 'employee_name',
                  'matched_by', 'punch_time', 'punch_type', 'status', 'error',
                  'attendance_record', 'created_at')
        read_only_fields = fields

    def get_employee_name(self, obj):
        return obj.employee.full_name if obj.employee else None