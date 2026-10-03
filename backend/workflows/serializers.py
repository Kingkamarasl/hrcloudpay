from rest_framework import serializers

from .models import HRNotification, WorkflowTask, WorkflowRule


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.ReadOnlyField()
    employee_name = serializers.SerializerMethodField()

    def get_employee_name(self, obj):
        return obj.employee.full_name if obj.employee_id else ''

    class Meta:
        model = HRNotification
        fields = [
            'id', 'notification_type', 'level', 'title', 'message',
            'action_url', 'due_date', 'read_at', 'created_at',
            'employee', 'employee_name', 'is_read',
        ]
        read_only_fields = [
            'id', 'notification_type', 'level', 'title', 'message',
            'action_url', 'due_date', 'read_at', 'created_at',
            'employee', 'employee_name', 'is_read',
        ]


class TaskSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    assigned_to_name = serializers.SerializerMethodField()

    def get_employee_name(self, obj):
        return obj.employee.full_name if obj.employee_id else ''

    def get_assigned_to_name(self, obj):
        return obj.assigned_to.username if obj.assigned_to_id else ''

    def validate(self, attrs):
        request = self.context.get('request')
        company = getattr(getattr(request, 'user', None), 'company', None)
        employee = attrs.get('employee', getattr(self.instance, 'employee', None))
        assignee = attrs.get('assigned_to', getattr(self.instance, 'assigned_to', None))
        if company and employee and employee.company_id != company.id:
            raise serializers.ValidationError({'employee': 'Employee does not belong to this company.'})
        if company and assignee and assignee.company_id != company.id:
            raise serializers.ValidationError({'assigned_to': 'User does not belong to this company.'})
        if 'status' in attrs and attrs['status'] == 'completed' and self.instance and self.instance.status == 'cancelled':
            raise serializers.ValidationError({'status': 'A cancelled task cannot be completed.'})
        return attrs

    class Meta:
        model = WorkflowTask
        fields = [
            'id', 'employee', 'employee_name', 'assigned_to', 'assigned_to_name',
            'task_type', 'title', 'description', 'priority', 'status',
            'due_date', 'source_type', 'source_id', 'created_at', 'completed_at',
        ]
        read_only_fields = [
            'id', 'company', 'employee_name', 'assigned_to_name',
            'source_type', 'source_id', 'created_at', 'completed_at',
        ]


class RuleSerializer(serializers.ModelSerializer):
    event_type_label = serializers.CharField(source='get_event_type_display', read_only=True)

    class Meta:
        model = WorkflowRule
        fields = [
            'id', 'event_type', 'event_type_label', 'name', 'enabled',
            'create_task', 'send_notification', 'task_type', 'priority',
            'days_before', 'created_at',
        ]
        read_only_fields = ['id', 'company', 'created_at', 'event_type_label']

    def validate_days_before(self, value):
        if value > 365:
            raise serializers.ValidationError('Automation window cannot exceed 365 days.')
        return value
