from django.contrib import admin
from .models import CompanyCountryProfile, StatutoryRule, StatutoryFilingRule, StatutoryFiling, StatutoryCompliancePack


@admin.register(CompanyCountryProfile)
class CompanyCountryProfileAdmin(admin.ModelAdmin):
    list_display = ('company', 'country_code', 'currency_code', 'payroll_frequency', 'onboarding_completed')
    list_filter = ('country_code', 'onboarding_completed')
    search_fields = ('company__name', 'company__email')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(StatutoryRule)
class StatutoryRuleAdmin(admin.ModelAdmin):
    list_display = ('country_code', 'code', 'rule_type', 'effective_from', 'effective_to', 'is_active')
    list_filter = ('country_code', 'rule_type', 'is_active')
    search_fields = ('code', 'name')
    readonly_fields = ('created_at', 'updated_at')

@admin.register(StatutoryFilingRule)
class StatutoryFilingRuleAdmin(admin.ModelAdmin):
    list_display = ('country_code', 'code', 'authority', 'frequency', 'due_day', 'effective_from', 'effective_to', 'is_active')
    list_filter = ('country_code', 'frequency', 'is_active', 'authority')
    search_fields = ('code', 'name', 'authority')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(StatutoryFiling)
class StatutoryFilingAdmin(admin.ModelAdmin):
    list_display = ('company', 'rule', 'period_end', 'due_date', 'status', 'amount', 'filed_at')
    list_filter = ('status', 'rule__country_code', 'rule__filing_type')
    search_fields = ('company__name', 'rule__code', 'reference')
    readonly_fields = ('created_at', 'updated_at', 'filed_at')


@admin.register(StatutoryCompliancePack)
class StatutoryCompliancePackAdmin(admin.ModelAdmin):
    list_display = ('company', 'country_code', 'payroll_run', 'period_end', 'status', 'filing_count', 'report_count', 'submitted_at')
    list_filter = ('country_code', 'status')
    search_fields = ('company__name',)
    readonly_fields = ('generated_at', 'updated_at', 'submitted_at')
