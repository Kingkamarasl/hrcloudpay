# Milestone 41 — HRCloudPay AI Knowledge / RAG

## Implemented
- Tenant-scoped AI knowledge documents.
- HR policies, employee handbooks, contract templates, HR guides, and other approved knowledge types.
- Automatic text chunking with overlap.
- Company-scoped retrieval using deterministic lexical relevance ranking.
- Retrieved knowledge is injected into NVIDIA NIM context only for the current company.
- Knowledge management endpoints for owner/admin/HR roles.
- Dashboard AI widget includes a lightweight Company AI Knowledge panel.
- Audit events for knowledge creation, update, and deletion.
- AI responses can expose knowledge source metadata alongside existing tool metadata.

## Safety
- Knowledge is isolated by `company` on every query.
- Only active documents are retrieved.
- Knowledge documents are not employee records and do not grant the model database access.
- AI remains read-only with respect to HR/payroll records.
- The model is instructed not to invent policy terms or treat retrieved policy text as database facts.

## API
- `GET/POST /api/ai/knowledge/`
- `PATCH/DELETE /api/ai/knowledge/<id>/`
- `POST /api/ai/knowledge/search/`

## Next upgrade
The retrieval layer is intentionally provider-neutral. A later phase can add NVIDIA hosted embeddings/vector search without changing the tenant/security model.
