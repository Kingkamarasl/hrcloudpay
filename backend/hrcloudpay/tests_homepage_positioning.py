"""The homepage hero an actual visitor sees, not the JSX fallback.

Home.jsx's DEFAULT_HERO is used only when the content endpoint is unavailable.
The copy a live site serves lives in the `home` MarketingPage row, so a copy
change made only in JSX reaches nobody and fails silently. These pin the data
migration that moves the stored copy, because that migration is the only part
that touches a deployed site.

Three of these assertions exist because they were wrong on the first attempt:
the seeded hero turned out to be DEFAULT_HERO's own copy rather than the seed
migration's, the seeded homepage turned out to have exactly one section rather
than several, and the revert turned out to restore a sentence this migration
never held.
"""
import importlib
import pathlib
import re

from django.test import SimpleTestCase, TestCase

MIGRATION = 'accounts.migrations.0026_homepage_positioning'
FRONTEND_HOME = (
    # parents[2] is the repository root. parents[1] is backend/, which has no
    # frontend/ directory - the first version of this test failed in setUpClass
    # for that reason and for no other.
    pathlib.Path(__file__).resolve().parents[2]
    / 'frontend' / 'src' / 'pages' / 'Home.jsx'
)

EXPECTED = {
    'eyebrow': 'People \u00b7 Payroll \u00b7 Progress',
    'title': 'Smarter HR & Payroll for a',
    'title_accent': 'Stronger Africa.',
    'primary_cta': 'Build Your Stronger Workforce',
}

# Read back from a seeded database, not assumed.
PREVIOUS_TITLE = 'Run your people operations'


def hero_of(page):
    for section in (page.content or {}).get('sections', []):
        if isinstance(section, dict) and section.get('type') == 'hero':
            return section
    return None


class HomepagePositioningTests(TestCase):
    def setUp(self):
        from accounts.platform_models import MarketingPage

        self.page = MarketingPage.objects.filter(slug='home').first()
        # Assert, not skip: a missing seeded homepage means there is nothing to
        # prove, and passing quietly would be worse than failing.
        self.assertIsNotNone(self.page, 'no seeded homepage to test against')

    def test_the_new_positioning_is_what_a_visitor_gets(self):
        hero = hero_of(self.page)

        for field, value in EXPECTED.items():
            self.assertEqual(hero[field], value, field)
        self.assertIn('African businesses', hero['subtitle'])

    def test_the_migration_target_is_reachable(self):
        """The migration declines to overwrite copy it does not recognise, so if
        PREVIOUS_HERO drifts from what a seeded database actually holds the
        change silently stops applying. This is the canary."""
        module = importlib.import_module(MIGRATION)

        self.assertEqual(module.PREVIOUS_HERO['title'], PREVIOUS_TITLE)
        self.assertEqual(module.NEW_HERO['title'], EXPECTED['title'])

    def test_it_targets_only_the_homepage_hero(self):
        """The seeded homepage has exactly one section. If that ever stops being
        true the migration must still touch nothing but the hero."""
        module = importlib.import_module(MIGRATION)
        from accounts.platform_models import MarketingPage

        sections = self.page.content.get('sections', [])
        self.assertEqual([s.get('type') for s in sections], ['hero'])

        # Applying it again is a no-op, and leaves another page untouched.
        other = MarketingPage.objects.exclude(slug='home').first()
        before = other.content if other is not None else None

        module.apply_positioning(_apps(), None)
        module.apply_positioning(_apps(), None)

        self.assertEqual(MarketingPage.objects.filter(slug='home').count(), 1)
        if other is not None:
            other.refresh_from_db()
            self.assertEqual(other.content, before)

    def test_it_is_reversible(self):
        """A marketing migration with no reverse is a one-way door: an operator
        who dislikes the new copy could only get back by hand-editing JSON."""
        module = importlib.import_module(MIGRATION)
        from accounts.platform_models import MarketingPage

        module.revert_positioning(_apps(), None)
        reverted = MarketingPage.objects.get(slug='home')

        self.assertEqual(hero_of(reverted)['title'], PREVIOUS_TITLE)
        # A revert that restores the title but leaves the new subtitle behind
        # leaves the page saying two contradictory things at once.
        self.assertIn('employee 360', hero_of(reverted)['subtitle'])
        self.assertNotIn('African businesses', hero_of(reverted)['subtitle'])

        module.apply_positioning(_apps(), None)
        restored = MarketingPage.objects.get(slug='home')
        self.assertEqual(hero_of(restored)['title'], EXPECTED['title'])


def _apps():
    from django.apps import apps as global_apps

    return global_apps


class FallbackMatchesStoredCopyTests(SimpleTestCase):
    """File-level checks, so no database.

    As a TestCase each of these opened a transaction and then tore it down
    for a class that never touches a table, and the teardown reported as an
    error of its own - which is how two genuinely passing tests looked
    broken.
    """
    """The fallback is what a visitor sees when the content endpoint is down.

    If it drifts from the stored copy, the site changes its own positioning
    depending on whether a background request happened to succeed.
    """

    @classmethod
    def setUpClass(cls):
        # errors='replace' because Home.jsx still contains corrupted bytes
        # elsewhere in the file - outside the regions this change touches. Reading
        # it strictly raises, which surfaced as a setUpClass error and hid the
        # assertions entirely.
        cls.source = FRONTEND_HOME.read_text(encoding='utf-8', errors='replace')

    def test_the_jsx_fallback_carries_the_new_positioning(self):
        block = re.search(r'const DEFAULT_HERO = \{(.*?)\n\};', self.source, re.DOTALL)
        self.assertIsNotNone(block, 'DEFAULT_HERO not found in Home.jsx')

        for field, value in EXPECTED.items():
            self.assertIn(value, block.group(1), f'fallback missing {field}')

    def test_the_pillars_name_the_six_capabilities(self):
        """Attendance and leave were both shipped apps and both were absent from
        the pillar list, so the page understated what the product does."""
        block = re.search(r'const PILLARS = \[(.*?)\n\];', self.source, re.DOTALL)
        self.assertIsNotNone(block, 'PILLARS not found in Home.jsx')

        for label in ('Employee Management', 'Automated Payroll',
                      'Attendance & Time Tracking', 'Leave Management',
                      'Compliance & Security', 'AI-Powered HR Assistant'):
            self.assertIn(label, block.group(1), label)

    def test_the_hero_regions_have_no_corrupted_characters(self):
        """The hero trust strip shipped with corrupted checkmark glyphs, so it
        rendered as four replacement characters in the hero.

        Scoped to the regions this change touches rather than the whole file.
        Home.jsx has pre-existing encoding damage elsewhere, and asserting the
        entire file clean would fail for reasons unrelated to the hero while
        telling us nothing about it.
        """
        hero = re.search(r'const DEFAULT_HERO = \{.*?\n\};', self.source, re.DOTALL)
        trust = re.search(
            r'<div className="hc-hero-trust">.*?</div>', self.source, re.DOTALL)
        self.assertIsNotNone(hero, 'DEFAULT_HERO not found')
        self.assertIsNotNone(trust, 'trust strip not found')

        self.assertNotIn('\ufffd', hero.group(0))
        self.assertNotIn('\ufffd', trust.group(0))
        self.assertIn('\u2713 AI-assisted HR', trust.group(0))
        self.assertIn('Employee 360\u00b0', trust.group(0))


class HomepageSeoTests(SimpleTestCase):
    def test_the_homepage_title_matches_the_positioning(self):
        from hrcloudpay import seo

        page = seo.PAGES_BY_SLUG['home']
        self.assertIn('African', page.title)
        self.assertIn('Payroll', page.title)

    def test_the_description_names_what_the_product_does(self):
        from hrcloudpay import seo

        page = seo.PAGES_BY_SLUG['home']
        for term in ('payroll', 'compliance'):
            self.assertIn(term, page.description.lower())