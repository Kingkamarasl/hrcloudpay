from pathlib import Path

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsCompanyActive, IsCompanyMember
from .models import IntegrationConnection, ImportJob, PROVIDER_CHOICES
from .serializers import IntegrationConnectionSerializer, ImportJobDetailSerializer, ImportJobListSerializer
from .services import parse_file, suggest_mapping, normalize_row, validate_rows, execute_import, rollback_import, ALLOWED_EXTENSIONS


class CompanyScopedMixin:
    def company(self, request):
        return request.user.company


def _can_manage_integrations(user):
    return bool(user and user.is_authenticated and user.role in ('owner', 'admin', 'hr'))


def _feature_or_403(key, company=None):
    from accounts.features import require_feature
    return require_feature(key, company=company)


class IntegrationHubView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]

    def get(self, request):
        if not _can_manage_integrations(request.user):
            return Response({'detail': 'Only owners, admins, or HR managers can access integrations.'}, status=403)
        from django.conf import settings
        from .oauth import PROVIDERS as OAUTH_PROVIDERS

        def provider_configured(provider):
            cfg = OAUTH_PROVIDERS.get(provider)
            if not cfg:
                return True
            from .models import IntegrationProviderConfig
            managed = IntegrationProviderConfig.objects.filter(provider=provider, enabled=True).first()
            if managed:
                return bool(managed.client_id and managed.encrypted_client_secret)
            client_id = getattr(settings, cfg['client_id'], '') or ''
            client_secret = getattr(settings, cfg['client_secret'], '') or ''
            return bool(client_id and client_secret)

        connections = {c.provider: c for c in IntegrationConnection.objects.filter(company=request.user.company)}
        providers = []
        for provider, label in PROVIDER_CHOICES:
            connection = connections.get(provider)
            from accounts.features import is_feature_enabled
            configured = provider_configured(provider)
            if provider in ('xero', 'quickbooks', 'microsoft', 'microsoft365') and not is_feature_enabled('integrations_oauth', company=request.user.company):
                configured = False
            status_value = connection.status if connection else ('available' if configured else 'not_configured')
            providers.append({
                'provider': provider,
                'label': label,
                'status': status_value,
                'configured': configured,
                'connected': bool(connection and connection.status == 'connected'),
                'connection_id': connection.id if connection else None,
                'external_account_id': connection.external_account_id if connection else '',
                'last_synced_at': connection.last_synced_at if connection else None,
                'metadata': connection.metadata if connection else {},
            })
        jobs = ImportJob.objects.filter(company=request.user.company)[:8]
        return Response({'providers': providers, 'recent_imports': ImportJobListSerializer(jobs, many=True).data})


class ImportJobListView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]

    def get(self, request):
        if not _can_manage_integrations(request.user):
            return Response({'detail': 'Only owners, admins, or HR managers can access import history.'}, status=403)
        jobs = ImportJob.objects.filter(company=request.user.company)
        return Response(ImportJobListSerializer(jobs, many=True).data)


class ImportJobUploadView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        ok, resp = _feature_or_403('integrations_file_import', request.user.company)
        if not ok:
            return resp
        if not _can_manage_integrations(request.user):
            return Response({'detail': 'Only owners, admins, or HR managers can import data.'}, status=403)
        upload = request.FILES.get('file')
        if not upload:
            return Response({'detail': 'Upload a CSV or .xlsx file.'}, status=status.HTTP_400_BAD_REQUEST)
        suffix = Path(upload.name).suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            return Response({'detail': 'Unsupported file type. Upload CSV or .xlsx.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            headers, source_rows, raw = parse_file(upload)
            mapping = suggest_mapping(headers)
            normalized = [normalize_row(row, mapping) for row in source_rows]
            rows = validate_rows(request.user.company, normalized)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response(
                {'detail': f'Could not process the uploaded file: {exc}'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        upload.seek(0)
        source_type = 'xlsx' if suffix == '.xlsx' else 'csv'
        job = ImportJob.objects.create(
            company=request.user.company,
            created_by=request.user,
            source_type=source_type,
            filename=upload.name[:255],
            uploaded_file=upload,
            checksum=ImportJob.checksum_bytes(raw),
            status='ready',
            headers=headers,
            mapping=mapping,
            rows=rows,
            total_rows=len(rows),
            valid_rows=sum(1 for row in rows if not row['errors']),
            warning_rows=sum(1 for row in rows if row['warnings']),
            error_rows=sum(1 for row in rows if row['errors']),
            duplicate_rows=sum(1 for row in rows if row.get('duplicate_employee_id')),
        )
        return Response(ImportJobDetailSerializer(job).data, status=status.HTTP_201_CREATED)


class ImportJobDetailView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]
    parser_classes = [JSONParser]

    def get_object(self, request, pk):
        return ImportJob.objects.get(pk=pk, company=request.user.company)

    def get(self, request, pk):
        if not _can_manage_integrations(request.user):
            return Response({'detail': 'Only owners, admins, or HR managers can access import details.'}, status=403)
        try:
            job = self.get_object(request, pk)
        except ImportJob.DoesNotExist:
            return Response({'detail': 'Import job not found.'}, status=404)
        return Response(ImportJobDetailSerializer(job).data)

    def patch(self, request, pk):
        if not _can_manage_integrations(request.user):
            return Response({'detail': 'Only owners, admins, or HR managers can edit import mappings.'}, status=403)
        try:
            job = self.get_object(request, pk)
        except ImportJob.DoesNotExist:
            return Response({'detail': 'Import job not found.'}, status=404)
        if job.status not in ('ready', 'draft'):
            return Response({'detail': 'Only a ready import can be edited.'}, status=400)
        mapping = request.data.get('mapping')
        if mapping is not None:
            job.mapping = mapping
            # Re-read source file and rebuild normalized rows with the new mapping.
            if not job.uploaded_file:
                return Response({'detail': 'Original import file is unavailable.'}, status=400)
            try:
                job.uploaded_file.open('rb')
                _headers, source_rows, _raw = parse_file(job.uploaded_file)
                normalized = [normalize_row(row, mapping) for row in source_rows]
                rows = validate_rows(job.company, normalized)
            except ValueError as exc:
                return Response({'detail': str(exc)}, status=400)
            job.rows = rows
            job.total_rows = len(rows)
            job.valid_rows = sum(1 for row in rows if not row['errors'])
            job.warning_rows = sum(1 for row in rows if row['warnings'])
            job.error_rows = sum(1 for row in rows if row['errors'])
            job.duplicate_rows = sum(1 for row in rows if row.get('duplicate_employee_id'))
            job.save(update_fields=['mapping','rows','total_rows','valid_rows','warning_rows','error_rows','duplicate_rows','updated_at'])
        return Response(ImportJobDetailSerializer(job).data)


class ImportJobExecuteView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]
    parser_classes = [JSONParser]

    def post(self, request, pk):
        try:
            job = ImportJob.objects.get(pk=pk, company=request.user.company)
        except ImportJob.DoesNotExist:
            return Response({'detail': 'Import job not found.'}, status=404)
        if request.user.role not in ('owner', 'admin', 'hr'):
            return Response({'detail': 'Only owners, admins, or HR managers can execute imports.'}, status=403)
        try:
            job = execute_import(job, request, update_duplicates=bool(request.data.get('update_duplicates', False)))
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        return Response(ImportJobDetailSerializer(job).data)


class ImportJobRollbackView(APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive]

    def post(self, request, pk):
        try:
            job = ImportJob.objects.get(pk=pk, company=request.user.company)
        except ImportJob.DoesNotExist:
            return Response({'detail': 'Import job not found.'}, status=404)
        if request.user.role not in ('owner', 'admin', 'hr'):
            return Response({'detail': 'Only owners, admins, or HR managers can roll back imports.'}, status=403)
        try:
            job = rollback_import(job, request)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        return Response(ImportJobDetailSerializer(job).data)

class PlatformIntegrationProviderConfigView(APIView):
    """Central OAuth credential vault controlled by Platform Admin."""
    from rest_framework.permissions import IsAdminUser
    permission_classes = [IsAdminUser]

    def get(self, request):
        from .models import IntegrationProviderConfig
        rows=[]
        for provider,label in IntegrationProviderConfig.PROVIDERS:
            obj=IntegrationProviderConfig.objects.filter(provider=provider).first()
            rows.append({'provider':provider,'name':label,'enabled':bool(obj and obj.enabled),'environment':obj.environment if obj else 'production','client_id':obj.client_id if obj else '','has_secret':bool(obj and obj.encrypted_client_secret),'configured_at':obj.configured_at if obj else None})
        return Response(rows)

    def post(self, request):
        from .models import IntegrationProviderConfig
        from accounts.secrets import encrypt_secret
        from django.utils import timezone
        from accounts.audit import audit
        provider=request.data.get('provider')
        if provider not in dict(IntegrationProviderConfig.PROVIDERS): return Response({'detail':'Unsupported integration provider.'},status=400)
        obj,_=IntegrationProviderConfig.objects.get_or_create(provider=provider)
        obj.client_id=str(request.data.get('client_id',obj.client_id) or '').strip()[:255]
        obj.environment=request.data.get('environment',obj.environment) if request.data.get('environment') in ('sandbox','production') else obj.environment
        if request.data.get('client_secret'): obj.encrypted_client_secret=encrypt_secret(str(request.data['client_secret']))
        if 'enabled' in request.data: obj.enabled=bool(request.data['enabled'])
        if obj.enabled and (not obj.client_id or not obj.encrypted_client_secret): return Response({'detail':'Client ID and client secret are required before enabling this integration.'},status=400)
        obj.configured_at=timezone.now(); obj.save()
        audit(request.user,'security',f'Updated {obj.get_provider_display()} OAuth configuration',None,'integration_provider_config',obj.id,{'enabled':obj.enabled,'environment':obj.environment})
        return Response({'provider':provider,'enabled':obj.enabled,'has_secret':bool(obj.encrypted_client_secret),'client_id':obj.client_id,'environment':obj.environment})

class PlatformIntegrationProviderToggleView(APIView):
    from rest_framework.permissions import IsAdminUser
    permission_classes=[IsAdminUser]
    def post(self,request,provider):
        from .models import IntegrationProviderConfig
        from accounts.audit import audit
        obj=IntegrationProviderConfig.objects.filter(provider=provider).first()
        if not obj: return Response({'detail':'Provider configuration not found.'},status=404)
        enabled=bool(request.data.get('enabled'))
        if enabled and (not obj.client_id or not obj.encrypted_client_secret): return Response({'detail':'Configure the OAuth client ID and secret first.'},status=400)
        obj.enabled=enabled; obj.save(update_fields=['enabled','updated_at'])
        audit(request.user,'security',f"{'Enabled' if enabled else 'Disabled'} {obj.get_provider_display()} OAuth integration",None,'integration_provider_config',obj.id,{'enabled':enabled})
        return Response({'enabled':obj.enabled})
