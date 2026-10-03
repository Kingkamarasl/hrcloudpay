# Milestone 46 — OCR + Advanced Document Intelligence

HRCloudPay AI knowledge now supports OCR fallback for scanned/image-only PDF pages and preserves source locations for citations.

## Capabilities
- Text PDFs: normal extraction with page numbers.
- Scanned PDFs: pages without extractable text are rendered and OCR'd locally with PyMuPDF + Tesseract.
- DOCX: paragraph/table extraction with heading-derived section labels where available.
- Knowledge chunks now retain `page_number` and `section_label`.
- Semantic RAG citations can expose exact page/section metadata.
- Tenant isolation and existing NVIDIA embedding flow remain unchanged.

## Server requirements
Python packages:
- `pymupdf`
- `pytesseract`

The server must also have the Tesseract OCR executable installed and available on PATH. OCR is local and does not send document images to a third-party OCR API.

## Migration
```bash
cd backend
python manage.py migrate
```

## Privacy
Documents continue to be uploaded to Django first. OCR runs locally on the application server. Only extracted text is sent to NVIDIA for embeddings/AI when the configured AI workflow requires it.
