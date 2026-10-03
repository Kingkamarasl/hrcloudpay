from rest_framework import serializers
from .models import IntegrationConnection, ImportJob


class IntegrationConnectionSerializer(serializers.ModelSerializer):
    provider_label = serializers.CharField(source='get_provider_display', read_only=True)

    class Meta:
        model = IntegrationConnection
        fields = ['id', 'provider', 'provider_label', 'status', 'display_name', 'external_account_id', 'last_synced_at', 'metadata']
        read_only_fields = ['status', 'last_synced_at', 'metadata']


class ImportJobListSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    source_label = serializers.CharField(source='get_source_type_display', read_only=True)

    class Meta:
        model = ImportJob
        fields = ['id', 'filename', 'source_type', 'source_label', 'status', 'entity_type', 'total_rows', 'valid_rows', 'warning_rows', 'error_rows', 'duplicate_rows', 'created_by_name', 'created_at', 'completed_at', 'rolled_back_at']

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.username if obj.created_by else 'System'


class ImportJobDetailSerializer(ImportJobListSerializer):
    class Meta(ImportJobListSerializer.Meta):
        fields = ImportJobListSerializer.Meta.fields + ['headers', 'mapping', 'rows', 'result', 'checksum', 'updated_at']
