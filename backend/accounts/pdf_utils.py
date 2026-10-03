"""Shared PDF helpers for rendering company branding on printed documents.

Each company owns its own logo, so every payslip and break-request form is
branded with *that company's* mark rather than a platform default. These
helpers keep the reportlab Image flowable creation in one place so the leave
and payroll PDF builders stay focused on layout.
"""
import io

from reportlab.platypus import Image as RLImage


# Logo is rendered as a small header mark - sized to fit the left of the title.
LOGO_MAX_WIDTH = 55
LOGO_MAX_HEIGHT = 55
MIN_LOGO_DIM = 12


def company_logo_image(company, max_width=LOGO_MAX_WIDTH, max_height=LOGO_MAX_HEIGHT):
    """
    Return a scaled reportlab Image flowable for the company's logo, or None
    when the company has no logo uploaded.

    The image is scaled to fit within ``max_width`` x ``max_height`` while
    preserving aspect ratio, and clamped to a sensible minimum so a tiny or
    oddly-proportioned upload never collapses the brand mark.
    """
    logo = getattr(company, 'logo', None)
    if not logo or not getattr(logo, 'name', ''):
        return None

    # Read the bytes rather than resolving a filesystem path.
    #
    # `FieldFile.path` only exists on a filesystem-backed storage: on S3 it
    # raises NotImplementedError. The old code caught that and returned None,
    # so enabling object storage would have silently dropped the company logo
    # from every payslip, break form and report with no error anywhere - a
    # branding regression that would have been reported as "the logo is missing"
    # long after the storage change that caused it.
    try:
        data = logo.read()
    except Exception:
        return None
    if not data:
        return None

    # Validate and read dimensions with Pillow (already a declared dependency).
    try:
        from PIL import Image as PILImage
        with PILImage.open(io.BytesIO(data)) as im:
            width, height = im.size
    except Exception:
        return None
    if not width or not height:
        w, h = max_width, max_height
    else:
        ratio = min(max_width / width, max_height / height)
        w = max(MIN_LOGO_DIM, round(width * ratio))
        h = max(MIN_LOGO_DIM, round(height * ratio))
    # reportlab accepts any file-like object, so the same bytes serve both the
    # measurement above and the rendered image. One read, no second request to
    # the storage backend.
    return RLImage(io.BytesIO(data), width=w, height=h, hAlign='LEFT')
