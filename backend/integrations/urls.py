from django.urls import path
from .views import IntegrationHubView, ImportJobDetailView, ImportJobExecuteView, ImportJobListView, ImportJobRollbackView, ImportJobUploadView
from .connector_views import OAuthStartView, OAuthCallbackView, IntegrationDisconnectView, IntegrationSyncView, AccountingCatalogSyncView, AccountingMappingView, PayrollJournalExportView, IntegrationScheduleView, SyncConflictListView, SyncConflictResolveView

urlpatterns = [
    path('oauth/<str:provider>/start/', OAuthStartView.as_view(), name='oauth-start'),
    path('oauth/<str:provider>/callback/', OAuthCallbackView.as_view(), name='oauth-callback'),
    path('connections/<str:provider>/disconnect/', IntegrationDisconnectView.as_view(), name='integration-disconnect'),
    path('connections/<str:provider>/sync/', IntegrationSyncView.as_view(), name='integration-sync'),
    path('', IntegrationHubView.as_view(), name='integration-hub'),
    path('imports/', ImportJobListView.as_view(), name='import-jobs'),
    path('imports/upload/', ImportJobUploadView.as_view(), name='import-upload'),
    path('imports/<int:pk>/', ImportJobDetailView.as_view(), name='import-detail'),
    path('imports/<int:pk>/execute/', ImportJobExecuteView.as_view(), name='import-execute'),
    path('imports/<int:pk>/rollback/', ImportJobRollbackView.as_view(), name='import-rollback'),
]
# Advanced accounting and sync operations
urlpatterns += [
    path('connections/<str:provider>/accounting-sync/', AccountingCatalogSyncView.as_view(), name='accounting-sync'),
    path('connections/<str:provider>/accounting-mapping/', AccountingMappingView.as_view(), name='accounting-mapping'),
    path('connections/<str:provider>/schedule/', IntegrationScheduleView.as_view(), name='integration-schedule'),
    path('payroll/<str:provider>/<int:payroll_id>/export/', PayrollJournalExportView.as_view(), name='payroll-journal-export'),
    path('conflicts/', SyncConflictListView.as_view(), name='sync-conflicts'),
    path('conflicts/<int:pk>/resolve/', SyncConflictResolveView.as_view(), name='sync-conflict-resolve'),
]
from .webhooks import ProviderWebhookView
urlpatterns += [path('webhooks/<str:provider>/', ProviderWebhookView.as_view(), name='provider-webhook')]
urlpatterns += [
    path('platform/provider-config/', __import__('integrations.views', fromlist=['PlatformIntegrationProviderConfigView']).PlatformIntegrationProviderConfigView.as_view(), name='platform-provider-config'),
    path('platform/provider-config/<str:provider>/toggle/', __import__('integrations.views', fromlist=['PlatformIntegrationProviderToggleView']).PlatformIntegrationProviderToggleView.as_view(), name='platform-provider-toggle'),
]
