from django.urls import path
from .knowledge_views import KnowledgeDocumentsView, KnowledgeDocumentUploadView, KnowledgeDocumentDetailView, KnowledgeSearchView, KnowledgeReindexView
from .views import AIConversationDetailView, AIConversationsView, AIDraftView, AIDraftsView, AIDraftDetailView

urlpatterns = [
    path('knowledge/', KnowledgeDocumentsView.as_view(), name='ai-knowledge'),
    path('knowledge/upload/', KnowledgeDocumentUploadView.as_view(), name='ai-knowledge-upload'),
    path('knowledge/search/', KnowledgeSearchView.as_view(), name='ai-knowledge-search'),
    path('knowledge/reindex/', KnowledgeReindexView.as_view(), name='ai-knowledge-reindex'),
    path('knowledge/<int:document_id>/', KnowledgeDocumentDetailView.as_view(), name='ai-knowledge-detail'),
    path('conversations/', AIConversationsView.as_view(), name='ai-conversations'),
    path('conversations/<int:conversation_id>/', AIConversationDetailView.as_view(), name='ai-conversation-detail'),
    path('drafts/', AIDraftView.as_view(), name='ai-draft-create'),
    path('drafts/list/', AIDraftsView.as_view(), name='ai-drafts-list'),
    path('drafts/<int:draft_id>/', AIDraftDetailView.as_view(), name='ai-draft-detail'),
]
