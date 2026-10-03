from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.audit import audit
from accounts.permissions import AIPlanGateMixin, CanManageAIDrafts, IsAIPlanAvailable, IsCompanyActive, IsCompanyMember

from .models import AIConversation, AIMessage, AIProviderConfig
from .nvidia import NVIDIAError
from .serializers import AIConversationListSerializer, AIMessageSerializer
from .services import generate_reply, get_or_create_conversation

# The list view only needs enough to render a sidebar. Nested every message of
# every conversation made this payload grow without bound as chat history grew.
CONVERSATION_LIST_LIMIT = 30
# The model is only ever shown the most recent turns; don't return an unbounded
# thread from the detail endpoint either.
CONVERSATION_MESSAGE_LIMIT = 200



# AI is a paid feature from the Professional plan up. IsAIPlanAvailable is
# listed LAST in every permission_classes below, after each role check: DRF
# stops at the first failure, so a plan check placed earlier would offer an
# upgrade to someone whose role would have refused them anyway.

class AIConversationsView(AIPlanGateMixin, APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive, IsAIPlanAvailable]

    def get(self, request):
        rows = (
            AIConversation.objects
            .filter(company=request.user.company, user=request.user)
            .only('id', 'title', 'created_at', 'updated_at')[:CONVERSATION_LIST_LIMIT]
        )
        return Response(AIConversationListSerializer(rows, many=True).data)

    def post(self, request):
        prompt = str(request.data.get('message', '')).strip()
        if not prompt:
            return Response({'detail': 'Message is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(prompt) > 8000:
            return Response({'detail': 'Message is too long.'}, status=status.HTTP_400_BAD_REQUEST)

        conversation_id = request.data.get('conversation_id')
        try:
            conversation = get_or_create_conversation(request.user, conversation_id)
        except AIConversation.DoesNotExist:
            return Response({'detail': 'Conversation not found.'}, status=status.HTTP_404_NOT_FOUND)

        # generate_reply persists the user's turn before it calls the provider, so a
        # provider failure returns 503 without erasing the question from history.
        try:
            reply, metadata = generate_reply(request.user, conversation, prompt)
        except NVIDIAError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        assistant_message = AIMessage.objects.create(
            conversation=conversation,
            role='assistant',
            content=reply,
            model=(AIProviderConfig.objects.filter(is_active=True).values_list('chat_model', flat=True).first() or 'NVIDIA NIM'),
            metadata=metadata or {},
        )
        if conversation.title == 'New conversation':
            conversation.title = prompt[:80]
        conversation.save(update_fields=['title', 'updated_at'])

        audit(
            request.user,
            'ai_chat',
            f'Used HRCloudPay AI in conversation {conversation.id}',
            conversation.company,
            'ai_conversation',
            conversation.id,
            {'model': assistant_message.model or 'NVIDIA NIM'},
            request=request,
        )
        # `metadata` is the single field the client uses to decide whether an answer
        # was backed by verified data, and it is also what the serializer returns on
        # a later read - so a message renders identically live and reloaded.
        return Response({
            'conversation_id': conversation.id,
            # Lets the client update its conversation list in place rather than
            # refetching every thread after each send.
            'title': conversation.title,
            'updated_at': conversation.updated_at,
            'message': {
                'id': assistant_message.id,
                'role': assistant_message.role,
                'content': assistant_message.content,
                'created_at': assistant_message.created_at,
                'metadata': assistant_message.metadata,
            },
        }, status=status.HTTP_201_CREATED)


class AIConversationDetailView(AIPlanGateMixin, APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive, IsAIPlanAvailable]

    def _get_conversation(self, request, conversation_id):
        return AIConversation.objects.filter(
            id=conversation_id, company=request.user.company, user=request.user
        ).first()

    def get(self, request, conversation_id):
        conversation = self._get_conversation(request, conversation_id)
        if not conversation:
            return Response({'detail': 'Conversation not found.'}, status=404)
        messages = list(conversation.messages.order_by('-created_at', '-id')[:CONVERSATION_MESSAGE_LIMIT])
        messages.reverse()
        return Response({
            'id': conversation.id,
            'title': conversation.title,
            'created_at': conversation.created_at,
            'updated_at': conversation.updated_at,
            'messages': AIMessageSerializer(messages, many=True).data,
        })

    def delete(self, request, conversation_id):
        conversation = self._get_conversation(request, conversation_id)
        if not conversation:
            return Response({'detail': 'Conversation not found.'}, status=404)
        conversation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AIDraftView(AIPlanGateMixin, APIView):
    """Generate and persist a reviewable draft; this endpoint never writes HR records."""
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive, CanManageAIDrafts, IsAIPlanAvailable]

    def post(self, request):
        from .actions import draft_action
        from .models import AIDraft
        from .serializers import AIDraftSerializer
        action_type = str(request.data.get('type', '')).strip()
        context = request.data.get('context', '')
        title = str(request.data.get('title', '')).strip()[:200]
        try:
            draft = draft_action(action_type, context)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=400)
        except NVIDIAError as exc:
            return Response({'detail': str(exc)}, status=503)
        row = AIDraft.objects.create(
            company=request.user.company, created_by=request.user, type=action_type,
            title=title or dict(AIDraft.TYPE_CHOICES).get(action_type, 'AI draft'),
            context=str(context).strip(), content=draft, status='pending',
        )
        audit(request.user, 'ai_draft', f'Generated reviewable AI draft: {action_type}', row.company, 'ai_draft', row.id, {'type': action_type, 'status': 'pending'}, request=request)
        return Response({**AIDraftSerializer(row).data, 'requires_review': True, 'saved': True}, status=201)


class AIDraftsView(AIPlanGateMixin, APIView):
    # The list returns each draft's full `content` and `context` - warning letters
    # and payroll explanations naming real employees - so it is gated to the same
    # roles that may review a draft, not merely to company membership.
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive, CanManageAIDrafts, IsAIPlanAvailable]

    def get(self, request):
        from .models import AIDraft
        from .serializers import AIDraftSerializer
        rows = AIDraft.objects.filter(company=request.user.company).select_related('created_by', 'reviewed_by')[:50]
        return Response(AIDraftSerializer(rows, many=True).data)


class AIDraftDetailView(AIPlanGateMixin, APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive, CanManageAIDrafts, IsAIPlanAvailable]

    def get_object(self, request, draft_id):
        from .models import AIDraft
        return AIDraft.objects.filter(id=draft_id, company=request.user.company).select_related('created_by', 'reviewed_by').first()

    def get(self, request, draft_id):
        from .serializers import AIDraftSerializer
        draft = self.get_object(request, draft_id)
        if not draft:
            return Response({'detail': 'Draft not found.'}, status=404)
        return Response(AIDraftSerializer(draft).data)

    def patch(self, request, draft_id):
        from django.utils import timezone
        from .serializers import AIDraftSerializer
        draft = self.get_object(request, draft_id)
        if not draft:
            return Response({'detail': 'Draft not found.'}, status=404)
        status_value = str(request.data.get('status', '')).strip().lower()
        if status_value not in ('approved', 'rejected', 'pending'):
            return Response({'detail': 'Status must be approved, rejected, or pending.'}, status=400)
        # Review is a workflow decision only. It never sends, publishes, or mutates an HR record.
        draft.status = status_value
        draft.reviewed_by = request.user
        draft.reviewed_at = timezone.now()
        draft.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])
        audit(request.user, 'ai_draft_review', f'Reviewed AI draft {draft.id}: {status_value}', draft.company, 'ai_draft', draft.id, {'status': status_value, 'type': draft.type}, request=request)
        return Response(AIDraftSerializer(draft).data)
