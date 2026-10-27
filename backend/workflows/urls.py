from django.urls import include,path
from rest_framework.routers import DefaultRouter
from .views import NotificationPreferenceView, NotificationViewSet,TaskViewSet,RuleViewSet
router=DefaultRouter(); router.register('notifications',NotificationViewSet,basename='notification'); router.register('tasks',TaskViewSet,basename='workflow-task'); router.register('rules',RuleViewSet,basename='workflow-rule')
urlpatterns=[path('preferences/', NotificationPreferenceView.as_view(), name='notification-preferences'), path('',include(router.urls))]
