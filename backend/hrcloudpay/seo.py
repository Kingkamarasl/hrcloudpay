"""Per-route metadata for the public marketing pages, plus sitemap and robots.

Why this is server-side at all
------------------------------
Every public URL is a route in a Vite SPA, so all of them are served the same
``index.html``. The only metadata a crawler could read was one hardcoded title
and description describing the homepage: seven URLs, one description, and every
one of them claiming to be the homepage. That is not a ranking problem so much
as a legibility one - a crawler cannot tell the pricing page from the security
page.

The alternatives were both worse. Server-side rendering the marketing pages would
add a second rendering path that has to stay in step with the React components,
for content that is already editable as JSON. Doing nothing leaves seven URLs
that a search engine has no reason to distinguish.

So the tags are injected into the shell per route. The SPA still hydrates and
takes over; a crawler reads real, distinct, per-URL metadata. This is the same
trade-off every static-host SPA makes, and it does not pretend to be SSR.

What is deliberately not here
-----------------------------
No per-page ``<meta name="keywords">``. It has done nothing for search engines
for over a decade, and shipping one implies it matters.

No pagination, no ``lastmod`` for a page with no managed row. A ``lastmod`` that
does not track a real content change teaches crawlers to distrust the signal,
which is worse than omitting it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from django.conf import settings

# One source of truth for the public surface. The SPA owns these routes
# (App.jsx); the slug is what each page asks useMarketingPage() for, and the two
# are 1:1 apart from the homepage, which is `/` on the front and `home` in the
# database.
#
# The title and description here are fallbacks. A MarketingPage row's
# meta_title / meta_description win, because the point of putting them in the
# platform console is that an administrator can change them without a deploy.


@dataclass(frozen=True)
class PublicPage:
    """One indexable URL and how to describe it."""

    path: str
    slug: str
    title: str
    description: str
    priority: str
    changefreq: str


PUBLIC_PAGES: tuple[PublicPage, ...] = (
    PublicPage(
        path='/',
        slug='home',
        title='HRCloudPay - Smarter HR & Payroll for African Businesses',
        description=(
            'All-in-one HR, payroll and workforce management for African businesses. '
            'Country-specific statutory rules, attendance, leave, compliance and an '
            'AI HR assistant.'
        ),
        priority='1.0',
        changefreq='weekly',
    ),
    PublicPage(
        path='/platform',
        slug='platform',
        title='The HRCloudPay platform - one workspace for people operations',
        description=(
            'How HRCloudPay fits together: a single record per employee, payroll '
            'that reads from it, and statutory reporting that follows the country '
            'the employee actually works in.'
        ),
        priority='0.9',
        changefreq='monthly',
    ),
    PublicPage(
        path='/payroll-product',
        slug='payroll-product',
        title='Payroll - run pay runs for multiple countries from one system',
        description=(
            'Multi-country payroll with PAYE bands, statutory contributions and '
            'payslips computed per employee country, and a compliance gap shown '
            'rather than hidden when a rule is unverified.'
        ),
        priority='0.9',
        changefreq='monthly',
    ),
    PublicPage(
        path='/hr',
        slug='hr',
        title='HR - contracts, leave, attendance and documents in one record',
        description=(
            'Employee records with contracts, leave, attendance, documents and '
            'expiry tracking, so onboarding and offboarding are steps in a '
            'workflow rather than a folder of files.'
        ),
        priority='0.9',
        changefreq='monthly',
    ),
    PublicPage(
        path='/pricing',
        slug='pricing',
        title='Pricing - plans and what each one includes',
        description=(
            'HRCloudPay plans and limits, with per-employee and per-country '
            'coverage stated plainly.'
        ),
        priority='0.8',
        changefreq='weekly',
    ),
    PublicPage(
        path='/security',
        slug='security',
        title='Security - how HRCloudPay protects payroll and employee data',
        description=(
            'Encryption at rest and in transit, an append-only audit chain, '
            'role-based access and step-up verification for sensitive actions.'
        ),
        priority='0.8',
        changefreq='monthly',
    ),
    PublicPage(
        path='/about',
        slug='about',
        title='About HRCloudPay',
        description='Who builds HRCloudPay and what they believe payroll software should do.',
        priority='0.6',
        changefreq='monthly',
    ),
)

PAGES_BY_PATH = {page.path: page for page in PUBLIC_PAGES}
PAGES_BY_SLUG = {page.slug: page for page in PUBLIC_PAGES}

# Paths that must never be indexed, and why each one is named rather than
# covered by a blanket rule. `/api/` is the interesting one: the OpenAPI schema
# and Swagger UI are served with AllowAny, so without this they are crawlable
# and advertise the entire API surface to anyone who fetches robots.txt.
DISALLOWED_PREFIXES = (
    ('/api/', 'API surface, including the public schema and Swagger UI'),
    ('/admin/', 'Django admin'),
    ('/media/', 'Uploaded tenant documents, served to signed-in roles only'),
    ('/login', 'Session sign-in'),
    ('/register', 'Account creation'),
    ('/activate/', 'Single-use activation links'),
    ('/platform-admin', 'Platform console'),
)

_TITLE_RE = re.compile(r'<title>.*?</title>', re.IGNORECASE | re.DOTALL)
_DESCRIPTION_RE = re.compile(
    r'<meta\s+name=["\']description["\'][^>]*?/?>', re.IGNORECASE
)
_HEAD_CLOSE_RE = re.compile(r'\s*</head>', re.IGNORECASE)


def site_url() -> str:
    """The public origin, without a trailing slash.

    FRONTEND_URL rather than the request's Host: a canonical URL and a sitemap
    built from a Host header are attacker-controlled, and either would let anyone
    who can reach the site write canonical tags pointing at a domain they own.
    """
    return (settings.FRONTEND_URL or '').rstrip('/')


def page_for_path(path: str) -> PublicPage | None:
    """The public page a URL path serves, if it is one.

    Matching is on the normalised path so `/pricing`, `/pricing/` and
    `/pricing?utm_source=x` all resolve. The SPA routes on trailing-slash
    tolerance, so the sitemap and the metadata have to agree with it - a sitemap
    listing `/pricing/` for a page served at `/pricing` splits the canonical
    signal across two URLs.
    """
    if not path:
        return None
    clean = path.split('?', 1)[0].split('#', 1)[0]
    if len(clean) > 1:
        clean = clean.rstrip('/')
    return PAGES_BY_PATH.get(clean or '/')


def _managed(slug: str):
    """The MarketingPage row for a slug, or None.

    Deliberately tolerates the table not existing yet: a fresh database has no
    rows and may not have run the marketing migration. A missing row means "use
    the fallbacks", never a 500 on a public page.
    """
    try:
        from accounts.platform_models import MarketingPage
    except Exception:
        return None
    try:
        return MarketingPage.objects.filter(slug=slug).first()
    except Exception:
        return None


def meta_for(page: PublicPage) -> dict[str, str]:
    """Resolve one page's tags: managed values win, fallbacks fill the gaps.

    A row that is published but has no meta fields is not an error - it is the
    common case for a page nobody has edited yet, and it should serve the same
    description the codebase shipped rather than an empty one.
    """
    row = _managed(page.slug)
    meta = {
        'title': (getattr(row, 'meta_title', '') or '').strip() or page.title,
        'description': (
            (getattr(row, 'meta_description', '') or '').strip() or page.description
        ),
        'og_image': (getattr(row, 'og_image_url', '') or '').strip(),
        'noindex': bool(getattr(row, 'noindex', False)),
    }
    base = site_url()
    meta['canonical'] = f'{base}{page.path}' if base else page.path
    meta['robots'] = 'noindex, nofollow' if meta['noindex'] else 'index, follow'
    return meta


def render_tags(meta: dict[str, str]) -> str:
    """The head fragment for one page.

    Open Graph is included because link previews are how the site gets shared on
    Slack and LinkedIn, and without og:title a shared link renders as a bare URL.
    """
    def esc(value: str) -> str:
        return (
            (value or '')
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
        )

    parts = [
        f'<title>{esc(meta["title"])}</title>',
        f'<meta name="description" content="{esc(meta["description"])}" />',
        f'<meta name="robots" content="{esc(meta["robots"])}" />',
        f'<link rel="canonical" href="{esc(meta["canonical"])}" />',
        f'<meta property="og:type" content="website" />',
        f'<meta property="og:site_name" content="HRCloudPay" />',
        f'<meta property="og:title" content="{esc(meta["title"])}" />',
        f'<meta property="og:description" content="{esc(meta["description"])}" />',
        f'<meta property="og:url" content="{esc(meta["canonical"])}" />',
        f'<meta name="twitter:card" content="summary_large_image" />',
    ]
    if meta.get('og_image'):
        parts.append(f'<meta property="og:image" content="{esc(meta["og_image"])}" />')
    return '\n    '.join(parts)


def inject_into_html(html: str, meta: dict[str, str]) -> str:
    """Swap the shell's one-size title and description for this route's.

    Two substitutions and one insertion rather than a template render, because
    index.html is a build artefact: parsing and re-serialising it here would
    silently drop whatever the next Vite version emits, and this has to keep
    working across frontend upgrades without being edited.

    Idempotent by construction - the injected block is written between markers,
    so a re-run replaces it rather than stacking a second copy. That matters
    because the fallback path in index.html is itself a `<title>` tag: if the
    replacement ever failed silently, a page would end up advertising the
    homepage's description under the homepage's title.
    """
    tags = render_tags(meta)
    block = f'<!-- seo:start -->\n    {tags}\n    <!-- seo:end -->'

    # Strip any previous injection, plus the build's own title/description,
    # so this is a replacement rather than an addition.
    cleaned = re.sub(
        r'[ \t]*<!-- seo:start -->.*?<!-- seo:end -->', '', html, flags=re.DOTALL
    )
    cleaned = _TITLE_RE.sub('', cleaned)
    cleaned = _DESCRIPTION_RE.sub('', cleaned)

    if not _HEAD_CLOSE_RE.search(cleaned):
        # No </head> to anchor on. Returning the shell untouched means the page
        # still works for a human; it just carries no per-route metadata, which
        # is a smaller problem than serving broken HTML.
        return html

    # The whitespace run before </head> is consumed by the pattern rather than
    # added to. Matching only the tag itself meant each pass left its own
    # indentation behind and the next pass wrapped that instead, so injecting
    # twice produced visibly different HTML - which is how a re-run ends up
    # shipping a page that has quietly drifted from the shell it came from.
    return _HEAD_CLOSE_RE.sub(f'\n    {block}\n  </head>', cleaned, count=1)


def sitemap_entries() -> list[dict[str, str]]:
    """Indexable URLs, newest first where a last-modified is known.

    A page marked noindex is omitted rather than listed with a disallow hint.
    A sitemap is a statement about what to index; listing a page the same file
    asks not to index is a contradiction, and crawlers resolve contradictions
    conservatively - usually by ignoring the sitemap entry.
    """
    base = site_url()
    entries = []
    for page in PUBLIC_PAGES:
        row = _managed(page.slug)
        if getattr(row, 'noindex', False):
            continue
        entry = {
            'loc': f'{base}{page.path}' if base else page.path,
            'priority': page.priority,
            'changefreq': page.changefreq,
        }
        updated = getattr(row, 'updated_at', None)
        if updated is not None:
            entry['lastmod'] = updated.date().isoformat()
        entries.append(entry)
    return entries


def sitemap_xml() -> str:
    """The sitemap, as text.

    Built by hand rather than by a library because the whole document is eleven
    lines and the dependency would be larger than the feature. Values are
    escaped because `loc` embeds the site URL from configuration, and a stray
    `&` in a query string would otherwise produce a document no parser accepts.
    """
    def esc(value: str) -> str:
        return (
            str(value)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
        )

    urls = []
    for entry in sitemap_entries():
        parts = [f'    <loc>{esc(entry["loc"])}</loc>']
        if entry.get('lastmod'):
            parts.append(f'    <lastmod>{esc(entry["lastmod"])}</lastmod>')
        parts.append(f'    <changefreq>{esc(entry["changefreq"])}</changefreq>')
        parts.append(f'    <priority>{esc(entry["priority"])}</priority>')
        urls.append('  <url>\n' + '\n'.join(parts) + '\n  </url>')

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + '\n'.join(urls)
        + '\n</urlset>\n'
    )


def robots_txt() -> str:
    """robots.txt, naming each disallowed prefix and why.

    The reasons are comments, so they cost nothing to a crawler and save the next
    person who reads this file from assuming `/media/` is a mistake.
    """
    base = site_url()
    lines = ['User-agent: *', '']
    for prefix, reason in DISALLOWED_PREFIXES:
        lines.append(f'Disallow: {prefix}  # {reason}')
    lines.append('')
    lines.append('# The schema and Swagger UI under /api/ are served AllowAny. This')
    lines.append('# line is the only thing keeping them out of a search index.')
    lines.append('')
    if base:
        lines.append(f'Sitemap: {base}/sitemap.xml')
    return '\n'.join(lines) + '\n'