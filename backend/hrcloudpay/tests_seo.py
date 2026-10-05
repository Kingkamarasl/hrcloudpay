"""Search metadata for the public pages, and the sitemap and robots files.

The failure these guard against is specific and quiet: the SPA shell carries one
hardcoded title and description, so every public URL is served that same pair.
Nothing breaks, every page returns 200, and seven URLs all claim to be the
homepage. No assertion in an ordinary suite would notice, which is why the
"distinct per route" cases below are stated as explicit requirements.
"""
import xml.etree.ElementTree as ET

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import AuditLog, User
from accounts.platform_models import MarketingPage
from hrcloudpay import seo

PUBLIC = override_settings(FRONTEND_URL='https://hrcloudpay.com')
SEO_LIST = reverse('platform-seo')


class RouteResolutionTests(TestCase):
    def test_every_public_route_resolves(self):
        for page in seo.PUBLIC_PAGES:
            self.assertEqual(seo.page_for_path(page.path), page,
                             f'{page.path} does not resolve to itself')

    def test_a_trailing_slash_and_query_string_resolve_to_the_same_page(self):
        """The SPA tolerates both, so the sitemap and the metadata must too.

        A sitemap listing /pricing/ for a page served at /pricing splits the
        canonical signal across two URLs, which is the same page telling a
        crawler two different things about where it lives.
        """
        canonical = seo.page_for_path('/pricing')
        for variant in ('/pricing/', '/pricing?utm_source=x', '/pricing#plans'):
            self.assertEqual(seo.page_for_path(variant), canonical, variant)

    def test_a_non_public_path_is_not_a_public_page(self):
        for path in ('/employees', '/login', '/api/anything', '/payroll'):
            self.assertIsNone(seo.page_for_path(path), path)

    def test_the_slug_mapping_matches_the_spa(self):
        """Each slug must be one the SPA actually asks for.

        useMarketingPage() is called with a literal slug per page, and the public
        endpoint 404s on anything else. If these drift apart the SEO console
        would offer to edit metadata for content the endpoint refuses to serve.
        """
        expected = {
            '/': 'home', '/platform': 'platform', '/payroll-product': 'payroll-product',
            '/hr': 'hr', '/about': 'about', '/pricing': 'pricing',
            '/security': 'security',
        }
        self.assertEqual({p.path: p.slug for p in seo.PUBLIC_PAGES}, expected)


@PUBLIC
class MetadataContentTests(TestCase):
    def test_no_two_public_pages_share_a_title_or_description(self):
        titles = [seo.meta_for(p)['title'] for p in seo.PUBLIC_PAGES]
        descriptions = [seo.meta_for(p)['description'] for p in seo.PUBLIC_PAGES]

        self.assertEqual(len(titles), len(set(titles)), 'duplicate titles')
        self.assertEqual(len(descriptions), len(set(descriptions)),
                         'duplicate descriptions')

    def test_a_managed_title_overrides_the_fallback(self):
        # Every public slug is seeded by migration 0018, so these tests
        # update the existing row rather than creating a second one.
        MarketingPage.objects.filter(slug='pricing').update(
            meta_title='Pricing - pay runs from $2 per employee',
        )

        meta = seo.meta_for(seo.PAGES_BY_SLUG['pricing'])
        self.assertEqual(meta['title'], 'Pricing - pay runs from $2 per employee')
        # A blank description must fall back rather than emit an empty tag.
        self.assertEqual(meta['description'], seo.PAGES_BY_SLUG['pricing'].description)

    def test_blank_fields_fall_back_rather_than_emit_empty_tags(self):
        """An empty meta description is worse than none: it states the page has
        nothing to say about itself."""
        MarketingPage.objects.filter(slug='about').update(
            meta_title='   ', meta_description='',
        )

        meta = seo.meta_for(seo.PAGES_BY_SLUG['about'])
        self.assertTrue(meta['title'].strip())
        self.assertTrue(meta['description'].strip())

    def test_noindex_sets_the_robots_meta(self):
        MarketingPage.objects.filter(slug='security').update(noindex=True)

        meta = seo.meta_for(seo.PAGES_BY_SLUG['security'])
        self.assertEqual(meta['robots'], 'noindex, nofollow')

    def test_the_canonical_uses_the_configured_origin_not_the_host_header(self):
        """A canonical built from Host is attacker-controlled, and would let
        anyone who can reach the site write canonical tags for their own domain."""
        with override_settings(FRONTEND_URL='https://hrcloudpay.com'):
            meta = seo.meta_for(seo.PAGES_BY_SLUG['pricing'])
        self.assertEqual(meta['canonical'], 'https://hrcloudpay.com/pricing')


class HtmlInjectionTests(TestCase):
    SHELL = (
        '<!doctype html><html lang="en"><head>'
        '<meta charset="UTF-8" />'
        '<title>HRCloudPay - People, Payroll &amp; AI HR Operations</title>'
        '<meta name="description" content="One description for everything." />'
        '<link rel="icon" href="/site-icon/favicon.png">'
        '</head><body><div id="root"></div></body></html>'
    )

    @PUBLIC
    def test_the_route_description_replaces_the_shell_description(self):
        html = seo.inject_into_html(
            self.SHELL, seo.meta_for(seo.PAGES_BY_SLUG['pricing']),
        )

        self.assertIn('Pricing - plans and what each one includes', html)
        self.assertNotIn('One description for everything.', html)
        # The original <title> must be gone, not merely preceded.
        self.assertNotIn('AI HR Operations', html)

    @PUBLIC
    def test_two_routes_do_not_leak_into_each_other(self):
        """The bug this whole module exists to prevent."""
        pricing = seo.inject_into_html(
            self.SHELL, seo.meta_for(seo.PAGES_BY_SLUG['pricing']))
        security = seo.inject_into_html(
            self.SHELL, seo.meta_for(seo.PAGES_BY_SLUG['security']))

        # Distinguishing text taken from each page's own description.
        self.assertIn('per-employee', pricing)
        self.assertNotIn('append-only audit chain', pricing)
        self.assertIn('append-only audit chain', security)
        self.assertNotIn('per-employee', security)

    def test_injection_is_idempotent(self):
        meta = seo.meta_for(seo.PAGES_BY_SLUG['pricing'])
        once = seo.inject_into_html(self.SHELL, meta)
        twice = seo.inject_into_html(once, meta)

        self.assertEqual(once, twice)
        self.assertEqual(twice.count('seo:start'), 1)

    @PUBLIC
    def test_the_canonical_and_og_tags_are_present(self):
        html = seo.inject_into_html(
            self.SHELL, seo.meta_for(seo.PAGES_BY_SLUG['pricing']))

        self.assertIn('<link rel="canonical" href="https://hrcloudpay.com/pricing" />', html)
        self.assertIn('<meta property="og:title"', html)
        self.assertIn('<meta name="robots" content="index, follow" />', html)

    def test_an_og_image_is_only_emitted_when_configured(self):
        page = seo.PAGES_BY_SLUG['pricing']
        without = seo.inject_into_html(self.SHELL, seo.meta_for(page))
        self.assertNotIn('og:image', without)

        MarketingPage.objects.filter(slug='pricing').update(
            og_image_url='https://hrcloudpay.com/media/share.png',
        )
        with_image = seo.inject_into_html(self.SHELL, seo.meta_for(page))
        self.assertIn('og:image', with_image)
        self.assertIn('https://hrcloudpay.com/media/share.png', with_image)

    def test_a_shell_without_a_head_is_returned_untouched(self):
        """Broken HTML for a crawler is a worse outcome than no metadata."""
        html = seo.inject_into_html('<div id="root"></div>', {'title': 'x' * 4,
            'description': 'd', 'canonical': '/', 'robots': 'index, follow',
            'og_image': ''})

        self.assertEqual(html, '<div id="root"></div>')

    def test_metadata_is_escaped(self):
        html = seo.render_tags({
            'title': 'Pay <script>alert(1)</script>',
            'description': 'Ampersand & "quotes"',
            'canonical': '/pricing', 'robots': 'index, follow', 'og_image': '',
        })

        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('&amp;', html)


class SitemapTests(TestCase):
    def test_the_sitemap_is_well_formed_xml_with_the_right_namespace(self):
        xml = seo.sitemap_xml()

        root = ET.fromstring(xml)
        self.assertEqual(
            root.tag, '{http://www.sitemaps.org/schemas/sitemap/0.9}urlset')

    @PUBLIC
    def test_every_public_page_is_listed_at_its_canonical_url(self):
        root = ET.fromstring(seo.sitemap_xml())
        locs = [
            node.text for node in
            root.findall('{http://www.sitemaps.org/schemas/sitemap/0.9}url/'
                         '{http://www.sitemaps.org/schemas/sitemap/0.9}loc')
        ]

        self.assertIn('https://hrcloudpay.com/pricing', locs)
        self.assertIn('https://hrcloudpay.com/', locs)
        self.assertEqual(len(locs), len(seo.PUBLIC_PAGES))

    @PUBLIC
    def test_a_noindex_page_is_removed_from_the_sitemap(self):
        """Listing a URL the same site asks not to index is a contradiction.

        Crawlers resolve contradictions conservatively, usually by distrusting the
        sitemap entry rather than the noindex, which means noindex quietly stops
        working.
        """
        MarketingPage.objects.filter(slug='pricing').update(noindex=True)

        self.assertNotIn('https://hrcloudpay.com/pricing', seo.sitemap_xml())
        self.assertIn('https://hrcloudpay.com/security', seo.sitemap_xml())

    @PUBLIC
    def test_lastmod_appears_only_where_content_actually_changed(self):
        """A lastmod that does not track a real edit teaches crawlers to ignore it."""
        ns = '{http://www.sitemaps.org/schemas/sitemap/0.9}'
        # No managed row at all means there is no content change to report,
        # so no lastmod rather than one tracking the seed.
        MarketingPage.objects.all().delete()
        root = ET.fromstring(seo.sitemap_xml())
        self.assertEqual(len(root.findall(f'.//{ns}lastmod')), 0)
        self.assertEqual(len(root.findall(f'.//{ns}url')),
                         len(seo.PUBLIC_PAGES))

        MarketingPage.objects.create(slug='pricing', name='Pricing')
        root = ET.fromstring(seo.sitemap_xml())
        self.assertEqual(len(root.findall(f'.//{ns}lastmod')), 1)


class RobotsTests(TestCase):
    @PUBLIC
    def test_the_api_surface_is_disallowed(self):
        """/api/schema/ and /api/docs/ are served AllowAny.

        Without this line a crawler is invited to index the entire API surface:
        endpoint names, parameters, and the auth scheme.
        """
        self.assertIn('Disallow: /api/', seo.robots_txt())

    @PUBLIC
    def test_the_sitemap_is_advertised(self):
        self.assertIn('Sitemap: https://hrcloudpay.com/sitemap.xml', seo.robots_txt())

    def test_media_and_admin_are_disallowed(self):
        body = seo.robots_txt()
        self.assertIn('Disallow: /media/', body)
        self.assertIn('Disallow: /admin/', body)


class ServedRoutesTests(TestCase):
    """The files have to beat the SPA catch-all to exist at all."""

    @PUBLIC
    def test_robots_txt_is_served_as_plain_text(self):
        response = self.client.get('/robots.txt')

        self.assertEqual(response.status_code, 200)
        self.assertIn('text/plain', response['Content-Type'])

    @PUBLIC
    def test_sitemap_xml_is_served_as_xml_not_the_spa_shell(self):
        response = self.client.get('/sitemap.xml')

        self.assertEqual(response.status_code, 200)
        self.assertIn('xml', response['Content-Type'])
        self.assertNotIn('<div id="root">', response.content.decode())

    def test_the_etag_differs_between_two_public_routes(self):
        """Otherwise a cache hands a 304 for one route to a request for another,
        and the client keeps the first route's description on the second page."""
        import django.test as dj_test

        with dj_test.override_settings(FRONTEND_URL='https://hrcloudpay.com'):
            first = self.client.get('/pricing')
            second = self.client.get('/security')

        self.assertNotEqual(first['ETag'], second['ETag'])

    def test_a_conditional_request_for_a_public_route_still_304s(self):
        first = self.client.get('/pricing')
        second = self.client.get('/pricing', HTTP_IF_NONE_MATCH=first['ETag'])

        self.assertEqual(second.status_code, 304)


class PlatformSeoApiTests(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser(
            username='root', email='root@example.com',
            password='Str0ngPass-2026!', company=None,
        )
        # Django's TestCase.client cannot force_authenticate; the SEO
        # endpoints are DRF views and need the token-authenticated client.
        self.client = APIClient()
        self.client.force_authenticate(self.root)

    @PUBLIC
    def test_the_list_shows_every_public_route_with_its_effective_tags(self):
        response = self.client.get(SEO_LIST)

        self.assertEqual(response.status_code, 200, response.data)
        slugs = {page['slug'] for page in response.data['pages']}
        self.assertEqual(slugs, set(seo.PAGES_BY_SLUG))

        pricing = next(p for p in response.data['pages'] if p['slug'] == 'pricing')
        # A blank form while the page is well described, with nothing saying
        # which text is in use, is the failure this field exists to prevent.
        self.assertEqual(pricing['effective']['title'],
                         seo.PAGES_BY_SLUG['pricing'].title)
        self.assertEqual(pricing['meta_title'], '')
        self.assertEqual(pricing['path'], '/pricing')

    @PUBLIC
    def test_saving_writes_the_row_and_audits_the_change(self):
        response = self.client.patch(
            reverse('platform-seo-detail', args=['pricing']),
            {'meta_title': 'Pricing - pay runs from $2 per employee',
             'meta_description': 'Plans and limits, stated plainly.',
             'og_image_url': 'https://hrcloudpay.com/media/share.png',
             'noindex': False},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        row = MarketingPage.objects.get(slug='pricing')
        self.assertEqual(row.meta_title, 'Pricing - pay runs from $2 per employee')
        self.assertEqual(row.updated_by, self.root)

        entry = AuditLog.objects.filter(action='platform_seo_update').first()
        self.assertIsNotNone(entry, 'saving search metadata wrote no audit row')
        self.assertEqual(entry.metadata['before']['meta_title'], '')

    @PUBLIC
    def test_saving_metadata_leaves_the_page_content_alone(self):
        """The SEO fields sit on the same row as the content.

        Saving a meta title through this screen must not touch the sections a
        visitor reads. The two screens edit one table, so the blast radius of a
        mistyped field is the whole page if this is wrong.
        """
        before = MarketingPage.objects.get(slug='about').content

        response = self.client.patch(
            reverse('platform-seo-detail', args=['about']),
            {'meta_title': 'About HRCloudPay'}, format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(MarketingPage.objects.get(slug='about').content, before)

    @PUBLIC
    def test_a_relative_og_image_is_refused(self):
        """A relative path resolves against nothing when a crawler fetches it
        from a different origin, so the preview silently loses its image - which
        looks identical to the field being ignored."""
        response = self.client.patch(
            reverse('platform-seo-detail', args=['pricing']),
            {'og_image_url': '/media/share.png'}, format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('og_image_url', response.data['errors'])

    def test_an_unknown_slug_is_refused(self):
        response = self.client.patch(
            reverse('platform-seo-detail', args=['nope']), {}, format='json')

        self.assertEqual(response.status_code, 404)

    def test_a_tenant_admin_cannot_change_search_metadata(self):
        from accounts.models import Company

        company = Company.objects.create(
            name='Acme', email='acme@example.com', is_active=True, plan='starter')
        worker = User.objects.create_user(
            username='owner', email='owner@example.com',
            password='Str0ngPass-2026!', company=company, role='owner',
        )
        self.client.force_authenticate(worker)

        self.assertEqual(self.client.get(SEO_LIST).status_code, 403)
        self.assertEqual(
            self.client.patch(reverse('platform-seo-detail', args=['pricing']),
                              {}, format='json').status_code,
            403,
        )