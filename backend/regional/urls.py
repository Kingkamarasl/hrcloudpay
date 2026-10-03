from django.urls import path
from .views import (
    CountryOptionsView, CompanyCountryExperienceView, CompanyOnboardingView,
    StatutoryPreviewView, ComplianceDashboardView, FilingBulkReviewView, StatutoryReportCatalogView, StatutoryReportExportView, FilingCalendarView, FilingGenerateView, FilingListView, FilingMarkFiledView, FilingExportView, CompliancePackListView, CompliancePackGenerateView, CompliancePackExportView, CompliancePackSubmitView, FilingReviewView, FilingApproveView, FilingPaymentView, FilingSubmitView, FilingCloseView,
)

urlpatterns = [
    path('countries/', CountryOptionsView.as_view(), name='country-options'),
    path('experience/', CompanyCountryExperienceView.as_view(), name='company-country-experience'),
    path('onboarding/', CompanyOnboardingView.as_view(), name='company-country-onboarding'),
    path('statutory-preview/', StatutoryPreviewView.as_view(), name='statutory-preview'),
    path('compliance-dashboard/', ComplianceDashboardView.as_view(), name='compliance-dashboard'),
    path('statutory-reports/', StatutoryReportCatalogView.as_view(), name='statutory-report-catalog'),
    path('statutory-reports/<str:report_code>/export/', StatutoryReportExportView.as_view(), name='statutory-report-export'),
]

urlpatterns += [
    path('filing-calendar/', FilingCalendarView.as_view(), name='filing-calendar'),
    path('filings/', FilingListView.as_view(), name='filing-list'),
    path('filings/bulk-review/', FilingBulkReviewView.as_view(), name='filing-bulk-review'),
    path('filings/generate/', FilingGenerateView.as_view(), name='filing-generate'),
    path('filings/<int:pk>/file/', FilingMarkFiledView.as_view(), name='filing-mark-filed'),
    path('filings/<int:pk>/export/', FilingExportView.as_view(), name='filing-export'),
    path('filings/<int:pk>/review/', FilingReviewView.as_view(), name='filing-review'),
    path('filings/<int:pk>/approve/', FilingApproveView.as_view(), name='filing-approve'),
    path('filings/<int:pk>/payment/', FilingPaymentView.as_view(), name='filing-payment'),
    path('filings/<int:pk>/submit/', FilingSubmitView.as_view(), name='filing-submit'),
    path('filings/<int:pk>/close/', FilingCloseView.as_view(), name='filing-close'),
]

urlpatterns += [
    path('compliance-packs/', CompliancePackListView.as_view(), name='compliance-pack-list'),
    path('compliance-packs/generate/<int:run_id>/', CompliancePackGenerateView.as_view(), name='compliance-pack-generate'),
    path('compliance-packs/<int:pk>/export/', CompliancePackExportView.as_view(), name='compliance-pack-export'),
    path('compliance-packs/<int:pk>/submit/', CompliancePackSubmitView.as_view(), name='compliance-pack-submit'),
]
