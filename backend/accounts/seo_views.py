"""Platform-admin endpoints for the public pages' search metadata.

Split from the marketing-page editor on purpose. That screen edits a page's
*content* - the sections a visitor reads. This one edits what a crawler and a
link preview see, which is a different question with a different audience, and
bundling it into the content form would bury four fields under a dozen
content ones that get edited far more often.

The list is built from ``hrcloudpay.seo.PUBLIC_PAGES``, not from
``MarketingPage.objects.all()``, because the set of indexable URLs is a property
of the routes the SPA actually serves. A MarketingPage row can exist for a slug
that no route uses, and listing it as a page you can set SEO for would be
offering to optimise something no visitor can reach.
"""
from django.http import Http404
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.platform import audit
from accounts.platform_models import MarketingPage
from hrcloudpay import seo

# Google's guidance, used as the warning threshold rather than enforced. A title
# over 60 characters is truncated in the result line, which is not fatal, so
# blocking the save would be paternalistic - but silently truncating is also not
# acceptable, so the console says so.
TITLE_TARGET = 60
DESCRIPTION_TARGET = 160


class PlatformSeoView(APIView):
    """Every public page with both its managed values and what will be served."""

    permission_classes = [IsAdminUser]
    schema = None

    def get(self, request):
        return Response({
            'site_url': seo.site_url(),
            'sitemap_url': f'{seo.site_url()}/sitemap.xml',
            'robots_url': f'{seo.site_url()}/robots.txt',
            'pages': [self.serialize(slug) for slug in seo.PAGES_BY_SLUG],
        })

    @staticmethod
    def serialize(slug):
        page = seo.PAGES_BY_SLUG[slug]
        row = MarketingPage.objects.filter(slug=slug).first()
        # The effective values are what a crawler gets today, fallbacks included.
        # Sending only the raw columns would leave an administrator staring at a
        # blank form while the page is perfectly well described, with nothing
        # telling them which text is actually in use.
        effective = seo.meta_for(page)
        return {
            'slug': slug,
            'path': page.path,
            'name': (row.name if row is not None else page.slug.replace('-', ' ').title()),
            'exists': row is not None,
            'is_published': bool(getattr(row, 'is_published', True)),
            'meta_title': (getattr(row, 'meta_title', '') or ''),
            'meta_description': (getattr(row, 'meta_description', '') or ''),
            'og_image_url': (getattr(row, 'og_image_url', '') or ''),
            'noindex': bool(getattr(row, 'noindex', False)),
            'effective': {
                'title': effective['title'],
                'description': effective['description'],
                'robots': effective['robots'],
                'canonical': effective['canonical'],
            },
            'fallbacks': {
                'title': page.title,
                'description': page.description,
            },
            'guidance': {
                'title_target': TITLE_TARGET,
                'description_target': DESCRIPTION_TARGET,
                'title_over': (
                    len((getattr(row, 'meta_title', '') or '').strip())
                    > TITLE_TARGET
                ),
                'description_over': (
                    len((getattr(row, 'meta_description', '') or '').strip())
                    > DESCRIPTION_TARGET
                ),
            },
        }


class PlatformSeoDetailView(APIView):
    """Write one page's search metadata."""

    permission_classes = [IsAdminUser]
    schema = None

    FIELDS = ('meta_title', 'meta_description', 'og_image_url', 'noindex')

    def patch(self, request, slug):
        # Not get_object_or_404: PAGES_BY_SLUG is a dict, and that helper expects
        # a queryset. Passed a dict it raised KeyError, so a mistyped slug was a
        # 500 with a traceback in the console rather than the 404 the caller
        # should see - and a slug is user-supplied.
        if slug not in seo.PAGES_BY_SLUG:
            raise Http404(f'No public page uses the slug "{slug}".')

        errors = {}

        title = str(request.data.get('meta_title', '') or '').strip()
        if len(title) > 120:
            errors['meta_title'] = 'Keep this under 120 characters.'
        description = str(request.data.get('meta_description', '') or '').strip()
        if len(description) > 320:
            errors['meta_description'] = 'Keep this under 320 characters.'
        image = str(request.data.get('og_image_url', '') or '').strip()
        if image and not (image.startswith('http://') or image.startswith('https://')):
            # An empty value means "share without an image", which is valid. A
            # relative path is not: a crawler fetching it from a different origin
            # resolves it against nothing and the preview silently loses its image,
            # which is indistinguishable from the field being ignored.
            errors['og_image_url'] = (
                'Use an absolute URL starting with https://, or leave it blank.'
            )

        if errors:
            return Response({
                'detail': 'Please correct the highlighted fields.',
                'errors': errors,
            }, status=400)

        page, _ = MarketingPage.objects.get_or_create(
            slug=slug, defaults={'name': slug.replace('-', ' ').title()},
        )
        before = {
            field: getattr(page, field) for field in self.FIELDS
        }
        page.meta_title = title
        page.meta_description = description
        page.og_image_url = image
        page.noindex = bool(request.data.get('noindex', False))
        page.updated_by = request.user
        page.save(update_fields=list(self.FIELDS) + ['updated_by', 'updated_at'])

        after = {field: getattr(page, field) for field in self.FIELDS}
        audit(
            request.user, 'platform_seo_update',
            f'Updated search metadata for /{slug.lstrip("/")}.',
            None, 'marketing_page', page.id, {'before': before, 'after': after},
        )

        return Response(PlatformSeoView.serialize(slug))