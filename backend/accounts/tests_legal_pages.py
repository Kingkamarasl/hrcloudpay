"""Terms, privacy and refund pages.

Marketplace and payment-processor verification follows the links rather than
checking that routes exist, so a page that renders but is unlinked fails review
exactly as one that does not exist. Both halves are guarded here.

Three failures of this shape have already shipped in this project - the SEO tab,
the AI approval gates, and the platform admin plan editor - each fully built,
each unreachable. That is the reason this module exists rather than a one-off
check on three new pages.
"""

import pathlib
import re

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.platform_models import MarketingPage
from hrcloudpay import seo

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / 'frontend' / 'src'
APP = (FRONTEND / 'App.jsx').read_text(encoding='utf-8')
LAYOUT = (FRONTEND / 'components' / 'MarketingLayout.tsx').read_text(encoding='utf-8')

LEGAL = [
    ('/terms', 'terms', 'Terms of Service'),
    ('/privacy', 'privacy', 'Privacy Policy'),
    ('/refund-policy', 'refund-policy', 'Refund Policy'),
]


class LegalRoutesTests(SimpleTestCase):
    def test_every_legal_path_has_a_route(self):
        for path, slug, _name in LEGAL:
            self.assertIn('path="%s"' % path, APP,
                          'no route for %s' % path)

    def test_each_route_passes_its_own_slug(self):
        """One component serves all three, so the slug has to come from the route.

        `useParams()` returns nothing here - none of these paths declares a
        :slug segment - so a component reading it would fetch an empty slug and
        render a blank page at all three addresses.
        """
        for path, slug, _name in LEGAL:
            route = re.search(r'path="%s"[^>]*' % re.escape(path), APP)
            self.assertIn('slug="%s"' % slug, route.group(0))

    def test_no_catch_all_swallows_unknown_paths(self):
        """`/legal/:slug` would render a legal page instead of a 404.

        A reviewer following a mistyped link would get a page of legal copy
        instead of a not-found, which reads as a broken site.
        """
        self.assertNotRegex(APP, r'path="/:slug"')

    def test_the_footer_links_to_all_three(self):
        """The part verification actually checks."""
        for path, _slug, label in LEGAL:
            self.assertIn('to="%s"' % path, LAYOUT,
                          'the footer does not link to %s' % path)
            # Case-insensitively: the link text is styled as a sentence
            # ("Terms of service"), the page title is not ("Terms of Service").
            # Both are correct; what matters is that each link carries words a
            # reviewer will recognise.
            self.assertIn(label.lower(), LAYOUT.lower())


class LegalSeoTests(SimpleTestCase):
    def test_each_legal_page_is_registered_for_seo(self):
        for path, slug, _name in LEGAL:
            self.assertIn(path, seo.PAGES_BY_PATH, '%s has no meta entry' % path)
            self.assertEqual(seo.PAGES_BY_PATH[path].slug, slug)

    def test_each_legal_page_gets_its_own_title_and_description(self):
        """Every public route is a SPA route, so without a registered entry they
        would all ship the homepage's hardcoded title and description."""
        titles = [seo.PAGES_BY_PATH[p].title for p, _s, _n in LEGAL]
        self.assertEqual(len(set(titles)), 3, 'two legal pages share a title')
        for path, _slug, _name in LEGAL:
            page = seo.PAGES_BY_PATH[path]
            self.assertTrue(page.description.strip())
            self.assertLessEqual(len(page.description), 320)
            self.assertLessEqual(len(page.title), 120)

    def test_legal_pages_are_in_the_sitemap(self):
        sitemap = seo.sitemap_xml()
        for path, _slug, _name in LEGAL:
            self.assertIn(path, sitemap,
                          '%s is missing from sitemap.xml' % path)


class LegalContentTests(TestCase):
    """The pages have to carry copy, not render an empty shell."""

    def setUp(self):
        # Deliberately not get_or_create. The rows come from migration 0027, and
        # creating an empty one here would let this class pass a build where the
        # migration never ran - which is the exact failure it exists to catch.
        for _path, slug, name in LEGAL:
            self.assertTrue(
                MarketingPage.objects.filter(slug=slug).exists(),
                'no MarketingPage row for %r - migration 0027 has not run' % slug)

    def test_legal_pages_are_not_noindexed(self):
        """`noindex` lives on the MarketingPage row, not on PublicPage."""
        for _path, slug, _name in LEGAL:
            page = MarketingPage.objects.get(slug=slug)
            self.assertFalse(page.noindex,
                             '%s is noindexed, so a reviewer cannot find it' % slug)

    def test_each_legal_page_holds_substantive_copy(self):
        """A reviewer reads these. An empty page is a worse failure than a
        missing one, because it looks like a broken link."""
        for _path, slug, _name in LEGAL:
            page = MarketingPage.objects.get(slug=slug)
            blocks = [
                b for section in page.content.get('sections', [])
                if section.get('type') == 'prose_blocks'
                for b in section.get('blocks', [])
            ]
            self.assertGreaterEqual(
                len(blocks), 6,
                '%s has %d sections of copy; a legal page needs more' % (slug, len(blocks)))
            for block in blocks:
                self.assertTrue(block.get('title', '').strip())
                self.assertGreater(
                    len(block.get('body', '')), 60,
                    'section %r in %s is too thin to be meaningful'
                    % (block.get('title'), slug))

    def test_each_legal_page_is_published(self):
        for _path, slug, _name in LEGAL:
            self.assertTrue(
                MarketingPage.objects.get(slug=slug).is_published,
                '%s is unpublished, so the route renders nothing' % slug)


class LegalAccuracyTests(TestCase):
    """Two statements in this copy must not be softened.

    Both describe how the product actually works, and a privacy policy that
    misstates either would mislead the exact buyers the product is for - the
    people running payroll on their own employees' data.
    """

    def _body(self, slug):
        page = MarketingPage.objects.get(slug=slug)
        return ' '.join(
            (b.get('body') or '')
            for section in page.content.get('sections', [])
            if section.get('type') == 'prose_blocks'
            for b in section.get('blocks', [])
        )

    def test_the_privacy_policy_does_not_claim_the_vendor_hosts_employee_data(self):
        body = self._body('privacy').lower()
        self.assertIn('processor', body)
        self.assertIn('controller', body)
        for claim in ['we host your data', 'we store your payroll',
                      'we never share your data']:
            self.assertNotIn(claim, body,
                             'unsupported privacy claim: %r' % claim)

    def test_the_privacy_policy_discloses_the_ai_provider(self):
        """The AI assistant sends submitted text to a third-party model
        provider. Omitting that would make the policy false."""
        body = self._body('privacy').lower()
        self.assertIn('model provider', body)
        self.assertIn('ai assistant', body)

    def test_the_terms_state_payroll_output_is_not_advice(self):
        """The buyers are running real payroll. This is the sentence that stops
        someone treating calculated figures as legally correct."""
        body = self._body('terms').lower()
        self.assertIn('not legal, tax or accounting advice', body)

    def test_the_refund_policy_states_when_refunds_apply(self):
        body = self._body('refund-policy').lower()
        self.assertIn('refund', body)
        self.assertIn('duplicate', body)

    def test_contact_address_is_consistent_across_all_three(self):
        addresses = set()
        for _path, slug, _name in LEGAL:
            addresses.update(re.findall(r'[\w.+-]+@[\w.-]+\.\w+',
                                        self._body(slug)))
        self.assertLessEqual(len(addresses), 1,
                             'legal pages name %d different addresses' % len(addresses))