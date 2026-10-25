from rest_framework import serializers

from .models import (
    BiometricDevice, BiometricEnrollment, BiometricPunch)


class BiometricDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = BiometricDevice
        fields = ('id', 'name', 'device_id', 'device_type', 'location',
                  'status', 'last_seen_at', 'last_sync_at', 'created_at')
        read_only_fields = ('id', 'last_seen_at', 'last_sync_at', 'created_at')


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
                  'status', 'api_key', 'created_at')
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
    employee_name = serializers.SerializerMethodField()
    device_name = serializers.CharField(source='device.name', read_only=True)

    class Meta:
        model = BiometricPunch
        fields = ('id', 'device', 'device_name', 'employee', 'employee_name',
                  'punch_time', 'punch_type', 'status', 'error',
                  'attendance_record', 'created_at')
        read_only_fields = fields

    def get_employee_name(self, obj):
        return obj.employee.full_name if obj.employee else None