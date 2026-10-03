from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from .models import Company, User
from .platform_models import (
    AuditChainState,
    AuditLog,
    FeatureFlag,
    PaymentEvent,
    PaymentPlan,
    PaymentProviderConfig,
    PaymentTransaction,
    BillingInvoice,
    PlatformNotification,
    Subscription,
    SupportTicket,
    SuspensionEvent,
)


@admin.register(Company)
class CompanyAdmin(ModelAdmin):
    list_display = ['name', 'email', 'country', 'plan', 'is_active', 'payroll_configured', 'created_at']
    list_filter = ['plan', 'is_active', 'payroll_configured', 'country']
    search_fields = ['name', 'email', 'phone']
    readonly_fields = ['activation_token', 'created_at', 'updated_at', 'logo_preview']
    list_fullwidth = True
    actions = ['activate_companies', 'suspend_companies']

    @admin.display(description='Logo preview')
    def logo_preview(self, obj):
        if getattr(obj, 'logo', None):
            return format_html(
                '<a href="{}" target="_blank"><img src="{}" style="max-height:60px;max-width:140px;border-radius:8px;" /></a>',
                obj.logo.url, obj.logo.url,
            )
        return 'No logo uploaded'

    @admin.action(description='Activate selected companies')
    def activate_companies(self, request, queryset):
        updated = queryset.filter(is_active=False).update(is_active=True)
        self.message_user(request, f'{updated} company(ies) activated.')

    @admin.action(description='Suspend selected companies')
    def suspend_companies(self, request, queryset):
        updated = queryset.filter(is_active=True).update(is_active=False)
        self.message_user(request, f'{updated} company(ies) suspended.')


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


@admin.register(User)
class CustomUserAdmin(BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    list_display = ['username', 'email', 'company', 'role', 'is_staff', 'is_active', 'last_login']
    list_filter = ['role', 'company', 'is_staff', 'is_active']
    search_fields = ['username', 'email', 'first_name', 'last_name', 'company__name']
    fieldsets = BaseUserAdmin.fieldsets + (
        ('HRCloudPay access', {'fields': ('company', 'role', 'managed_department')}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('HRCloudPay access', {'fields': ('company', 'role', 'managed_department')}),
    )


try:
    admin.site.unregister(Group)
except admin.sites.NotRegistered:
    pass


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    search_fields = ['name']


@admin.register(Subscription)
class SubscriptionAdmin(ModelAdmin):
    list_display = ['company', 'status', 'provider', 'billing_cycle', 'monthly_price', 'currency', 'trial_ends_at', 'renews_at']
    list_filter = ['status', 'provider', 'billing_cycle', 'currency']
    search_fields = ['company__name', 'company__email', 'external_customer_id', 'external_subscription_id']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(PaymentPlan)
class PaymentPlanAdmin(ModelAdmin):
    list_display = ['provider', 'plan', 'billing_cycle', 'amount', 'currency', 'created_at']
    list_filter = ['provider', 'plan', 'billing_cycle', 'currency']
    search_fields = ['plan']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(ModelAdmin):
    list_display = ['company', 'status', 'amount', 'currency', 'reference', 'created_at']
    list_filter = ['status', 'currency']
    search_fields = ['company__name', 'reference']
    readonly_fields = ['created_at', 'updated_at']
    list_fullwidth = True




@admin.register(BillingInvoice)
class BillingInvoiceAdmin(ModelAdmin):
    list_display = ['number', 'company', 'status', 'amount', 'currency', 'issued_at', 'paid_at']
    list_filter = ['status', 'currency']
    search_fields = ['number', 'company__name', 'company__email']
    readonly_fields = ['issued_at']

@admin.register(PaymentEvent)
class PaymentEventAdmin(ModelAdmin):
    list_display = ['provider', 'event_id', 'event_type', 'status', 'received_at']
    list_filter = ['provider', 'event_type', 'status']
    search_fields = ['event_id', 'event_type']
    readonly_fields = [field.name for field in PaymentEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PaymentProviderConfig)
class PaymentProviderConfigAdmin(ModelAdmin):
    list_display = ['provider', 'enabled', 'environment', 'updated_at']
    list_filter = ['enabled', 'environment', 'provider']
    search_fields = ['provider']
    readonly_fields = ['updated_at']


@admin.register(AuditLog)
class ImmutableAuditAdmin(ModelAdmin):
    list_display = ['created_at', 'action', 'company', 'actor', 'target_type', 'target_id']
    list_filter = ['action', 'target_type']
    search_fields = ['message', 'target_type', 'target_id', 'request_id', 'actor__username', 'company__name']
    readonly_fields = [field.name for field in AuditLog._meta.fields]
    list_fullwidth = True

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditChainState)
class AuditChainStateAdmin(ModelAdmin):
    list_display = ['key', 'last_sequence', 'last_hash']
    readonly_fields = ['key', 'last_sequence', 'last_hash']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FeatureFlag)
class FeatureFlagAdmin(ModelAdmin):
    list_display = ['name', 'key', 'enabled', 'rollout_percent', 'environment', 'created_at', 'updated_at']
    list_filter = ['enabled', 'environment']
    search_fields = ['name', 'key', 'description']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(SupportTicket)
class SupportTicketAdmin(ModelAdmin):
    list_display = ['subject', 'company', 'status', 'priority', 'assigned_to', 'created_at', 'updated_at']
    list_filter = ['status', 'priority']
    search_fields = ['subject', 'description', 'company__name', 'created_by__username']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(PlatformNotification)
class PlatformNotificationAdmin(ModelAdmin):
    list_display = ['title', 'company', 'level', 'is_active', 'created_at']
    list_filter = ['level', 'is_active']
    search_fields = ['title', 'message']
    readonly_fields = ['created_at']


@admin.register(SuspensionEvent)
class SuspensionEventAdmin(ModelAdmin):
    list_display = ['company', 'reason', 'suspended_by', 'started_at', 'ended_at']
    list_filter = ['started_at', 'ended_at']
    search_fields = ['company__name', 'reason']
    readonly_fields = ['started_at']
