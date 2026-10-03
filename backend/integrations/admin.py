from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import IntegrationConnection, ImportJob, OAuthState, ExternalRecord, SyncJob


@admin.register(IntegrationConnection)
class IntegrationConnectionAdmin(ModelAdmin):
    list_display = ('company', 'provider', 'status', 'external_account_id', 'last_synced_at', 'updated_at')
    list_filter = ('provider', 'status')
    search_fields = ('company__name', 'company__email', 'external_account_id')
    readonly_fields = ('access_token', 'refresh_token', 'created_at', 'updated_at', 'last_synced_at')


@admin.register(ImportJob)
class ImportJobAdmin(ModelAdmin):
    list_display = ('id', 'company', 'filename', 'source_type', 'status', 'total_rows', 'valid_rows', 'error_rows', 'created_at')
    list_filter = ('source_type', 'status', 'entity_type')
    search_fields = ('filename', 'company__name', 'company__email')
    readonly_fields = ('created_at', 'updated_at', 'completed_at', 'rolled_back_at', 'checksum')

@admin.register(OAuthState)
class OAuthStateAdmin(ModelAdmin):
    list_display = ('provider','company','created_by','expires_at','used_at')
    readonly_fields = ('state_hash','created_at','used_at')

@admin.register(ExternalRecord)
class ExternalRecordAdmin(ModelAdmin):
    list_display = ('connection','entity_type','external_id','local_object_type','local_object_id','last_synced_at')
    search_fields = ('external_id','entity_type')
    readonly_fields = ('connection','entity_type','external_id','local_object_type','local_object_id','last_synced_at','metadata')

@admin.register(SyncJob)
class SyncJobAdmin(ModelAdmin):
    list_display = ('id','connection','direction','entity_type','status','created_at','completed_at')
    list_filter = ('status','direction','entity_type')
    readonly_fields = ('created_at','started_at','completed_at')

from .models import AccountingMapping, SyncSchedule, SyncEvent, SyncConflict
@admin.register(AccountingMapping)
class AccountingMappingAdmin(ModelAdmin):
    list_display=('connection','payroll_expense_account_id','payroll_liability_account_id','net_pay_account_id','updated_at')
    readonly_fields=('updated_at',)
@admin.register(SyncSchedule)
class SyncScheduleAdmin(ModelAdmin):
    list_display=('connection','enabled','interval_minutes','next_run_at','last_run_at')
    list_filter=('enabled',)
@admin.register(SyncEvent)
class SyncEventAdmin(ModelAdmin):
    list_display=('connection','event_type','entity_type','external_id','processed','created_at')
    list_filter=('processed','event_type')
    readonly_fields=('connection','provider_event_id','event_type','entity_type','external_id','payload','processed','processed_at','created_at')
@admin.register(SyncConflict)
class SyncConflictAdmin(ModelAdmin):
    list_display=('connection','entity_type','external_id','resolution','created_at','resolved_at')
    list_filter=('resolution','entity_type')
    readonly_fields=('connection','entity_type','external_id','local_object_type','local_object_id','external_data','local_data','created_at')
