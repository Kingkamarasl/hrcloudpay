from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import PayrollConfig, PayrollRun, Payslip, StatutoryContribution, TaxBracket


class TaxBracketInline(admin.TabularInline):
    model = TaxBracket
    extra = 1


class StatutoryContributionInline(admin.TabularInline):
    model = StatutoryContribution
    extra = 1


@admin.register(PayrollConfig)
class PayrollConfigAdmin(ModelAdmin):
    list_display = ['company', 'currency', 'pay_frequency', 'tax_calculation_enabled', 'updated_at']
    list_filter = ['pay_frequency', 'tax_calculation_enabled', 'currency']
    search_fields = ['company__name', 'company__email']
    inlines = [TaxBracketInline, StatutoryContributionInline]


@admin.register(PayrollRun)
class PayrollRunAdmin(ModelAdmin):
    list_display = ['company', 'period_start', 'period_end', 'status', 'run_date', 'approved_by']
    list_filter = ['status', 'company', 'period_start']
    search_fields = ['company__name']
    list_select_related = ['company', 'approved_by']


@admin.register(Payslip)
class PayslipAdmin(ModelAdmin):
    list_display = ['employee', 'payroll_run', 'gross_salary', 'tax_amount', 'net_salary', 'payment_method', 'paid_at', 'generated_at']
    list_filter = ['payment_method', 'generated_at']
    search_fields = ['employee__first_name', 'employee__last_name', 'employee__employee_code', 'payment_reference']
    list_select_related = ['employee', 'payroll_run']
    readonly_fields = ['generated_at']
