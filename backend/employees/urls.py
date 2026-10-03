from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    DepartmentViewSet, EmployeeViewSet, ContractViewSet,
    EmployeeAllowanceViewSet, EmployeeDeductionViewSet, WarningLetterViewSet,
    EmployeePersonalDetailsViewSet, EmergencyContactViewSet, EmploymentEventViewSet, EmployeeDocumentViewSet, RequiredDocumentRuleViewSet, EmployeeStatutoryProfileViewSet, ComplianceDashboardView, DashboardSummaryView, HRRequestViewSet,
)

router = DefaultRouter()
router.register('departments', DepartmentViewSet, basename='department')
router.register('employees', EmployeeViewSet, basename='employee')
router.register('contracts', ContractViewSet, basename='contract')
router.register('allowances', EmployeeAllowanceViewSet, basename='allowance')
router.register('deductions', EmployeeDeductionViewSet, basename='deduction')
router.register('warning-letters', WarningLetterViewSet, basename='warning-letter')
router.register('personal-details', EmployeePersonalDetailsViewSet, basename='employee-personal-details')
router.register('emergency-contacts', EmergencyContactViewSet, basename='emergency-contact')
router.register('employment-events', EmploymentEventViewSet, basename='employment-event')
router.register('documents', EmployeeDocumentViewSet, basename='employee-document')
router.register('statutory-profiles', EmployeeStatutoryProfileViewSet, basename='employee-statutory-profile')
router.register('compliance-rules', RequiredDocumentRuleViewSet, basename='compliance-rule')
router.register('hr-requests', HRRequestViewSet, basename='hr-request')

urlpatterns = router.urls + [
    path('compliance-dashboard/', ComplianceDashboardView.as_view({'get':'list'}), name='compliance-dashboard'),
    path('dashboard-summary/', DashboardSummaryView.as_view(), name='dashboard-summary'),
]
