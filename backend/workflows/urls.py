from django.urls import include,path
from rest_framework.routers import DefaultRouter
from .views import NotificationViewSet,TaskViewSet,RuleViewSet
router=DefaultRouter(); router.register('notifications',NotificationViewSet,basename='notification'); router.register('tasks',TaskViewSet,basename='workflow-task'); router.register('rules',RuleViewSet,basename='workflow-rule')
urlpatterns=[path('',include(router.urls))]
