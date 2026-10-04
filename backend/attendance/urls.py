from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AttendanceViewSet, BulkMarkView, ClockView

router = DefaultRouter()
router.register('records', AttendanceViewSet, basename='attendance')

urlpatterns = [
    # Under the router's own prefix, and listed first so they are matched before
    # `records/<pk>/` tries to read "clock" or "bulk" as a primary key.
    path('records/clock/', ClockView.as_view(), name='attendance-clock'),
    path('records/bulk/', BulkMarkView.as_view(), name='attendance-bulk-mark'),
] + router.urls
