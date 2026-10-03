from rest_framework import serializers
from .models import AIConversation, AIMessage, AIDraft


class AIMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIMessage
        fields = ('id', 'role', 'content', 'model', 'metadata', 'created_at')


class AIConversationListSerializer(serializers.ModelSerializer):
    """Sidebar shape: identity and timestamps only, no nested message bodies."""

    class Meta:
        model = AIConversation
        fields = ('id', 'title', 'created_at', 'updated_at')


class AIConversationSerializer(serializers.ModelSerializer):
    """Full thread shape.

    Deliberately not used by the detail endpoint: nesting ``messages`` here reads
    every message of the conversation, so a long thread became an unbounded
    response payload. ``AIConversationDetailView`` serializes a capped slice
    instead. Left here for callers that genuinely want a whole thread.
    """

    messages = AIMessageSerializer(many=True, read_only=True)

    class Meta:
        model = AIConversation
        fields = ('id', 'title', 'created_at', 'updated_at', 'messages')


class AIDraftSerializer(serializers.ModelSerializer):
    type_label = serializers.CharField(source='get_type_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    created_by_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = AIDraft
        fields = ('id', 'type', 'type_label', 'title', 'context', 'content', 'status', 'status_label',
                  'created_by_name', 'reviewed_by_name', 'created_at', 'updated_at', 'reviewed_at')

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() or obj.created_by.email

    def get_reviewed_by_name(self, obj):
        if not obj.reviewed_by:
            return None
        return obj.reviewed_by.get_full_name() or obj.reviewed_by.email
