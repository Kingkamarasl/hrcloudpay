# Milestone 42 — NVIDIA Semantic RAG

HRCloudPay AI Knowledge now supports NVIDIA hosted embeddings for semantic retrieval.

## What changed
- Knowledge chunks store NVIDIA embedding vectors and embedding metadata.
- Documents are embedded during indexing when NVIDIA embeddings are configured.
- Knowledge search embeds the user's question with `input_type=query` and ranks chunks using cosine similarity.
- If NVIDIA embeddings are unavailable, the existing keyword retrieval remains available as a safe fallback.
- Added an owner/admin/HR-only reindex endpoint for existing knowledge.
- Company isolation remains enforced on all knowledge operations.

## NVIDIA configuration

The endpoint and embedding model are set on the `AIProviderConfig` row via **Platform admin → AI settings**, not through environment variables. An earlier version of this document described `NVIDIA_EMBEDDING_API_URL` / `NVIDIA_EMBEDDING_MODEL`; the application has never read them. Defaults live on the `embedding_model` field in `ai/models.py` and in `DEFAULT_EMBEDDING_MODEL` in `ai/embeddings.py`.

Current default: `nvidia/nemotron-3-embed-1b` (2048 dimensions). Its predecessor, `nvidia/llama-3.2-nemoretriever-300m-embed-v2`, was retired by NVIDIA on 2026-07-20 and now answers HTTP 410.

The embedding model uses NVIDIA's hosted `/v1/embeddings` endpoint and supports separate `passage` and `query` input modes, which are used respectively for indexing and search.

### Changing the embedding model

Vectors are compared against the model that produced them, so switching models makes every existing chunk stale. Documents are flagged as needing a reindex, and `/api/ai/knowledge/reindex/` rebuilds them. Forgetting this step silently degrades search to keyword fallback.

## Migration
```bash
cd backend
python manage.py migrate
```

## Reindex existing knowledge
POST `/api/ai/knowledge/reindex/` as an owner, admin, or HR manager. Optionally provide `document_id` to reindex one document.

## Search behavior
The search endpoint returns `method: nvidia_semantic` when semantic retrieval succeeds, otherwise `keyword_fallback`.

## Safety
Embeddings are generated only from company-scoped knowledge. No cross-company documents are included in retrieval queries.
