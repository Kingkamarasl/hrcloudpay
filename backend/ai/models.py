from django.conf import settings
from django.db import models


class AIConversation(models.Model):
    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='ai_conversations')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ai_conversations')
    title = models.CharField(max_length=200, default='New conversation')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-id']


class AIMessage(models.Model):
    ROLE_CHOICES = [('user', 'User'), ('assistant', 'Assistant')]
    conversation = models.ForeignKey(AIConversation, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    model = models.CharField(max_length=150, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']


class AIDraft(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending review'),
        ('approved', 'Approved for use'),
        ('rejected', 'Rejected'),
    ]
    TYPE_CHOICES = [
        ('employment_letter', 'Employment letter'),
        ('warning_letter', 'Warning letter'),
        ('payroll_explanation', 'Payroll explanation'),
        ('hr_report', 'HR report'),
    ]
    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='ai_drafts')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_ai_drafts')
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='reviewed_ai_drafts')
    type = models.CharField(max_length=40, choices=TYPE_CHOICES)
    title = models.CharField(max_length=200, blank=True)
    context = models.TextField()
    content = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-updated_at', '-id']
        indexes = [
            models.Index(fields=['company', 'status', '-updated_at']),
        ]

class KnowledgeDocument(models.Model):
    LIFECYCLE_CHOICES = [
        ('active', 'Active'), ('processing', 'Processing'), ('failed', 'Failed'), ('archived', 'Archived'),
    ]
    # Statuses whose stored text may be retrieved by the assistant. A 'failed'
    # document kept its chunks when embedding failed, so it still answers by keyword
    # ranking and surfaces under "Needs attention" with a reindex action; excluding
    # it would turn a recoverable indexing error into the document vanishing.
    RETRIEVABLE_STATUSES = ('active', 'failed')
    # Mirrors accounts.User.ROLE_CHOICES. Previously listed a phantom 'manager' role
    # that no user can hold and omitted the real 'finance' and 'department_manager'
    # roles. ai.access.ALL_COMPANY_ROLES is derived from the model at runtime and is
    # what access decisions actually use; tests assert the two stay in sync.
    DEFAULT_ACCESS_ROLES = ['owner', 'admin', 'hr', 'finance', 'department_manager', 'employee']
    SOURCE_CHOICES = [
        ('policy', 'HR policy'), ('handbook', 'Employee handbook'),
        ('contract_template', 'Contract template'), ('guide', 'HR guide'), ('other', 'Other'),
    ]
    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='ai_knowledge_documents')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_ai_knowledge_documents')
    title = models.CharField(max_length=200)
    description = models.CharField(max_length=500, blank=True)
    source_type = models.CharField(max_length=30, choices=SOURCE_CHOICES, default='other')
    content = models.TextField()
    source_file = models.FileField(upload_to='ai_knowledge/%Y/%m/', null=True, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    file_size = models.PositiveBigIntegerField(null=True, blank=True)
    mime_type = models.CharField(max_length=120, blank=True)
    extraction_status = models.CharField(max_length=30, default='manual', choices=[('manual','Manual content'),('extracted','Extracted'),('failed','Extraction failed')])
    is_active = models.BooleanField(default=True)
    lifecycle_status = models.CharField(max_length=20, choices=LIFECYCLE_CHOICES, default='active')
    version = models.PositiveIntegerField(default=1)
    version_group = models.UUIDField(null=True, blank=True, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.TextField(blank=True)
    last_indexed_at = models.DateTimeField(null=True, blank=True)
    allowed_roles = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['-updated_at', '-id']
        indexes = [models.Index(fields=['company','is_active','-updated_at'])]

class KnowledgeChunk(models.Model):
    document = models.ForeignKey(KnowledgeDocument, on_delete=models.CASCADE, related_name='chunks')
    content = models.TextField()
    chunk_index = models.PositiveIntegerField()
    page_number = models.PositiveIntegerField(null=True, blank=True)
    section_label = models.CharField(max_length=300, blank=True)
    embedding = models.JSONField(null=True, blank=True)
    embedding_model = models.CharField(max_length=150, blank=True)
    embedded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['document_id','chunk_index']
        constraints = [models.UniqueConstraint(fields=['document','chunk_index'], name='unique_ai_knowledge_chunk')]

class AIProviderConfig(models.Model):
    """Site-wide AI provider configuration. Managed only by Django site admins."""
    provider = models.CharField(max_length=40, default='nvidia_nim', editable=False)
    display_name = models.CharField(max_length=100, default='NVIDIA NIM')
    api_key_encrypted = models.TextField(blank=True)
    chat_api_url = models.URLField(default='https://integrate.api.nvidia.com/v1/chat/completions')
    embeddings_api_url = models.URLField(default='https://integrate.api.nvidia.com/v1/embeddings')
    # Provider defaults are verified live against the NVIDIA catalog. `qwen/qwen3.5-122b-a10b`
    # and `nvidia/llama-3.2-nemoretriever-300m-embed-v2` both reached end of life on
    # 2026-07-20 and now answer HTTP 410, so a fresh install was dead on arrival.
    chat_model = models.CharField(max_length=200, default='nvidia/nemotron-3-super-120b-a12b')
    embedding_model = models.CharField(max_length=200, default='nvidia/nemotron-3-embed-1b')
    temperature = models.FloatField(default=0.3)
    max_tokens = models.PositiveIntegerField(default=1200)
    request_timeout_seconds = models.PositiveIntegerField(default=90)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'AI provider configuration'
        verbose_name_plural = 'AI provider configuration'

    def __str__(self):
        return f'{self.display_name} ({"Active" if self.is_active else "Inactive"})'

    def set_api_key(self, value):
        from .provider import _fernet
        value = (value or '').strip()
        if value:
            self.api_key_encrypted = _fernet().encrypt(value.encode('utf-8')).decode('utf-8')

    def clear_api_key(self):
        self.api_key_encrypted = ''
