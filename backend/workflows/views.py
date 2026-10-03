from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.audit import audit
from accounts.permissions import IsCompanyActive, IsCompanyMember, CanManageHR

from .models import HRNotification, WorkflowTask, WorkflowRule
from .serializers import NotificationSerializer, TaskSerializer, RuleSerializer
from .services import run_due_automations


class Base(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive, CanManageHR]

    def get_queryset(self):
        return self.queryset.filter(company=self.request.user.company)


class NotificationViewSet(Base):
    serializer_class = NotificationSerializer
    queryset = HRNotification.objects.select_related('employee', 'recipient')
    http_method_names = ['get', 'post']

    def get_queryset(self):
        return super().get_queryset().filter(recipient=self.request.user)

    def create(self, request, *args, **kwargs):
        raise MethodNotAllowed('POST')

    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        return Response({'count': self.get_queryset().filter(read_at__isnull=True).count()})

    @action(detail=True, methods=['post'])
    def read(self, request, pk=None):
        obj = self.get_object()
        obj.read_at = timezone.now()
        obj.save(update_fields=['read_at'])
        return Response(self.get_serializer(obj).data)

    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        self.get_queryset().filter(read_at__isnull=True).update(read_at=timezone.now())
        return Response({'ok': True})


class TaskViewSet(Base):
    serializer_class = TaskSerializer
    queryset = WorkflowTask.objects.select_related('employee', 'assigned_to')

    def perform_create(self, serializer):
        serializer.save(company=self.request.user.company)

    def perform_update(self, serializer):
        before = self.get_object().status
        obj = serializer.save()
        if obj.status == 'completed' and before != 'completed':
            obj.completed_at = timezone.now()
            obj.save(update_fields=['completed_at'])
        elif obj.status != 'completed' and before == 'completed':
            obj.completed_at = None
            obj.save(update_fields=['completed_at'])
        audit(
            self.request.user, 'update', f'Updated HR workflow task {obj.title}',
            obj.company, 'workflow_task', obj.id, {'status': obj.status}, request=self.request,
        )

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        obj = self.get_object()
        if obj.status == 'cancelled':
            return Response({'detail': 'A cancelled task cannot be completed.'}, status=status.HTTP_400_BAD_REQUEST)
        if obj.status != 'completed':
            obj.status = 'completed'
            obj.completed_at = timezone.now()
            obj.save(update_fields=['status', 'completed_at'])
            audit(
                request.user, 'update', f'Completed HR workflow task {obj.title}',
                obj.company, 'workflow_task', obj.id, request=request,
            )
        return Response(self.get_serializer(obj).data)


class RuleViewSet(Base):
    serializer_class = RuleSerializer
    queryset = WorkflowRule.objects.all()

    def perform_create(self, serializer):
        serializer.save(company=self.request.user.company)

    @action(detail=False, methods=['post'])
    def run_now(self, request):
        return Response(run_due_automations(request.user.company))
