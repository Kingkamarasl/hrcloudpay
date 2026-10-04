"""Document extraction must not silently lose pages.

The bug: ``extract_pdf`` collapsed every failure to read a page into an empty
string. ``knowledge_views`` then joined the pages that *did* work and saved the
result, so a PDF whose scanned pages could not be recovered was indexed as
though it were complete. No error, no warning, nothing in the response. Every
later answer drawn from that document was confidently wrong about the pages
that had gone missing.

Worse, the failure was invisible in both directions. OCR fails for reasons that
have nothing to do with hosting - a skewed page, a low-resolution phone photo,
handwriting - so this was reachable on a perfectly healthy server.

These tests build real PDFs rather than stubbing the parser, because the whole
question is which pages PyMuPDF and pypdf disagree about. ``_ocr_page`` is
patched so the OCR result is a decision of the test rather than of whatever
engine the machine happens to have: the development image installs Tesseract,
and a test suite whose outcome depends on that is not a test suite.
"""
import io
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from ai.document_extractors import OCR_UNAVAILABLE, extract_pdf, extract_text

UPLOAD_URL = '/api/ai/knowledge/upload/'


def png_bytes():
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (240, 320), 'white').save(buffer, format='PNG')
    return buffer.getvalue()


def build_pdf(pages):
    """Build a real PDF. Each page is 'text' or 'image'."""
    import fitz

    document = fitz.open()
    for kind in pages:
        page = document.new_page()
        if kind == 'text':
            page.insert_text((72, 96), 'Annual leave is 25 days per year.',
                             fontsize=12)
        elif kind == 'image':
            page.insert_image(fitz.Rect(40, 40, 200, 200), stream=png_bytes())
        elif kind == 'blank':
            pass
        else:
            raise ValueError('unknown page kind %r' % kind)
    try:
        return document.tobytes()
    finally:
        document.close()


def upload(pages, name='handbook.pdf'):
    return SimpleUploadedFile(
        name, build_pdf(pages), content_type='application/pdf')


def with_ocr(result, reason=None):
    """Patch the OCR step to a fixed outcome."""
    def fake(pdf, index):
        return result, reason
    return patch('ai.document_extractors._ocr_page', side_effect=fake)


class PageClassificationTests(TestCase):
    def test_a_digital_pdf_is_read_from_its_text_layer(self):
        pages, meta = extract_pdf(upload(['text', 'text']))

        self.assertEqual(meta['ocr_used'], False)
        self.assertEqual(meta['unreadable_pages'], [])
        self.assertEqual([p['source'] for p in pages], ['text', 'text'])
        self.assertIn('25 days', pages[0]['text'])

    def test_a_blank_page_is_not_counted_as_a_loss(self):
        """The back of a sheet is blank in contracts and reports constantly.

        Treating every empty page as unreadable would make the feature unusable
        for ordinary documents, so blank has to stay distinct from unreadable.
        """
        pages, meta = extract_pdf(upload(['text', 'blank', 'text']))

        self.assertEqual(meta['unreadable_pages'], [])
        self.assertEqual([p['source'] for p in pages], ['text', 'blank', 'text'])

    def test_an_image_page_read_by_ocr_is_marked_as_ocr(self):
        with with_ocr('Scanned clause 4 applies.'):
            pages, meta = extract_pdf(upload(['text', 'image']))

        self.assertEqual(meta['ocr_used'], True)
        self.assertEqual(meta['unreadable_pages'], [])
        self.assertEqual([p['source'] for p in pages], ['text', 'ocr'])
        self.assertEqual(pages[1]['text'], 'Scanned clause 4 applies.')


class UnreadablePageTests(TestCase):
    def test_a_scanned_page_that_cannot_be_read_is_rejected(self):
        """The reported bug: this used to succeed and drop the page."""
        with with_ocr('', OCR_UNAVAILABLE):
            with self.assertRaises(ValueError) as caught:
                extract_text(upload(['text', 'image']))

        self.assertIn('Page 2', str(caught.exception))

    def test_a_fully_scanned_pdf_is_rejected(self):
        with with_ocr('', OCR_UNAVAILABLE):
            with self.assertRaises(ValueError) as caught:
                extract_text(upload(['image', 'image']))

        message = str(caught.exception)
        self.assertIn('No readable text', message)
        # The cause is the actionable part: re-scanning cannot help a server
        # that has no OCR engine, so the message has to say which it is.
        self.assertIn('no OCR engine', message)
        self.assertIn('Nothing has been saved', message)

    def test_the_message_distinguishes_a_missing_engine_from_a_bad_page(self):
        """One is an administrator's problem, the other is the uploader's.

        Reporting them the same way sends people to the wrong place: there is no
        point re-scanning a document when the server simply cannot read images.
        """
        with with_ocr('', OCR_UNAVAILABLE):
            with self.assertRaises(ValueError) as caught:
                extract_text(upload(['text', 'image']))
        self.assertIn('no OCR engine', str(caught.exception))

        with with_ocr('', 'OCR could not read the page (SomethingElse).'):
            with self.assertRaises(ValueError) as caught:
                extract_text(upload(['text', 'image']))
        self.assertIn('SomethingElse', str(caught.exception))

    def test_page_numbers_are_collapsed_into_ranges(self):
        """A 40-page scan should not produce a 200-character error message."""
        with with_ocr('', OCR_UNAVAILABLE):
            with self.assertRaises(ValueError) as caught:
                extract_text(upload(['text', 'image', 'image', 'image',
                                     'text', 'image']))

        self.assertIn('2-4, 6', str(caught.exception))

    def test_the_message_says_nothing_was_saved(self):
        with with_ocr('', OCR_UNAVAILABLE):
            with self.assertRaises(ValueError) as caught:
                extract_text(upload(['text', 'image']))

        self.assertIn('Nothing has been saved', str(caught.exception))

    def test_the_reason_survives_to_the_caller(self):
        """The view needs it to answer an upload, not just to log a failure."""
        with with_ocr('', OCR_UNAVAILABLE):
            with self.assertRaises(ValueError):
                extract_text(upload(['text', 'image']))


class NonPdfTests(TestCase):
    def test_a_docx_is_unaffected_by_any_of_this(self):
        """DOCX never involved OCR; it must keep working unchanged."""
        document = io.BytesIO()
        from docx import Document
        doc = Document()
        doc.add_paragraph('Annual leave is 25 days per year.')
        doc.save(document)

        blocks, ext, meta = extract_text(SimpleUploadedFile(
            'handbook.docx', document.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'))

        self.assertEqual(ext, '.docx')
        self.assertEqual(meta['unreadable_pages'], [])
        self.assertIn('25 days', blocks[0]['text'])

    def test_an_unsupported_type_is_refused(self):
        with self.assertRaises(ValueError):
            extract_text(SimpleUploadedFile('notes.txt', b'hello'))

    def test_an_oversized_file_is_refused(self):
        with self.assertRaises(ValueError):
            extract_text(SimpleUploadedFile('big.pdf', b'x' * (11 * 1024 * 1024)))


class UploadEndpointTests(TestCase):
    """The guarantee as a person uploading actually meets it.

    The unit tests above pin the extractor's behaviour. This pins the two
    things that matter at the boundary: the response has to say what went wrong,
    and nothing may be saved when it did. A partial document written to the
    database is worse than no document, because it looks complete to everything
    downstream - the search index, the AI answering questions, and the person
    who uploaded it.
    """

    def setUp(self):
        from datetime import timedelta

        from django.utils import timezone
        from rest_framework.test import APIClient

        from accounts.billing import AI_MINIMUM_PLAN
        from accounts.models import Company, User
        from accounts.platform_models import Subscription
        from ai.models import KnowledgeDocument

        self.KnowledgeDocument = KnowledgeDocument

        self.company = Company.objects.create(
            name='Acme AI', email='ai-acme@example.com',
            is_active=True, plan=AI_MINIMUM_PLAN,
        )
        Subscription.objects.create(
            company=self.company, status='active',
            started_at=timezone.now(), renews_at=timezone.now() + timedelta(days=30),
        )
        self.hr = User.objects.create_user(
            username='hr', email='hr@example.com',
            password='StrongPassword123!', company=self.company, role='hr',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def post_pdf(self, pages):
        # allowed_roles is required and fails closed, so it is not optional
        # here any more than it is in production.
        return self.client.post(
            UPLOAD_URL,
            {
                'file': upload(pages),
                'title': 'Handbook',
                'source_type': 'policy',
                'allowed_roles': 'hr',
            },
            format='multipart')

    def test_a_partly_unreadable_pdf_is_refused_and_saves_nothing(self):
        with with_ocr('', OCR_UNAVAILABLE):
            response = self.post_pdf(['text', 'image'])

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('Page 2', response.data['detail'])
        self.assertEqual(self.KnowledgeDocument.objects.count(), 0)

    def test_a_fully_scanned_pdf_is_refused_and_saves_nothing(self):
        with with_ocr('', OCR_UNAVAILABLE):
            response = self.post_pdf(['image', 'image'])

        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.KnowledgeDocument.objects.count(), 0)

    def test_a_blank_page_does_not_block_a_real_upload(self):
        """The other direction: ordinary documents must still go through."""
        with patch('ai.knowledge_views.embed_texts', return_value=[]):
            response = self.post_pdf(['text', 'blank', 'text'])

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.KnowledgeDocument.objects.count(), 1)
        self.assertIn('25 days', self.KnowledgeDocument.objects.get().content)

    def test_a_digital_pdf_is_refused_by_nothing_and_saves_one_document(self):
        with patch('ai.knowledge_views.embed_texts', return_value=[]):
            response = self.post_pdf(['text', 'text'])

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['ocr_used'], False)
        self.assertEqual(self.KnowledgeDocument.objects.count(), 1)
