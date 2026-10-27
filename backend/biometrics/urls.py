from django.urls import include, path

from .views import (
    BiometricDeviceViewSet, BiometricEnrollmentViewSet,
    BiometricPunchIngestView, BiometricPunchListView,
    BiometricPunchReconcileView,
)

urlpatterns = [
    path('devices/', BiometricDeviceViewSet.as_view({'get': 'list',
                                                    'post': 'create'})),
    path('devices/<int:pk>/', BiometricDeviceViewSet.as_view(
        {'get': 'retrieve', 'patch': 'partial_update',
         'delete': 'destroy'})),
    path('enrollments/', BiometricEnrollmentViewSet.as_view(
        {'get': 'list', 'post': 'create'})),
    path('enrollments/<int:pk>/', BiometricEnrollmentViewSet.as_view(
        {'get': 'retrieve', 'delete': 'destroy'})),
    path('punches/', BiometricPunchListView.as_view()),
    path('punches/<int:pk>/reconcile/', BiometricPunchReconcileView.as_view()),
    path('punch/', BiometricPunchIngestView.as_view()),
]