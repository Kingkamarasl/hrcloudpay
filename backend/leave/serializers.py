from rest_framework import serializers
from .models import LeaveRequest, BreakRequest


class LeaveRequestSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.full_name', read_only=True)
    employee_id_card_no = serializers.CharField(source='employee.id_card_no', read_only=True)
    employee_code = serializers.CharField(source='employee.employee_code', read_only=True)
    days_requested = serializers.ReadOnlyField()

    class Meta:
        model = LeaveRequest
        fields = [
            'id', 'employee', 'employee_name', 'employee_id_card_no', 'employee_code',
            'leave_type', 'start_date', 'end_date', 'days_requested', 'reason', 'status', 'applied_at',
        ]
        read_only_fields = ['status']

    def validate(self, attrs):
        # LeaveRequest.days_requested is (end - start).days + 1, so an inverted
        # range yields a negative day count. That slips past the balance check
        # (available < days is trivially false for negatives) and then *credits*
        # the balance on approval. Reject inverted ranges outright.
        start = attrs.get('start_date') or getattr(self.instance, 'start_date', None)
        end = attrs.get('end_date') or getattr(self.instance, 'end_date', None)
        if start and end and end < start:
            raise serializers.ValidationError({
                'end_date': f'end_date ({end}) must not be before start_date ({start}).',
            })
        return attrs


class BreakRequestSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.full_name', read_only=True)
    employee_id_card_no = serializers.CharField(source='employee.id_card_no', read_only=True)
    employee_code = serializers.CharField(source='employee.employee_code', read_only=True)
    duration_minutes = serializers.ReadOnlyField()

    class Meta:
        model = BreakRequest
        fields = [
            'id', 'employee', 'employee_name', 'employee_id_card_no', 'employee_code',
            'break_type', 'date', 'start_time', 'end_time', 'duration_minutes', 'reason', 'status', 'applied_at',
        ]
        read_only_fields = ['status']
