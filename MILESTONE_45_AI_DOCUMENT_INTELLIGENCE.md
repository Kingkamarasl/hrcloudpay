# Milestone 45 — AI Document Intelligence

HRCloudPay AI Knowledge can now ingest approved PDF and DOCX HR documents directly from the dashboard.

## Supported files
- PDF (`.pdf`)
- Microsoft Word (`.docx`)
- Maximum upload size: 10 MB
- Text extraction from normal/text PDFs and DOCX paragraphs/tables
- Scanned/image-only PDFs are rejected with a clear message; OCR is intentionally deferred

## Flow
1. Authorized Owner/Admin/HR user opens the AI Knowledge panel.
2. Selects a source type and uploads a PDF/DOCX.
3. Django validates the file and extracts text server-side.
4. The extracted text is chunked.
5. NVIDIA embeddings are generated using the site-wide Platform Admin configuration.
6. Chunks and embeddings are stored under the current company tenant.
7. The dashboard chatbot can retrieve the document through semantic RAG and show citations.

## Security
- Only company Owner/Admin/HR roles can upload/manage knowledge.
- Files and extracted content are associated with the current company.
- AI never receives the raw upload directly from the browser; Django extracts and controls the context.
- NVIDIA credentials remain in the Platform Admin AI configuration.

## Migration
```bash
cd backend
python manage.py migrate
```

## Dependencies
- pypdf
- python-docx

## Endpoint
`POST /api/ai/knowledge/upload/` as multipart form data with:
- `file`
- `title` (optional)
- `source_type`
- `description` (optional)

Existing manual paste/index functionality remains available.
