import mimetypes
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpResponse
from django.utils.http import http_date

from . import seo
from .media_access import may_access

# Formats a browser may render directly. This is an allow-list rather than a
# `startswith('image/')` test, because an uploaded file's bytes are
# attacker-supplied and `image/svg+xml` is a document format that carries
# <script>: served inline, it executes in the app's own origin with the user's
# session. SVG is therefore downloadable despite belonging to the image/* family.
#
# PDF is included deliberately. These are payslips, contracts and certificates
# that staff are meant to read, and forcing a download for each one is a worse
# product than the small residual risk. An HTML or SVG upload is not shown
# inline, and that is the vector that actually matters here.
INLINE_CONTENT_TYPES = frozenset({
    'application/pdf',
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/webp',
    'image/bmp',
})

# Characters allowed to survive into a Content-Disposition filename.
#
# Django's own Storage.generate_filename already runs get_valid_name, whose
# regex strips anything outside [-\w.], so a quote uploaded as a file name is
# removed before it ever reaches storage. This is the remaining guard for names
# that bypass that path - a data import or migration assigning document.name
# directly, or a storage backend with different validation - and it deliberately
# keeps spaces, apostrophes and brackets, which the Django regex also strips, so
# that "Ada O'Brien (2).txt" does not reach a user as "AdaOBrien2.txt". A single
# quote is safe inside a double-quoted header value; only a double quote, a
# backslash and a semicolon would break it or the parameter grammar.
_DISPOSITION_SAFE = frozenset(
    'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    "._- ()[]'"
)


def _safe_filename(name):
    cleaned = ''.join(c if c in _DISPOSITION_SAFE else '_' for c in name)
    # A name that was nothing but whitespace would otherwise yield an empty
    # filename, which is a worse header than a generic one.
    return cleaned.strip() or 'download'


def serve_media(request, path):
    """Serve an uploaded file, but only to someone entitled to it.

    Replaces the ``static()`` helper that ``urls.py`` used to register under
    ``DEBUG``. That helper maps a URL straight onto the filesystem with no
    identity check whatsoever, so simply enabling it in production would publish
    every identity document, contract, medical certificate and disciplinary
    letter in the system to anyone holding the URL.

    Two properties matter here beyond the access rule:

    * It goes through ``default_storage`` and streams with ``FileResponse``, so
      it works unchanged when ``STORAGES`` points at object storage. Reading via
      ``open(MEDIA_ROOT)/name`` would pin this to local disk and be the reason
      the storage backend could never be turned on.
    * ``nosniff`` plus an explicit content type, because a stored file's bytes
      are attacker-supplied. Without both, a file named ``x.jpg`` containing
      HTML is served as ``image/jpeg`` and some browsers will still render it.
    """
    if not request.user.is_authenticated:
        return HttpResponse('Authentication required.', status=401,
                            content_type='text/plain')

    # `path` arrives from the URL, so it is entirely attacker-controlled. A
    # storage name containing ".." or a backslash would escape the media
    # namespace and address any object in the bucket, including a tenant's
    # files under a different prefix. Reject those shapes outright rather than
    # relying on the storage backend to normalise them.
    if (
        not path
        or '\\' in path
        or path.startswith('/')
        or '..' in Path(path).parts
    ):
        raise Http404('Not found.')

    # A trailing-slash or empty component is not a valid storage name either.
    if any(part in ('', '.') for part in path.split('/')):
        raise Http404('Not found.')

    if not may_access(request.user, path):
        # 404 rather than 403: a requester who may not have this file should
        # not learn that it exists, and the two answers are otherwise
        # indistinguishable in practice.
        raise Http404('Not found.')

    try:
        handle = default_storage.open(path, 'rb')
    except FileNotFoundError:
        raise Http404('Not found.')
    except OSError:
        # Includes NotImplementedError-adjacent storage failures. An object
        # store that is unreachable must not become a 500 that leaks the
        # storage backend's name in the response.
        raise Http404('Not found.')

    name = Path(path).name
    content_type, _encoding = mimetypes.guess_type(name)
    response = FileResponse(handle, content_type=content_type or 'application/octet-stream')

    if content_type not in INLINE_CONTENT_TYPES:
        response['Content-Disposition'] = f'attachment; filename="{_safe_filename(name)}"'

    response['X-Content-Type-Options'] = 'nosniff'
    # Private documents must not sit in a shared or browser cache: a shared
    # workstation is a realistic threat for HR tooling.
    response['Cache-Control'] = 'private, no-store'
    return response


def serve_frontend(request):
    """
    Serves the built React app's index.html for '/' and any other
    non-API route, so React Router can take over client-side routing
    from there (e.g. /employees, /payroll, /activate/<id>/<token>).

    Requires `npm run build` to have been run in frontend/ first (see
    README) - that outputs into backend/frontend_dist/.

    index.html must never be cached without revalidation. It is the only file
    that names the current hashed bundles, so a cached copy keeps pointing at
    the previous build and the user is left on the old app. With no cache
    headers at all the browser falls back to heuristic caching and reuses that
    stale copy on an ordinary reload, which is precisely the "I reloaded and
    still see the old version" case. `no-cache` does not forbid storing the
    file - it forces revalidation - so the ETag below turns each reload into a
    cheap 304 when nothing changed.
    """
    index_path = Path(settings.BASE_DIR) / 'frontend_dist' / 'index.html'

    if not index_path.exists():
        return HttpResponse(
            "Frontend build not found.\n\n"
            "Run this once to build it:\n"
            "  cd frontend\n"
            "  npm install\n"
            "  npm run build\n\n"
            "Then reload this page.",
            content_type='text/plain',
            status=503,
        )

    stat = index_path.stat()
    etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'

    # Every public route is a route in the SPA, so they are all this same file.
    # Give each one its own title, description, canonical and robots tags, or a
    # crawler sees seven URLs all claiming to be the homepage.
    #
    # The ETag has to move with the route. It is derived only from the file's
    # mtime and size, which are identical for every URL, so leaving it alone
    # would let a cache hand back a 304 for /pricing to a request for /security
    # - and the client would then serve the pricing description on the security
    # page. A route in the ETag makes the conditional request mean what it says.
    page = seo.page_for_path(request.path)
    if page is not None:
        meta = seo.meta_for(page)
        html = seo.inject_into_html(
            index_path.read_text(encoding='utf-8'), meta,
        )
        etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}-{page.slug}"'
    else:
        html = index_path.read_text(encoding='utf-8')

    if request.META.get('HTTP_IF_NONE_MATCH') == etag:
        response = HttpResponse(status=304)
    else:
        response = HttpResponse(html, content_type='text/html')
    response['ETag'] = etag
    response['Last-Modified'] = http_date(stat.st_mtime)
    response['Cache-Control'] = 'no-cache, must-revalidate'
    return response


def sitemap_view(request):
    """`/sitemap.xml`, built from the published public pages.

    A view rather than a static file because the URL set and the last-modified
    dates come from the database. A hand-written sitemap.xml goes stale the
    moment someone unpublishes a page, and nothing points at the staleness.
    """
    return HttpResponse(
        seo.sitemap_xml(), content_type='application/xml; charset=utf-8',
    )


def robots_view(request):
    """`/robots.txt`.

    The one line that matters is `Disallow: /api/`. The OpenAPI schema and the
    Swagger UI are served AllowAny, so without it a crawler is invited to index
    the entire API surface - endpoint names, parameters, and the auth scheme.
    """
    return HttpResponse(
        seo.robots_txt(), content_type='text/plain; charset=utf-8',
    )
