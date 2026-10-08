from django.urls import path
from rest_framework.routers import DefaultRouter

from .import_views import (
    AttendanceImportApplyView,
    AttendanceImportPreviewView,
    AttendanceImportTemplateView,
)
from .views import (
    AttendanceMonthGridView,
    AttendanceViewSet,
    BulkMarkView,
    ClockView,
)

router = DefaultRouter()
router.register('records', AttendanceViewSet, basename='attendance')

urlpatterns = [
    # Under the router's own prefix, and listed first so they are matched before
    # `records/<pk>/` tries to read "clock" or "bulk" as a primary key.
    path('records/clock/', ClockView.as_view(), name='attendance-clock'),
    path('month-grid/', AttendanceMonthGridView.as_view(), name='attendance-month-grid'),
    path('records/bulk/', BulkMarkView.as_view(), name='attendance-bulk-mark'),
    path('imports/preview/', AttendanceImportPreviewView.as_view(),
         name='attendance-import-preview'),
    path('imports/apply/', AttendanceImportApplyView.as_view(),
         name='attendance-import-apply'),
    path('imports/template/', AttendanceImportTemplateView.as_view(),
         name='attendance-import-template'),
] + router.urls
