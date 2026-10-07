from django.urls import path

from .seo_views import PlatformSeoDetailView, PlatformSeoView
from .platform import (PlatformDashboardView, PlatformCompaniesView, PlatformCompanyDetailView, PlatformCompanyActivationView, PlatformCompanySuspensionView, PlatformCompanyResendActivationView, PlatformUsersView, PlatformUserDetailView, PlatformUsageView, PlatformSubscriptionsView, PlatformOnboardingView, PlatformAuditLogsView, PlatformNotificationsView, PlatformSupportView, PlatformAnalyticsView, PlatformBillingPlansView, PlatformPaymentProvidersView, PlatformPaymentProviderToggleView, PlatformSubscriptionStatusView, PlatformCompany360View, PlatformPaymentTransactionsView, PlatformSystemHealthView, PlatformSecurityCenterView, PlatformFeatureFlagsView, PlatformFeatureFlagDetailView, PlatformSupportDetailView, PlatformGlobalSearchView, PaymentWebhookView, BillingPlansView, CompanyBillingView, CompanyBillingCheckoutView, CompanyBillingVerifyView, PublicMarketingPageView, PlatformMarketingPagesView, PlatformMarketingPageDetailView, PlatformAIConfigView, PlatformAITestView, PlatformEmailConfigView, PlatformEmailTestView, PlatformSiteBrandingView, CompanyBillingCancelView, CompanyBillingReactivateView, CompanyBillingInvoicesView)
from .views import (
    PublicFeaturesView, ActivateView, CompanyAuditLogsView, CompanyUserDetailView,
    CompanyUsersView, CompanySettingsView, CompanyLogoView, LoginView, LogoutView, MeView, RegisterView,
)
from .password_reset import PasswordResetConfirmView, PasswordResetRequestView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('activate/<int:company_id>/<uuid:token>/', ActivateView.as_view(), name='activate'),
    path('login/', LoginView.as_view(), name='login'),
    # Password reset. Two endpoints rather than one because the confirm step
    # carries a secret and needs its own throttle bucket: a shared rate would
    # let one attacker exhaust the request allowance and lock a real user out of
    # their own recovery, or brute-force tokens against the confirm budget.
    path('password-reset/', PasswordResetRequestView.as_view(), name='password-reset'),
    path('password-reset/confirm/', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('me/', MeView.as_view(), name='me'),
    path('features/', PublicFeaturesView.as_view(), name='public-features'),
    path('marketing-pages/<slug:slug>/', PublicMarketingPageView.as_view(), name='public-marketing-page'),
    path('users/', CompanyUsersView.as_view(), name='company-users'),
        path('users/<int:user_id>/', CompanyUserDetailView.as_view(), name='company-user-detail'),
    path('company/', CompanySettingsView.as_view(), name='company-settings'),
    path('company/logo/', CompanyLogoView.as_view(), name='company-logo'),
    path('platform/dashboard/', PlatformDashboardView.as_view(), name='platform-dashboard'),
    path('platform/companies/', PlatformCompaniesView.as_view(), name='platform-companies'),
    path('platform/companies/<int:company_id>/', PlatformCompanyDetailView.as_view(), name='platform-company-detail'),
    path('platform/companies/<int:company_id>/activate/', PlatformCompanyActivationView.as_view(), name='platform-company-activate'),
    path('platform/companies/<int:company_id>/suspend/', PlatformCompanySuspensionView.as_view(), name='platform-company-suspend'),
    path('platform/companies/<int:company_id>/resend-activation/', PlatformCompanyResendActivationView.as_view(), name='platform-company-resend-activation'),
    path('platform/users/', PlatformUsersView.as_view(), name='platform-users'),
    path('platform/users/<int:user_id>/', PlatformUserDetailView.as_view(), name='platform-user-detail'),
    path('platform/usage/', PlatformUsageView.as_view(), name='platform-usage'),
    path('platform/subscriptions/', PlatformSubscriptionsView.as_view(), name='platform-subscriptions'),
    path('platform/billing-plans/', PlatformBillingPlansView.as_view(), name='platform-billing-plans'),
    path('platform/subscription-status/<int:company_id>/', PlatformSubscriptionStatusView.as_view(), name='platform-subscription-status'),
    path('platform/companies/<int:company_id>/360/', PlatformCompany360View.as_view(), name='platform-company-360'),
    path('platform/payment-transactions/', PlatformPaymentTransactionsView.as_view(), name='platform-payment-transactions'),
    path('platform/system-health/', PlatformSystemHealthView.as_view(), name='platform-system-health'),
    path('platform/security-center/', PlatformSecurityCenterView.as_view(), name='platform-security-center'),
    path('platform/feature-flags/', PlatformFeatureFlagsView.as_view(), name='platform-feature-flags'),
    path('platform/feature-flags/<int:flag_id>/', PlatformFeatureFlagDetailView.as_view(), name='platform-feature-flag-detail'),
    path('platform/seo/', PlatformSeoView.as_view(), name='platform-seo'),
    path('platform/seo/<slug:slug>/', PlatformSeoDetailView.as_view(), name='platform-seo-detail'),
    path('platform/marketing-pages/', PlatformMarketingPagesView.as_view(), name='platform-marketing-pages'),
    path('platform/marketing-pages/<slug:slug>/', PlatformMarketingPageDetailView.as_view(), name='platform-marketing-page-detail'),
    path('platform/support/<int:ticket_id>/', PlatformSupportDetailView.as_view(), name='platform-support-detail'),
    path('platform/search/', PlatformGlobalSearchView.as_view(), name='platform-global-search'),
    path('platform/payment-providers/', PlatformPaymentProvidersView.as_view(), name='platform-payment-providers'),
    path('platform/payment-providers/<str:provider>/toggle/', PlatformPaymentProviderToggleView.as_view(), name='platform-payment-provider-toggle'),
    path('platform/ai-config/', PlatformAIConfigView.as_view(), name='platform-ai-config'),
    path('platform/ai-config/test/', PlatformAITestView.as_view(), name='platform-ai-test'),
    path('platform/email-config/', PlatformEmailConfigView.as_view(), name='platform-email-config'),
    path('platform/email-config/test/', PlatformEmailTestView.as_view(), name='platform-email-test'),
    path('platform/site-branding/', PlatformSiteBrandingView.as_view(), name='platform-site-branding'),
    path('payments/webhook/<str:provider>/', PaymentWebhookView.as_view(), name='payment-webhook'),
    path('billing/plans/', BillingPlansView.as_view(), name='billing-plans'),
    path('billing/', CompanyBillingView.as_view(), name='company-billing'),
    path('billing/checkout/', CompanyBillingCheckoutView.as_view(), name='billing-checkout'),
    path('billing/verify/', CompanyBillingVerifyView.as_view(), name='billing-verify'),
    path('billing/cancel/', CompanyBillingCancelView.as_view(), name='billing-cancel'),
    path('billing/reactivate/', CompanyBillingReactivateView.as_view(), name='billing-reactivate'),
    path('billing/invoices/', CompanyBillingInvoicesView.as_view(), name='billing-invoices'),
    path('platform/onboarding/', PlatformOnboardingView.as_view(), name='platform-onboarding'),
    path('platform/audit-logs/', PlatformAuditLogsView.as_view(), name='platform-audit-logs'),
    path('platform/notifications/', PlatformNotificationsView.as_view(), name='platform-notifications'),
    path('platform/support/', PlatformSupportView.as_view(), name='platform-support'),
    path('platform/analytics/', PlatformAnalyticsView.as_view(), name='platform-analytics'),
    path('audit-logs/', CompanyAuditLogsView.as_view(), name='company-audit-logs'),
]
