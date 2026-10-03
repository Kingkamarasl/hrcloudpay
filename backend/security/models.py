import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone
from accounts.models import Company, User

class SecuritySession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='security_sessions')
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='security_sessions', null=True, blank=True)
    secret_hash = models.CharField(max_length=64, unique=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    country = models.CharField(max_length=100, blank=True)
    user_agent = models.TextField(blank=True)
    device_label = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    mfa_verified = models.BooleanField(default=False)
    # When this session actually completed a TOTP challenge. Needed for
    # step-up auth: a boolean cannot express "verified 3 hours ago".
    mfa_verified_at = models.DateTimeField(null=True, blank=True)

    @property
    def active(self):
        return self.revoked_at is None and self.expires_at > timezone.now() and self.user.is_active

class MFADevice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='mfa_device')
    secret_encrypted = models.TextField()
    enabled = models.BooleanField(default=False)
    required = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class RecoveryCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='recovery_codes')
    code_hash = models.CharField(max_length=64, unique=True)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class LoginThrottle(models.Model):
    """Failed-login accounting for the account lockout policy.

    DRF's throttle buckets are per-IP only, which leaves the per-account
    attack wide open: rotating source addresses resets the budget, so nothing
    stopped unlimited attempts against one username. This is the per-account
    half of the defence and the state progressive lockout is derived from.
    """
    IDENTIFIER_TYPES = [('username','Username'), ('ip','IP address')]

    identifier = models.CharField(max_length=254)
    identifier_type = models.CharField(max_length=10, choices=IDENTIFIER_TYPES, default='username')
    failure_count = models.PositiveIntegerField(default=0)
    window_started_at = models.DateTimeField(default=timezone.now)
    locked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('identifier', 'identifier_type')]
        indexes = [models.Index(fields=['identifier_type', 'locked_until'])]

    def __str__(self):
        return f'{self.identifier_type}:{self.identifier}'

class SecurityEvent(models.Model):
    SEVERITIES = [('low','Low'),('medium','Medium'),('high','High'),('critical','Critical')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.CASCADE, related_name='security_events')
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='security_events')
    event_type = models.CharField(max_length=120)
    severity = models.CharField(max_length=20, choices=SEVERITIES, default='low')
    message = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['company','event_type','created_at']), models.Index(fields=['severity','created_at'])]

class SecurityIncident(models.Model):
    STATUSES = [('open','Open'),('investigating','Investigating'),('contained','Contained'),('resolved','Resolved'),('false_positive','False Positive')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.CASCADE, related_name='security_incidents')
    title = models.CharField(max_length=255)
    severity = models.CharField(max_length=20, choices=SecurityEvent.SEVERITIES, default='medium')
    status = models.CharField(max_length=30, choices=STATUSES, default='open')
    assigned_to = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='security_incidents_assigned')
    summary = models.TextField(blank=True)
    evidence = models.JSONField(default=list, blank=True)
    opened_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

class ThreatIndicator(models.Model):
    TYPES = [('ip','IP'),('domain','Domain'),('hash','File Hash'),('user_agent','User Agent')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.CASCADE, related_name='threat_indicators')
    indicator_type = models.CharField(max_length=30, choices=TYPES)
    value_hash = models.CharField(max_length=64, db_index=True)
    label = models.CharField(max_length=255, blank=True)
    severity = models.CharField(max_length=20, choices=SecurityEvent.SEVERITIES, default='high')
    active = models.BooleanField(default=True)
    source = models.CharField(max_length=100, default='internal')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

class RiskSignal(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.CASCADE, related_name='risk_signals')
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='risk_signals')
    signal_type = models.CharField(max_length=120)
    score = models.PositiveSmallIntegerField(default=0)
    evidence = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

class DeviceTrust(models.Model):
    STATES = [('unknown','Unknown'),('trusted','Trusted'),('untrusted','Untrusted'),('blocked','Blocked')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='trusted_devices')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='trusted_devices')
    device_hash = models.CharField(max_length=64)
    label = models.CharField(max_length=200, blank=True)
    state = models.CharField(max_length=20, choices=STATES, default='unknown')
    last_ip = models.GenericIPAddressField(null=True, blank=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    class Meta:
        constraints = [models.UniqueConstraint(fields=['company','user','device_hash'], name='uniq_device_per_user_company')]

class AccessRole(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='security_roles')
    name = models.CharField(max_length=120)
    permissions = models.JSONField(default=list)
    privileged = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['company','name'], name='uniq_security_role_company_name')]

class AccessRequest(models.Model):
    STATUSES = [('pending','Pending'),('approved','Approved'),('rejected','Rejected'),('expired','Expired'),('revoked','Revoked')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='access_requests')
    requester = models.ForeignKey(User, on_delete=models.CASCADE, related_name='access_requests')
    target_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='access_grants')
    requested_permissions = models.JSONField(default=list)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUSES, default='pending')
    expires_at = models.DateTimeField()
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='approved_access_requests')
    created_at = models.DateTimeField(auto_now_add=True)

class PAMSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='pam_sessions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pam_sessions')
    access_request = models.OneToOneField(AccessRequest, null=True, blank=True, on_delete=models.SET_NULL)
    permissions = models.JSONField(default=list)
    started_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    emergency = models.BooleanField(default=False)

class SSOProvider(models.Model):
    TYPES = [('oidc','OIDC'),('saml','SAML'),('entra','Microsoft Entra ID'),('google','Google Workspace')]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='sso_providers')
    provider_type = models.CharField(max_length=30, choices=TYPES)
    name = models.CharField(max_length=120)
    domain = models.CharField(max_length=255)
    config_encrypted = models.TextField()
    enabled = models.BooleanField(default=False)
    group_role_mapping = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class SCIMCredential(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='scim_credentials')
    token_hash = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=120)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

class AccessReview(models.Model):
    STATUSES = [('open','Open'),('closed','Closed')]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='access_reviews')
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=STATUSES, default='open')
    due_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

class AccessCertification(models.Model):
    DECISIONS = [('pending','Pending'),('certified','Certified'),('revoked','Revoked'),('change_requested','Change Requested')]
    review = models.ForeignKey(AccessReview, on_delete=models.CASCADE, related_name='certifications')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='access_certifications')
    permissions_snapshot = models.JSONField(default=list)
    decision = models.CharField(max_length=30, choices=DECISIONS, default='pending')
    reason = models.TextField(blank=True)
    decided_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    decided_at = models.DateTimeField(null=True, blank=True)

class DLPPolicy(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='dlp_policies')
    name = models.CharField(max_length=160)
    active = models.BooleanField(default=True)
    sensitive_fields = models.JSONField(default=list, blank=True)
    bulk_threshold = models.PositiveIntegerField(default=100)
    block_external_share = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

class DLPEvent(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='dlp_events')
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    event_type = models.CharField(max_length=100)
    object_type = models.CharField(max_length=100)
    object_count = models.PositiveIntegerField(default=1)
    blocked = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class ResponsePlaybook(models.Model):
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.CASCADE, related_name='response_playbooks')
    name = models.CharField(max_length=160)
    action = models.CharField(max_length=80)
    enabled = models.BooleanField(default=False)
    requires_approval = models.BooleanField(default=True)
    config = models.JSONField(default=dict, blank=True)

class ResponseAction(models.Model):
    playbook = models.ForeignKey(ResponsePlaybook, on_delete=models.CASCADE, related_name='actions')
    incident = models.ForeignKey(SecurityIncident, null=True, blank=True, on_delete=models.SET_NULL)
    requested_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='response_requests')
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='response_approvals')
    status = models.CharField(max_length=20, default='pending')
    result = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    executed_at = models.DateTimeField(null=True, blank=True)
