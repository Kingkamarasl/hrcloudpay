"""The site's own favicon and iOS home-screen icon.

These two files are served from a **public, unauthenticated** route, which is a
deliberate exception to the rule every other uploaded file follows. It is worth
being explicit about why, because "public route serving user uploads" is
normally the exact thing to avoid:

* A browser requests a favicon before the visitor has any session - on a cold
  cache, on the public marketing pages, and for anyone who has never logged in.
  Routing it through ``views.serve_media`` would mean the icon silently fails to
  load for most of the audience, which is the same class of bug as the 404ing
  company logos fixed in the same pass.
* It is safe here because the content is the platform's own brand mark. It is
  not tenant data, is not derived from any user, and carries nothing personal.
  Nothing in this module may be reused to expose an object that a tenant
  uploaded.

Every response is re-encoded from the stored original rather than streamed
through. That is not fussiness: it guarantees the bytes served are exactly the
bytes this module produced, so a file that is simultaneously a valid image and
valid HTML - a polyglot - cannot survive, and any EXIF or ICC payload the
uploader attached does not reach every visitor.
"""
import io

from django.core.files.storage import default_storage
from django.http import HttpResponse, HttpResponseNotModified
from django.utils.http import http_date

from accounts.platform_models import SiteBranding

# A favicon is displayed at 16-32px and an iOS home-screen icon at 180px.
# Anything larger is wasted bytes served to every visitor, on every page load.
FAVICON_MAX_EDGE = 256
APPLE_TOUCH_ICON_SIZE = 180

# 512 KB is far above any legitimate favicon and far below anything that would
# make an unbounded upload a denial-of-service lever.
MAX_UPLOAD_BYTES = 512 * 1024

# SVG is excluded on purpose. It is a document format that can carry <script>,
# and this route is anonymous and same-origin with the app, so an SVG favicon
# would execute in the app's own origin for every visitor. Browsers do support
# SVG favicons, which is exactly why the exclusion has to be deliberate.
ALLOWED_FORMATS = frozenset({'PNG', 'JPEG', 'WEBP', 'ICO', 'GIF'})
ALLOWED_CONTENT_TYPES = frozenset({
    'image/png', 'image/jpeg', 'image/webp', 'image/x-icon',
    'image/vnd.microsoft.icon', 'image/gif',
})


class SiteIconError(ValueError):
    """The upload is not usable as a site icon."""


def _read_source(field_file):
    if not field_file or not getattr(field_file, 'name', ''):
        raise SiteIconError('No icon has been uploaded yet.')
    try:
        return field_file.read()
    except OSError as exc:
        # The object is named in the database but absent from the bucket, which
        # is a real state after a partial restore or a bad bucket policy.
        raise SiteIconError(f'The stored file could not be read: {exc}')


def _looks_like_svg(raw):
    """Sniff for SVG, which Pillow does not recognise as an image at all.

    Without this, an SVG upload is rejected with the generic "not a recognised
    image" message. That is true but useless: SVG is a format people reasonably
    expect to be allowed, and the actual reason it is refused - that it can
    carry script, and this route is anonymous and same-origin - is the one thing
    an administrator needs to hear.
    """
    head = raw[:512].lstrip()
    # Skip a UTF-8 BOM and XML declaration/doctype, which may both appear.
    return head.startswith(b'<?xml') or head.startswith(b'<svg') or (
        b'<svg' in head.lower()
    )


def normalise_site_icon(raw, *, apple_touch=False):
    """Re-encode an uploaded icon into a safe, correctly sized PNG.

    Returns the PNG bytes. Raises ``SiteIconError`` with a message fit to show a
    platform administrator, because the alternative - a 500 from deep inside
    Pillow - tells them nothing about which file is wrong.
    """
    if not raw:
        raise SiteIconError('The uploaded file was empty.')
    if len(raw) > MAX_UPLOAD_BYTES:
        raise SiteIconError(
            f'The file is {len(raw) // 1024} KB. The limit is '
            f'{MAX_UPLOAD_BYTES // 1024} KB - a site icon does not need to be large.'
        )

    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:  # pragma: no cover - Pillow is a declared dependency
        raise SiteIconError('Image support is unavailable on this server.')

    if _looks_like_svg(raw):
        raise SiteIconError(
            'SVG is not accepted for the site icon. An SVG is a document that '
            'can carry a <script> tag, and this icon is served to every visitor '
            'on every page without them being signed in, so an SVG could run '
            'code in this site\'s own origin. Upload a PNG instead - browsers '
            'render that at the same sizes.'
        )

    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except UnidentifiedImageError:
        raise SiteIconError(
            'That file is not a recognised image. Upload a PNG, JPEG, WebP, '
            'GIF or ICO file.'
        )
    except Image.DecompressionBombError:
        raise SiteIconError(
            'That image is too large to process. Resize it before uploading.'
        )
    except Exception as exc:
        raise SiteIconError(f'The image could not be read: {exc}')

    if image.format not in ALLOWED_FORMATS:
        raise SiteIconError(
            f'{image.format} images are not accepted. Use PNG, JPEG, WebP, '
            f'GIF or ICO. (SVG is refused because it can carry scripts.)'
        )

    # Every output format here supports an alpha channel, and flattening to
    # RGB would give a black background on a transparent PNG in some viewers.
    if image.mode not in ('RGBA', 'LA', 'P'):
        image = image.convert('RGBA')
    elif image.mode == 'P':
        image = image.convert('RGBA')
    elif image.mode == 'LA':
        image = image.convert('RGBA')

    if apple_touch:
        # iOS expects exactly 180x180 and applies its own rounded mask. A
        # non-square source is padded onto a transparent square rather than
        # stretched, because a stretched letterhead logo looks broken on a home
        # screen and there is no way for the OS to guess the intended framing.
        size = APPLE_TOUCH_ICON_SIZE
        canvas = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        inner = image.copy()
        inner.thumbnail((size, size), Image.LANCZOS)
        canvas.paste(inner, ((size - inner.width) // 2, (size - inner.height) // 2))
        image = canvas
    else:
        image.thumbnail((FAVICON_MAX_EDGE, FAVICON_MAX_EDGE), Image.LANCZOS)

    buffer = io.BytesIO()
    # optimise=True only helps PNG; passing it for other formats is harmless.
    image.save(buffer, format='PNG', optimize=True)
    return buffer.getvalue()


def _resolve(which):
    """The stored field for ``'favicon'`` or ``'apple_touch_icon'``."""
    branding = SiteBranding.objects.first()
    if branding is None:
        return None
    return getattr(branding, which)


def serve_favicon(request):
    return _serve_site_icon(request, 'favicon')


def serve_apple_touch_icon(request):
    return _serve_site_icon(request, 'apple_touch_icon')


def _serve_site_icon(request, which):
    field_file = _resolve(which)
    if field_file is None or not getattr(field_file, 'name', ''):
        # 204 rather than 404. A missing icon is a normal state before the
        # first upload, and a 404 for it on every single page load is log noise
        # that trains people to ignore the log. 204 says "nothing here" without
        # the browser logging an error or showing a broken-image affordance.
        return HttpResponse(status=204)

    try:
        raw = _read_source(field_file)
    except SiteIconError:
        return HttpResponse(status=204)

    try:
        png = normalise_site_icon(
            raw, apple_touch=(which == 'apple_touch_icon')
        )
    except SiteIconError:
        # The stored original is unreadable or in a format no longer accepted.
        # Serving a broken icon would be worse than serving none, and this is
        # recoverable by re-uploading.
        return HttpResponse(status=204)

    # ETag over the normalised bytes, so re-uploading an identical file is a
    # 304 rather than a fresh download, but any real change is picked up at once.
    etag = f'"{which}-{len(png)}-{hash(png) & 0xFFFFFFFF:08x}"'
    if request.META.get('HTTP_IF_NONE_MATCH') == etag:
        return HttpResponseNotModified(headers={'ETag': etag})

    response = HttpResponse(png, content_type='image/png')
    response['ETag'] = etag
    response['Last-Modified'] = http_date()
    # Revalidate every time rather than cache hard: a site icon is fetched
    # uncached by many corporate proxies, and an admin who uploads a new logo
    # should not have to wait out a long max-age to see it.
    response['Cache-Control'] = 'no-cache'
    # These are re-encoded PNGs produced above, never raw user bytes, but the
    # header costs nothing and states the invariant at the point it matters.
    response['X-Content-Type-Options'] = 'nosniff'
    return response
