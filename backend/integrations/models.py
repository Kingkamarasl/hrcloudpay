import hashlib

from django.conf import settings
from django.db import models

from accounts.models import Company

PROVIDER_CHOICES = [
    ('quickbooks', 'QuickBooks Online'),
    ('microsoft365', 'Microsoft 365'),
    ('xero', 'Xero'),
    ('google_workspace', 'Google Workspace'),
    ('api', 'HRCloudPay API'),
]
INTEGRATION_STATUS_CHOICES = [('available','Available'),('connected','Connected'),('attention','Needs attention'),('disconnected','Disconnected')]
IMPORT_SOURCE_CHOICES = [('csv','CSV'),('xlsx','Excel workbook')]
IMPORT_STATUS_CHOICES = [('draft','Draft'),('ready','Ready to import'),('importing','Importing'),('completed','Completed'),('completed_with_warnings','Completed with warnings'),('failed','Failed'),('rolled_back','Rolled back')]
SYNC_STATUS_CHOICES = [('queued','Queued'),('running','Running'),('completed','Completed'),('completed_with_warnings','Completed with warnings'),('failed','Failed')]

class IntegrationConnection(models.Model):
    ENVIRONMENT_CHOICES = [('sandbox','Sandbox'),('production','Production')]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='integration_connections')
    provider = models.CharField(max_length=40, choices=PROVIDER_CHOICES)
    status = models.CharField(max_length=20, choices=INTEGRATION_STATUS_CHOICES, default='available')
    environment = models.CharField(max_length=20, choices=ENVIRONMENT_CHOICES, default='production')
    display_name = models.CharField(max_length=120, blank=True)
    external_account_id = models.CharField(max_length=255, blank=True)
    access_token = models.TextField(blank=True)
    refresh_token = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['company','provider'], name='unique_integration_provider_per_company')]
        ordering = ['provider']
    def __str__(self): return f'{self.company.name} - {self.get_provider_display()}'

class OAuthState(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='integration_oauth_states')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    provider = models.CharField(max_length=40, choices=PROVIDER_CHOICES)
    state_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    @staticmethod
    def digest(state): return hashlib.sha256(state.encode()).hexdigest()

class ExternalRecord(models.Model):
    connection = models.ForeignKey(IntegrationConnection, on_delete=models.CASCADE, related_name='external_records')
    entity_type = models.CharField(max_length=80)
    external_id = models.CharField(max_length=255)
    local_object_type = models.CharField(max_length=100, blank=True)
    local_object_id = models.PositiveBigIntegerField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['connection','entity_type','external_id'], name='unique_external_record')]
        indexes = [models.Index(fields=['connection','entity_type','local_object_id'])]

class SyncJob(models.Model):
    connection = models.ForeignKey(IntegrationConnection, on_delete=models.CASCADE, related_name='sync_jobs')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    direction = models.CharField(max_length=30, default='import')
    entity_type = models.CharField(max_length=80, default='employee')
    status = models.CharField(max_length=40, choices=SYNC_STATUS_CHOICES, default='queued')
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ['-created_at']

class ImportJob(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='import_jobs')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_import_jobs')
    source_type = models.CharField(max_length=20, choices=IMPORT_SOURCE_CHOICES)
    filename = models.CharField(max_length=255)
    uploaded_file = models.FileField(upload_to='imports/%Y/%m/', null=True, blank=True)
    checksum = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=32, choices=IMPORT_STATUS_CHOICES, default='draft')
    entity_type = models.CharField(max_length=50, default='employee')
    headers = models.JSONField(default=list, blank=True)
    mapping = models.JSONField(default=dict, blank=True)
    rows = models.JSONField(default=list, blank=True)
    result = models.JSONField(default=dict, blank=True)
    total_rows = models.PositiveIntegerField(default=0)
    valid_rows = models.PositiveIntegerField(default=0)
    warning_rows = models.PositiveIntegerField(default=0)
    error_rows = models.PositiveIntegerField(default=0)
    duplicate_rows = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    rolled_back_at = models.DateTimeField(null=True, blank=True)
    class Meta: ordering = ['-created_at']
    def __str__(self): return f'IMP-{self.pk or "new"} {self.filename}'
    @staticmethod
    def checksum_bytes(data: bytes) -> str: return hashlib.sha256(data).hexdigest()


class AccountingMapping(models.Model):
    connection = models.OneToOneField(IntegrationConnection, on_delete=models.CASCADE, related_name='accounting_mapping')
    payroll_expense_account_id = models.CharField(max_length=255, blank=True)
    payroll_liability_account_id = models.CharField(max_length=255, blank=True)
    net_pay_account_id = models.CharField(max_length=255, blank=True)
    employer_contribution_account_id = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

class SyncSchedule(models.Model):
    connection = models.OneToOneField(IntegrationConnection, on_delete=models.CASCADE, related_name='sync_schedule')
    enabled = models.BooleanField(default=False)
    interval_minutes = models.PositiveIntegerField(default=1440)
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class SyncEvent(models.Model):
    connection = models.ForeignKey(IntegrationConnection, on_delete=models.CASCADE, related_name='sync_events')
    provider_event_id = models.CharField(max_length=255, blank=True)
    event_type = models.CharField(max_length=120)
    entity_type = models.CharField(max_length=80, blank=True)
    external_id = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['-created_at']

class SyncConflict(models.Model):
    RESOLUTION_CHOICES=[('pending','Pending'),('external','Use external'),('local','Keep HRCloudPay'),('merged','Merged')]
    connection = models.ForeignKey(IntegrationConnection, on_delete=models.CASCADE, related_name='sync_conflicts')
    entity_type = models.CharField(max_length=80)
    external_id = models.CharField(max_length=255)
    local_object_type = models.CharField(max_length=100, blank=True)
    local_object_id = models.PositiveBigIntegerField(null=True, blank=True)
    resolution = models.CharField(max_length=20, choices=RESOLUTION_CHOICES, default='pending')
    external_data = models.JSONField(default=dict, blank=True)
    local_data = models.JSONField(default=dict, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['-created_at']

class IntegrationProviderConfig(models.Model):
    """Platform-controlled OAuth credentials; secrets never belong in tenant settings."""
    PROVIDERS = [('quickbooks','QuickBooks Online'),('microsoft365','Microsoft 365'),('xero','Xero')]
    provider = models.CharField(max_length=40, choices=PROVIDERS, unique=True)
    enabled = models.BooleanField(default=False)
    client_id = models.CharField(max_length=255, blank=True)
    encrypted_client_secret = models.TextField(blank=True)
    environment = models.CharField(max_length=20, choices=[('sandbox','Sandbox'),('production','Production')], default='production')
    configured_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    def __str__(self): return f'{self.get_provider_display()} ({self.environment})'
