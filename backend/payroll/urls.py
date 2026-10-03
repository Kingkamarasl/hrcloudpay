from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ApprovePayrollRunView, PayPayrollRunView, PayrollConfigView, PayrollDashboardView,
    PayrollExportView, PayrollRunViewSet, PayrollSummaryView, PayslipViewSet, ProcessPayrollRunView,
    EmailPayslipsView, BankFileExportView, ComparePayrollRunsView,
    OvertimeRuleView, OvertimeEntryListCreateView, SalaryAdvanceListCreateView, PublicHolidayListCreateView,
)

router = DefaultRouter()
router.register('runs', PayrollRunViewSet, basename='payrollrun')
router.register('payslips', PayslipViewSet, basename='payslip')

urlpatterns = [
    path('config/', PayrollConfigView.as_view(), name='payroll-config'),
    path('runs/<int:run_id>/process/', ProcessPayrollRunView.as_view(), name='process-payroll-run'),
    path('runs/<int:run_id>/approve/', ApprovePayrollRunView.as_view(), name='approve-payroll-run'),
    path('runs/<int:run_id>/pay/', PayPayrollRunView.as_view(), name='pay-payroll-run'),
    path('runs/<int:run_id>/email-payslips/', EmailPayslipsView.as_view(), name='email-payslips'),
    path('runs/<int:run_id>/bank-file/', BankFileExportView.as_view(), name='bank-file'),
    path('compare/', ComparePayrollRunsView.as_view(), name='compare-runs'),
    path('overtime/rules/', OvertimeRuleView.as_view(), name='overtime-rules'),
    path('overtime/entries/', OvertimeEntryListCreateView.as_view(), name='overtime-entries'),
    path('advances/', SalaryAdvanceListCreateView.as_view(), name='salary-advances'),
    path('holidays/', PublicHolidayListCreateView.as_view(), name='public-holidays'),
    path('export/', PayrollExportView.as_view(), name='payroll-export'),
    path('summary/', PayrollSummaryView.as_view(), name='payroll-summary'),
    path('dashboard/', PayrollDashboardView.as_view(), name='payroll-dashboard'),
] + router.urls
