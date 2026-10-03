from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    LeaveRequestViewSet, BreakRequestViewSet,
    LeaveAccrualPolicyView, RunLeaveAccrualView, LeaveBalanceListView, LeaveEncashmentView,
)

router = DefaultRouter()
router.register('requests', LeaveRequestViewSet, basename='leave-request')
router.register('break-requests', BreakRequestViewSet, basename='break-request')

urlpatterns = [
    path('accrual-policies/', LeaveAccrualPolicyView.as_view(), name='leave-accrual-policies'),
    path('accrue/', RunLeaveAccrualView.as_view(), name='leave-accrue'),
    path('balances/', LeaveBalanceListView.as_view(), name='leave-balances'),
    path('encashments/', LeaveEncashmentView.as_view(), name='leave-encashments'),
] + router.urls
