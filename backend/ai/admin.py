from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError

from .models import AIConversation, AIMessage, AIDraft, KnowledgeDocument, KnowledgeChunk, AIProviderConfig


class AIProviderConfigForm(forms.ModelForm):
    api_key = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text='Enter a new provider API key. It is encrypted before storage. Leave blank to keep the existing key.',
    )

    class Meta:
        model = AIProviderConfig
        exclude = ('api_key_encrypted',)

    def save(self, commit=True):
        instance = super().save(commit=False)
        value = self.cleaned_data.get('api_key', '').strip()
        if value:
            instance.set_api_key(value)
        if commit:
            instance.save()
        return instance


@admin.register(AIProviderConfig)
class AIProviderConfigAdmin(admin.ModelAdmin):
    form = AIProviderConfigForm
    list_display = ('display_name', 'provider', 'chat_model', 'embedding_model', 'is_active', 'updated_at')
    list_filter = ('is_active', 'provider')
    readonly_fields = ('provider', 'updated_at')
    fieldsets = (
        ('Provider', {'fields': ('provider', 'display_name', 'is_active')}),
        ('Credentials', {'fields': ('api_key',), 'description': 'AI credentials are site-wide and are not exposed to company users.'}),
        ('NVIDIA NIM endpoints', {'fields': ('chat_api_url', 'embeddings_api_url', 'chat_model', 'embedding_model')}),
        ('Generation', {'fields': ('temperature', 'max_tokens', 'request_timeout_seconds')}),
        ('System', {'fields': ('updated_at',)}),
    )

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_staff and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff and request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_active and request.user.is_staff and request.user.is_superuser and not AIProviderConfig.objects.exists()

    def has_change_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff and request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff and request.user.is_superuser

    def save_model(self, request, obj, form, change):
        if AIProviderConfig.objects.exclude(pk=obj.pk).exists() and not change:
            raise ValidationError('Only one AI provider configuration is supported.')
        super().save_model(request, obj, form, change)


@admin.register(AIConversation)
class AIConversationAdmin(admin.ModelAdmin):
    list_display = ('title', 'company', 'user', 'updated_at')
    search_fields = ('title', 'user__email', 'company__name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(AIMessage)
class AIMessageAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'role', 'model', 'created_at')
    search_fields = ('content',)
    readonly_fields = ('conversation', 'role', 'content', 'model', 'created_at')


@admin.register(AIDraft)
class AIDraftAdmin(admin.ModelAdmin):
    list_display = ('title', 'type', 'company', 'status', 'created_by', 'updated_at')
    list_filter = ('status', 'type')
    search_fields = ('title', 'content', 'company__name')
    readonly_fields = ('created_at', 'updated_at', 'reviewed_at')


@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'company', 'source_type', 'is_active', 'updated_at')
    list_filter = ('source_type', 'is_active')
    search_fields = ('title', 'description', 'company__name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(KnowledgeChunk)
class KnowledgeChunkAdmin(admin.ModelAdmin):
    list_display = ('document', 'chunk_index', 'embedding_model', 'embedded_at')
    search_fields = ('content', 'document__title')
    readonly_fields = ('document', 'content', 'chunk_index', 'embedding', 'embedding_model', 'embedded_at', 'created_at')
