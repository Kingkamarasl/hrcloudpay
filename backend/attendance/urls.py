from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AttendanceViewSet, ClockView

router = DefaultRouter()
router.register('records', AttendanceViewSet, basename='attendance')

urlpatterns = [
    # Under the router's own prefix, and listed first so it is matched before
    # `records/<pk>/` tries to read "clock" as a primary key.
    path('records/clock/', ClockView.as_view(), name='attendance-clock'),
] + router.urls
