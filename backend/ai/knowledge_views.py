from pathlib import Path
from uuid import UUID, uuid4

import logging

from django.core.files.storage import default_storage
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.audit import audit
from accounts.permissions import AIPlanGateMixin, IsAIPlanAvailable, IsCompanyActive, IsCompanyMember
from .access import (
    ALL_COMPANY_ROLES,
    can_manage_knowledge,
    document_accessible_to,
    parse_allowed_roles,
)
from .models import KnowledgeDocument, KnowledgeChunk, AIProviderConfig
from .knowledge import chunk_text, rank_chunks
from .embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    cosine_similarity,
    document_needs_reindex,
    embed_texts,
    embedding_is_current,
)
from .nvidia import NVIDIAError
from .document_extractors import extract_text, MAX_FILE_SIZE

logger = logging.getLogger(__name__)

# Extracted text is capped so one document cannot blow past provider payload limits.
# Truncation is reported to the caller rather than applied silently, because a
# policy handbook's effective dates and appendices live in the tail.
MAX_CONTENT_CHARS = 200000
INVALID_ROLES_DETAIL = 'At least one valid access role is required.'
RETRIEVABLE_STATUSES = KnowledgeDocument.RETRIEVABLE_STATUSES


def active_embedding_model():
    return AIProviderConfig.objects.filter(is_active=True).values_list('embedding_model', flat=True).first() or DEFAULT_EMBEDDING_MODEL


def _serialize(doc):
    return {
        'id': doc.id, 'title': doc.title, 'description': doc.description,
        'source_type': doc.source_type, 'source_type_label': doc.get_source_type_display(),
        'is_active': doc.is_active, 'lifecycle_status': doc.lifecycle_status,
        'version': doc.version, 'version_group': str(doc.version_group) if doc.version_group else None,
        'archived_at': doc.archived_at, 'processing_error': doc.processing_error,
        'last_indexed_at': doc.last_indexed_at,
        'allowed_roles': doc.allowed_roles or ALL_COMPANY_ROLES,
        'chunk_count': doc.chunks.count(),
        # A model change leaves stored vectors uncomparable, which used to degrade
        # semantic search silently. Surfaced so an admin can reindex.
        'needs_reindex': document_needs_reindex(doc, active_embedding_model()),
        'created_by': doc.created_by.get_full_name() or doc.created_by.email,
        'created_at': doc.created_at, 'updated_at': doc.updated_at,
        'file_name': doc.file_name, 'file_size': doc.file_size, 'mime_type': doc.mime_type,
        'extraction_status': doc.extraction_status,
    }


def _resolve_version_group(request, title):
    """Resolve which version chain a newly submitted document belongs to.

    Returns ``(group, previous, error_response)``. A client that knows which chain
    it is replacing sends ``version_group``; otherwise an existing active chain with
    the same title is continued, which keeps "re-upload the handbook to supersede
    it" working without the client tracking ids.

    The group is re-validated against this tenant and the chain query is
    company-scoped, so one company can never archive or inherit another company's
    chain even with a guessed group id. Superseding matters beyond tidiness:
    retrieval does not prefer newer versions, so two active copies of the same
    policy would let the assistant answer from the superseded one.
    """
    requested = str(request.data.get('version_group', '') or '').strip()
    if requested:
        # Validated before it reaches the query: a malformed id would otherwise
        # raise an uncaught ValidationError from the ORM and return a 500.
        try:
            UUID(requested)
        except (ValueError, AttributeError, TypeError):
            return None, None, Response({'detail': 'Invalid version group.'}, status=400)
        group = KnowledgeDocument.objects.filter(
            company=request.user.company, version_group=requested,
        ).values_list('version_group', flat=True).first()
        if group is None:
            return None, None, Response(
                {'detail': 'That version group does not belong to your company.'}, status=400,
            )
        previous = KnowledgeDocument.objects.filter(
            company=request.user.company, version_group=group, is_active=True,
        ).order_by('-version').first()
        return group, previous, None

    # Keyed on is_active, not lifecycle_status='active': a document whose embedding
    # failed is still the current version of that policy and must be supersedable,
    # otherwise a broken index makes the document permanently un-replaceable.
    previous = KnowledgeDocument.objects.filter(
        company=request.user.company, title=title, is_active=True,
    ).order_by('-version').first()
    group = previous.version_group if previous and previous.version_group else uuid4()
    return group, previous, None


def _archive_previous(previous):
    """Mark the superseded document archived, if there is one."""
    if not previous:
        return
    previous.is_active = False
    previous.lifecycle_status = 'archived'
    previous.archived_at = timezone.now()
    previous.save(update_fields=['is_active', 'lifecycle_status', 'archived_at', 'updated_at'])



# AI is a paid feature from the Professional plan up. IsAIPlanAvailable is
# listed LAST in every permission_classes below, after each role check: DRF
# stops at the first failure, so a plan check placed earlier would offer an
# upgrade to someone whose role would have refused them anyway.

class KnowledgeDocumentsView(AIPlanGateMixin, APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive, IsAIPlanAvailable]

    def get(self, request):
        rows = KnowledgeDocument.objects.filter(company=request.user.company).prefetch_related('chunks')[:200]
        # Knowledge managers administer every document in the tenant. Everyone else
        # only sees the documents they are actually allowed to retrieve, so a
        # restricted policy cannot be inferred from its title or author.
        if not can_manage_knowledge(request.user):
            rows = [row for row in rows if document_accessible_to(request.user, row)]
        return Response([_serialize(r) for r in rows])

    def post(self, request):
        if not can_manage_knowledge(request.user):
            return Response({'detail': 'Only owners, admins, and HR managers can manage AI knowledge.'}, status=403)
        title = str(request.data.get('title', '')).strip()[:200]
        content = str(request.data.get('content', '')).strip()
        source_type = str(request.data.get('source_type', 'other')).strip()
        description = str(request.data.get('description', '')).strip()[:500]
        roles = parse_allowed_roles(request.data.get('allowed_roles'))
        if not title or not content:
            return Response({'detail': 'Title and content are required.'}, status=400)
        if len(content) > MAX_CONTENT_CHARS:
            return Response({'detail': f'Document content is limited to {MAX_CONTENT_CHARS:,} characters.'}, status=400)
        if source_type not in dict(KnowledgeDocument.SOURCE_CHOICES):
            return Response({'detail': 'Invalid source type.'}, status=400)
        if roles is None:
            return Response({'detail': INVALID_ROLES_DETAIL}, status=400)
        group, previous, error = _resolve_version_group(request, title)
        if error is not None:
            return error
        _archive_previous(previous)
        doc = KnowledgeDocument.objects.create(
            company=request.user.company, created_by=request.user, title=title,
            description=description, source_type=source_type, content=content,
            version=previous.version + 1 if previous else 1,
            version_group=group, allowed_roles=roles, lifecycle_status='processing'
        )
        parts = chunk_text(content)
        chunks = [KnowledgeChunk(document=doc, content=p, chunk_index=i) for i, p in enumerate(parts)]
        try:
            vectors = embed_texts(parts, input_type='passage')
            model_name = active_embedding_model()
            for chunk, vector in zip(chunks, vectors):
                chunk.embedding = vector; chunk.embedding_model = model_name; chunk.embedded_at = timezone.now()
            doc.lifecycle_status = 'active'; doc.last_indexed_at = timezone.now(); doc.processing_error = ''
        except NVIDIAError as exc:
            vectors = []
            # The text is stored and still serves keyword search, but there are no
            # vectors. Marking it 'failed' is what surfaces it under "Needs
            # attention" with a reindex action, instead of showing a healthy green
            # Active pill over an error the admin can only see in the drawer.
            doc.lifecycle_status = 'failed'
            doc.processing_error = str(exc)
        KnowledgeChunk.objects.bulk_create(chunks)
        doc.save(update_fields=['lifecycle_status', 'last_indexed_at', 'processing_error', 'updated_at'])
        audit(request.user, 'ai_knowledge', f'Added AI knowledge document: {title}', doc.company, 'ai_knowledge_document', doc.id, {'chunks': len(parts), 'version': doc.version, 'allowed_roles': roles}, request=request)
        return Response(_serialize(doc), status=201)


class KnowledgeDocumentUploadView(AIPlanGateMixin, APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive, IsAIPlanAvailable]

    def post(self, request):
        if not can_manage_knowledge(request.user):
            return Response({'detail': 'Only owners, admins, and HR managers can upload AI knowledge.'}, status=403)
        upload = request.FILES.get('file')
        title = str(request.data.get('title', '')).strip()[:200]
        source_type = str(request.data.get('source_type', 'other')).strip()
        description = str(request.data.get('description', '')).strip()[:500]
        # Fail closed: an absent or empty selection is a 400, never "everyone".
        roles = parse_allowed_roles(request.data.get('allowed_roles'))
        if not upload:
            return Response({'detail': 'A PDF or DOCX file is required.'}, status=400)
        if upload.size and upload.size > MAX_FILE_SIZE:
            return Response({'detail': 'The maximum document size is 10 MB.'}, status=400)
        if not title:
            title = Path(upload.name).stem[:200]
        if source_type not in dict(KnowledgeDocument.SOURCE_CHOICES):
            return Response({'detail': 'Invalid source type.'}, status=400)
        if roles is None:
            return Response({'detail': INVALID_ROLES_DETAIL}, status=400)
        try:
            extracted, ext, extraction_meta = extract_text(upload)
        except (ValueError, RuntimeError) as exc:
            return Response({'detail': str(exc)}, status=400)
        if ext == '.pdf':
            content = '\n\n'.join(p['text'] for p in extracted if p['text']).strip()
        else:
            content = '\n'.join(b['text'] for b in extracted).strip()
        if not content:
            return Response({'detail': 'No readable text was found in that file.'}, status=400)
        if len(content) > MAX_CONTENT_CHARS:
            # Reported rather than silently truncated: a handbook's effective dates
            # and appendices live in the tail, and the AI would then answer as if
            # they did not exist.
            return Response({
                'detail': (
                    f'That file extracted to {len(content):,} characters of text, over the '
                    f'{MAX_CONTENT_CHARS:,} character limit. Split it into smaller documents '
                    'or reduce the text before uploading.'
                ),
            }, status=400)

        group, previous, error = _resolve_version_group(request, title)
        if error is not None:
            return error
        _archive_previous(previous)
        version = previous.version + 1 if previous else 1

        doc = KnowledgeDocument.objects.create(
            company=request.user.company, created_by=request.user, title=title,
            description=description, source_type=source_type, content=content,
            source_file=upload, file_name=upload.name[:255], file_size=upload.size,
            mime_type=getattr(upload, 'content_type', '') or '', extraction_status='extracted',
            lifecycle_status='processing', version=version, version_group=group, allowed_roles=roles,
        )
        if ext == '.pdf':
            parts = []
            for page in extracted:
                for part in chunk_text(page['text']):
                    parts.append((part, page['page_number'], ''))
        else:
            parts = []
            current_section = ''
            for block in extracted:
                if block.get('section'):
                    current_section = block['section']
                for part in chunk_text(block['text']):
                    parts.append((part, None, current_section))
        chunks = [KnowledgeChunk(document=doc, content=p, chunk_index=i, page_number=page, section_label=section) for i, (p, page, section) in enumerate(parts)]
        semantic = False
        error = ''
        try:
            vectors = embed_texts([p[0] for p in parts], input_type='passage')
            model_name = active_embedding_model()
            for chunk, vector in zip(chunks, vectors):
                chunk.embedding = vector; chunk.embedding_model = model_name; chunk.embedded_at = timezone.now()
            semantic = bool(vectors)
            doc.lifecycle_status = 'active'; doc.last_indexed_at = timezone.now()
        except NVIDIAError as exc:
            vectors = []; error = str(exc); doc.lifecycle_status = 'failed'
        doc.processing_error = error
        KnowledgeChunk.objects.bulk_create(chunks)
        doc.save(update_fields=['lifecycle_status', 'processing_error', 'last_indexed_at', 'updated_at'])
        audit(request.user, 'ai_knowledge', f'Uploaded AI knowledge document: {doc.title}', doc.company, 'ai_knowledge_document', doc.id, {'chunks': len(parts), 'version': version, 'semantic_indexed': semantic, 'ocr_used': extraction_meta.get('ocr_used', False), 'allowed_roles': roles}, request=request)
        return Response({**_serialize(doc), 'status': 'indexed', 'semantic_indexed': semantic, 'ocr_used': extraction_meta.get('ocr_used', False), 'page_count': extraction_meta.get('page_count')}, status=201)


class KnowledgeDocumentDetailView(AIPlanGateMixin, APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive, IsAIPlanAvailable]

    def get_object(self, request, document_id):
        return KnowledgeDocument.objects.filter(id=document_id, company=request.user.company).first()

    def delete(self, request, document_id):
        if not can_manage_knowledge(request.user):
            return Response({'detail': 'You do not have permission to manage AI knowledge.'}, status=403)
        doc = self.get_object(request, document_id)
        if not doc: return Response({'detail': 'Knowledge document not found.'}, status=404)
        # Capture company before delete() so the delete event stays attributable
        # to a tenant rather than being logged with a null company.
        title = doc.title; company = doc.company
        # Django does not remove FileField contents when the row is deleted, so the
        # uploaded file has to be removed explicitly. Without this every superseded
        # version leaks a copy into media storage.
        storage_path = doc.source_file.name if doc.source_file else None
        doc.delete()
        if storage_path:
            try:
                default_storage.delete(storage_path)
            except Exception:
                # A missing or already-removed file must not fail the delete: the
                # database row is gone either way and the row cascade succeeded.
                logger.exception('Could not remove stored file %s for deleted knowledge document', storage_path)
        audit(request.user, 'ai_knowledge', f'Deleted AI knowledge document: {title}', company, 'ai_knowledge_document', document_id, {}, request=request)
        return Response(status=204)

    def patch(self, request, document_id):
        if not can_manage_knowledge(request.user):
            return Response({'detail': 'You do not have permission to manage AI knowledge.'}, status=403)
        doc = self.get_object(request, document_id)
        if not doc: return Response({'detail': 'Knowledge document not found.'}, status=404)
        changes = {}
        if 'is_active' in request.data:
            doc.is_active = bool(request.data.get('is_active')); changes['is_active'] = doc.is_active
            if doc.is_active and doc.lifecycle_status == 'archived':
                doc.lifecycle_status = 'active'; doc.archived_at = None; changes['lifecycle_status'] = 'active'
            elif not doc.is_active:
                doc.lifecycle_status = 'archived'; doc.archived_at = timezone.now(); changes['lifecycle_status'] = 'archived'
        if 'title' in request.data:
            doc.title = str(request.data.get('title', '')).strip()[:200] or doc.title; changes['title'] = doc.title
        if 'description' in request.data:
            doc.description = str(request.data.get('description', '')).strip()[:500]; changes['description'] = doc.description
        if 'allowed_roles' in request.data:
            roles = parse_allowed_roles(request.data.get('allowed_roles'))
            if roles is None: return Response({'detail': INVALID_ROLES_DETAIL}, status=400)
            doc.allowed_roles = roles; changes['allowed_roles'] = roles
        if request.data.get('action') == 'archive':
            doc.is_active = False; doc.lifecycle_status = 'archived'; doc.archived_at = timezone.now(); changes['lifecycle_status'] = 'archived'
        if request.data.get('action') == 'restore':
            doc.is_active = True; doc.lifecycle_status = 'active'; doc.archived_at = None; changes['lifecycle_status'] = 'active'
        if not changes:
            # A request that changes nothing (the reindex flow used to send an empty
            # body purely to touch the URL) must not write a row or an audit event
            # claiming the document was updated.
            return Response(_serialize(doc))
        doc.save()
        audit(request.user, 'ai_knowledge', f'Updated AI knowledge document: {doc.title}', doc.company, 'ai_knowledge_document', doc.id, changes, request=request)
        return Response(_serialize(doc))


class KnowledgeSearchView(AIPlanGateMixin, APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive, IsAIPlanAvailable]
    def post(self, request):
        query = str(request.data.get('query', '')).strip()
        if not query: return Response({'detail': 'Query is required.'}, status=400)
        chunks = list(KnowledgeChunk.objects.filter(document__company=request.user.company, document__is_active=True, document__lifecycle_status__in=RETRIEVABLE_STATUSES).select_related('document'))
        chunks = [c for c in chunks if document_accessible_to(request.user, c.document)]
        semantic = []
        try:
            query_vector = embed_texts([query], input_type='query')[0]
            model_name = active_embedding_model()
            comparable = [c for c in chunks if embedding_is_current(c, model_name, len(query_vector))]
            semantic = [(cosine_similarity(query_vector, c.embedding), c) for c in comparable]
            semantic.sort(key=lambda item: (item[0], item[1].id), reverse=True); semantic = semantic[:8]
        # Semantic ranking is an enrichment over a keyword search that works on its
        # own. Any failure here (provider down, misconfiguration, unexpected
        # response shape) must fall back to keyword ranking rather than 500 a search
        # that can still be answered.
        except Exception:
            logger.exception('Semantic knowledge search failed; falling back to keyword ranking')
            semantic = []
        ranked = semantic if semantic else rank_chunks(chunks, query, limit=8)
        method = 'nvidia_semantic' if semantic else 'keyword_fallback'
        return Response({'query': query, 'method': method, 'results': [{'document_id': c.document_id, 'document_title': c.document.title, 'source_type': c.document.source_type, 'score': round(score, 3), 'content': c.content, 'page_number': c.page_number, 'section_label': c.section_label, 'version': c.document.version} for score, c in ranked]})


class KnowledgeReindexView(AIPlanGateMixin, APIView):
    permission_classes = [IsAuthenticated, IsCompanyMember, IsCompanyActive, IsAIPlanAvailable]

    def post(self, request):
        if not can_manage_knowledge(request.user):
            return Response({'detail': 'Only owners, admins, and HR managers can reindex AI knowledge.'}, status=403)
        document_id = request.data.get('document_id')
        qs = KnowledgeChunk.objects.filter(document__company=request.user.company, document__is_active=True, document__lifecycle_status__in=RETRIEVABLE_STATUSES)
        if document_id: qs = qs.filter(document_id=document_id)
        chunks = list(qs.select_related('document'))
        if not chunks: return Response({'detail': 'No knowledge chunks found.'}, status=404)
        # embed_texts batches internally. This call is unbounded - it covers every
        # active chunk in the tenant - so a single un-batched request would exceed
        # provider payload limits and fail the whole reindex.
        try: vectors = embed_texts([c.content for c in chunks], input_type='passage')
        except NVIDIAError as exc: return Response({'detail': str(exc)}, status=503)
        model_name = active_embedding_model()
        now = timezone.now()
        # Pair before filtering, so a chunk with an empty vector cannot shift every
        # later chunk onto the wrong embedding.
        pairs = [(c, v) for c, v in zip(chunks, vectors) if v]
        updated = [c for c, _v in pairs]
        for c, v in pairs:
            c.embedding = v; c.embedding_model = model_name; c.embedded_at = now
        KnowledgeChunk.objects.bulk_update(updated, ['embedding', 'embedding_model', 'embedded_at'])
        # Recover documents previously left in 'failed': a successful reindex is
        # exactly the remedy the "Retry index" action offers.
        KnowledgeDocument.objects.filter(id__in={c.document_id for c in updated}).update(
            last_indexed_at=now, processing_error='', lifecycle_status='active',
        )
        return Response({'status': 'indexed', 'chunks': len(updated), 'model': model_name})
