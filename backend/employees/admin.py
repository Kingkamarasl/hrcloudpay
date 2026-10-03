from django.contrib import admin
from .models import Department, Employee, Contract, WarningLetter, EmployeeAllowance, EmployeeDeduction, EmployeePersonalDetails, EmergencyContact, EmploymentEvent, EmployeeDocument, RequiredDocumentRule, EmployeeStatutoryProfile

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name','company','is_active','created_at')
    search_fields = ('name','company__name')
    list_filter = ('is_active',)

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('employee_code','first_name','last_name','company','job_title','employment_status','base_salary','hire_date')
    search_fields = ('employee_code','first_name','last_name','email','phone','company__name')
    list_filter = ('employment_status','company')

@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ('employee','contract_type','start_date','end_date','status')
    search_fields = ('employee__employee_code','employee__first_name','employee__last_name')
    list_filter = ('contract_type',)

@admin.register(WarningLetter)
class WarningLetterAdmin(admin.ModelAdmin):
    list_display = ('employee','warning_level','subject','issued_date','acknowledged')
    search_fields = ('employee__first_name','employee__last_name','subject')
    list_filter = ('warning_level','acknowledged')

@admin.register(EmployeeAllowance)
class EmployeeAllowanceAdmin(admin.ModelAdmin):
    list_display = ('employee','name','amount','is_percentage_of_base')
    search_fields = ('employee__first_name','employee__last_name','name')

@admin.register(EmployeeDeduction)
class EmployeeDeductionAdmin(admin.ModelAdmin):
    list_display = ('employee','name','amount','is_percentage_of_base')
    search_fields = ('employee__first_name','employee__last_name','name')

@admin.register(EmployeePersonalDetails)
class EmployeePersonalDetailsAdmin(admin.ModelAdmin):
    list_display = ('employee','date_of_birth','nationality','city','country','updated_at')
    search_fields = ('employee__employee_code','employee__first_name','employee__last_name','nationality','city')
    readonly_fields = ('created_at','updated_at')

@admin.register(EmergencyContact)
class EmergencyContactAdmin(admin.ModelAdmin):
    list_display = ('employee','name','relationship','phone','is_primary','updated_at')
    search_fields = ('employee__employee_code','employee__first_name','employee__last_name','name','phone')
    list_filter = ('is_primary',)

@admin.register(EmploymentEvent)
class EmploymentEventAdmin(admin.ModelAdmin):
    list_display = ('employee','event_type','effective_date','title','created_by','created_at')
    search_fields = ('employee__employee_code','employee__first_name','employee__last_name','title','description')
    list_filter = ('event_type',)
    readonly_fields = ('created_at',)

@admin.register(EmployeeDocument)
class EmployeeDocumentAdmin(admin.ModelAdmin):
    list_display = ('employee','document_type','title','issue_date','expiry_date','uploaded_by','created_at')
    search_fields = ('employee__employee_code','employee__first_name','employee__last_name','title')
    list_filter = ('document_type',)
    readonly_fields = ('created_at',)


@admin.register(RequiredDocumentRule)
class RequiredDocumentRuleAdmin(admin.ModelAdmin):
    list_display = ('name','company','document_type','contract_type','employee','warning_days','is_active')
    search_fields = ('name','company__name','employee__employee_code','employee__first_name','employee__last_name')
    list_filter = ('document_type','contract_type','is_active')
    readonly_fields = ('created_at',)


@admin.register(EmployeeStatutoryProfile)
class EmployeeStatutoryProfileAdmin(admin.ModelAdmin):
    list_display = ('employee','tax_region','social_security_region','updated_at')
    search_fields = ('employee__employee_code','employee__first_name','employee__last_name','tax_region')
    readonly_fields = ('created_at','updated_at')
