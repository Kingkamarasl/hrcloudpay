from pathlib import Path

ALLOWED_EXTENSIONS = {'.pdf', '.docx'}
MAX_FILE_SIZE = 10 * 1024 * 1024


def _ocr_pdf_page(page):
    """OCR a PDF page when it has no usable text. Requires pymupdf + pytesseract."""
    try:
        import fitz
        import pytesseract
    except ImportError as exc:
        raise RuntimeError('OCR dependencies are not installed. Install pymupdf and pytesseract, and ensure Tesseract OCR is installed on the server.') from exc
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    from PIL import Image
    import io
    image = Image.open(io.BytesIO(pix.tobytes('png')))
    return (pytesseract.image_to_string(image) or '').strip()


def extract_pdf(uploaded_file):
    from pypdf import PdfReader
    uploaded_file.seek(0)
    reader = PdfReader(uploaded_file)
    pages = []
    ocr_pages = []
    pdf_for_ocr = None
    try:
        for number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or '').strip()
            if not text:
                if pdf_for_ocr is None:
                    try:
                        import fitz
                        uploaded_file.seek(0)
                        pdf_for_ocr = fitz.open(stream=uploaded_file.read(), filetype='pdf')
                    except ImportError as exc:
                        raise RuntimeError('OCR dependencies are not installed. Install pymupdf and pytesseract, and ensure Tesseract OCR is installed on the server.') from exc
                try:
                    text = _ocr_pdf_page(pdf_for_ocr[number - 1])
                except Exception:
                    text = ''
                if text:
                    ocr_pages.append(number)
            pages.append({'page_number': number, 'text': text, 'ocr': number in ocr_pages})
    finally:
        if pdf_for_ocr is not None:
            pdf_for_ocr.close()
    return pages, bool(ocr_pages)


def _docx_blocks(uploaded_file):
    from docx import Document
    uploaded_file.seek(0)
    doc = Document(uploaded_file)
    blocks = []
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if text:
            style = getattr(paragraph.style, 'name', '') if paragraph.style else ''
            section = text if style and 'heading' in style.lower() else ''
            blocks.append({'text': text, 'section': section})
    for table_index, table in enumerate(doc.tables, start=1):
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                blocks.append({'text': ' | '.join(cells), 'section': f'Table {table_index}'})
    return blocks


def extract_text(uploaded_file):
    """Extract document text with page/section metadata and OCR fallback for scanned PDFs."""
    name = uploaded_file.name or ''
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError('Only PDF and DOCX files are supported.')
    if uploaded_file.size and uploaded_file.size > MAX_FILE_SIZE:
        raise ValueError('The maximum document size is 10 MB.')

    if ext == '.pdf':
        pages, ocr_used = extract_pdf(uploaded_file)
        readable = [p for p in pages if p['text']]
        if not readable:
            raise ValueError('No readable text could be extracted from this PDF. OCR could not recover text.')
        return pages, ext, {'ocr_used': ocr_used, 'page_count': len(pages)}

    blocks = _docx_blocks(uploaded_file)
    if not blocks:
        raise ValueError('No readable text could be extracted from this DOCX document.')
    return blocks, ext, {'ocr_used': False, 'page_count': None}
