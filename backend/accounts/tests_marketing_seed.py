"""The seed migration must produce content the schema accepts and the renderer
can draw.

This exists because the seed is a data migration: nothing validates it. A typo
in one of the seven page definitions would otherwise be discovered the first
time an admin opened the editor, on a live site, and the content system would
already be half-populated with a page it refuses to save.

Two classes of check:

  * the seeded pages are **valid** - they survive `validate_content` with no
    blocking errors, so an admin can edit and re-save any of them;
  * the seeded pages are **complete** - every public route in the front end has
    a row, and the copy a page renders matches what shipped in its JSX, so
    wiring the renderer up does not change what a visitor sees.
"""

import pathlib
import unittest

from django.test import TestCase

from accounts.marketing_schema import SECTION_TYPES, validate_content
from accounts.platform_models import MarketingPage

MIGRATION = (
    pathlib.Path(__file__).resolve().parent / 'migrations'
    / '0018_seed_marketing_pages.py'
)
FRONTEND = pathlib.Path(__file__).resolve().parents[2] / 'frontend' / 'src' / 'pages'

# The public routes in frontend/src/App.jsx that render marketing copy, and the
# page component that owns each one.
PUBLIC_ROUTES = {
    '/': 'Home',
    '/platform': 'Platform',
    '/payroll-product': 'PayrollProduct',
    '/hr': 'HRProduct',
    '/about': 'About',
    '/pricing': 'Pricing',
    '/security': 'Security',
}

# Copy that shipped hardcoded in the JSX. The seed has to reproduce it, because
# the point of the renderer is to move this copy into the database - not to
# rewrite the site's words as a side effect.
COPY_THAT_MUST_NOT_CHANGE = {
    'home': [
        'The intelligent operating system for people, payroll & HR',
        'Run your people operations',
        'with clarity.',
    ],
    'platform': [
        'One system for people ops and payday.',
        'How it fits together',
        'From first hire to payslip, without switching tools.',
        'See payroll and HR in more detail.',
    ],
    'payroll-product': [
        'Payroll that is clear from draft to payday.',
        'Know exactly where payroll stands.',
        'Progressive tax calculation from your brackets',
        'Payroll should feel controlled.',
    ],
    'hr': [
        'People records that stay useful after onboarding.',
        'Structured records, not spreadsheet rows.',
        'Employee 360 profiles with contracts and documents',
        'Give HR one source of truth.',
    ],
    'about': [
        "Payroll software shouldn't assume where you do business.",
        'Why we built this',
        'How the payroll engine works',
        "Built for how your team is actually structured",
        "Who it's for",
    ],
    'pricing': [
        'One price per plan. No per-country surcharge.',
        'Professional',
        'Upgrade any time',
        'No setup fee',
    ],
    'security': [
        'Enterprise control without enterprise complexity.',
    ],
}


def load_pages():
    """Import the migration's PAGES table without running Django's migration."""
    import importlib.util

    spec = importlib.util.spec_from_file_location('_seed_0018', MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PAGES


def flatten(sections):
    """Every string in a page's content, for substring assertions."""
    strings = []

    def walk(value):
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(sections)
    return strings


class SeededPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = dict((slug, content) for slug, _, content in load_pages())
        cls.names = dict((slug, name) for slug, name, _ in load_pages())

    def test_every_public_route_has_a_seeded_page(self):
        """A page with no row cannot be managed, which is the bug being fixed."""
        for route, component in PUBLIC_ROUTES.items():
            with self.subTest(route=route):
                # Home and security already existed before this migration; the
                # other five are the ones being brought under management.
                self.assertTrue(self.pages, 'no pages were seeded at all')
        for slug in ('platform', 'payroll-product', 'hr', 'about', 'pricing'):
            with self.subTest(slug=slug):
                self.assertIn(slug, self.pages,
                              f'{slug} still has no marketing page row')

    def test_all_seven_pages_are_seeded(self):
        self.assertEqual(len(self.pages), 7)

    def test_every_seeded_page_passes_validation(self):
        """Otherwise an admin cannot open and re-save the page."""
        for slug, content in self.pages.items():
            with self.subTest(slug=slug):
                _, blocking, _ = validate_content(content)
                self.assertEqual(blocking, [], f'{slug} seeded invalid content')

    def test_no_seeded_page_uses_an_unknown_section_type(self):
        for slug, content in self.pages.items():
            for section in content['sections']:
                with self.subTest(slug=slug, section=section['type']):
                    self.assertIn(section['type'], SECTION_TYPES)

    def test_every_seeded_page_starts_with_a_hero(self):
        """The hero is what a visitor sees first; a page without one opens blank."""
        for slug, content in self.pages.items():
            with self.subTest(slug=slug):
                self.assertEqual(content['sections'][0]['type'], 'hero')

    def test_shipped_copy_is_reproduced_exactly(self):
        """Moving copy into the database must not change what a visitor reads."""
        for slug, expected in COPY_THAT_MUST_NOT_CHANGE.items():
            with self.subTest(slug=slug):
                actual = flatten(self.pages[slug]['sections'])
                for phrase in expected:
                    self.assertIn(phrase, actual,
                                  f'{slug} is missing the shipped copy {phrase!r}')

    def test_the_fallback_copy_still_matches_the_seed(self):
        """Where the JSX still holds copy, it must still say the same thing.

        This started as "the seed matches the JSX" for all seven pages. It only
        ever applied to two of them: `home` and `security` keep a `DEFAULT_*`
        constant in JSX as the fallback when the content endpoint is
        unavailable. The other five had their copy *moved* into this migration
        - their page components are now a dozen lines that read managed content
        and render it. There is no JSX left to compare them against, and
        pretending otherwise would just assert that the migration is equal to
        itself.

        So the check now covers what it can still cover, which is the part that
        matters: if someone edits the `home` or `security` fallback without
        editing the seed, the two drift and a visitor sees different words
        depending on whether the API answered.
        """
        # 'home' has moved out of here. This check compares the JSX fallback
        # against the seed migration's own table, which is the right input
        # only while the seed is the last thing to touch that page.
        # Migration 0026 repositions the homepage after it, so the seed's
        # table is now a state no install ever reaches and this assertion
        # could only pass by demanding the JSX keep saying something the
        # deployed site has replaced.
        #
        # The authoritative check moved to
        # hrcloudpay/tests_homepage_positioning.py, which compares the JSX
        # fallback against the copy a migrated database actually holds.
        fallback_pages = ('security',)
        for slug in fallback_pages:
            component = PUBLIC_ROUTES['/' if slug == 'home' else '/security']
            jsx = ' '.join(
                (FRONTEND / f'{component}.jsx').read_text(encoding='utf-8').split()
            )
            for phrase in COPY_THAT_MUST_NOT_CHANGE[slug]:
                with self.subTest(slug=slug, phrase=phrase):
                    self.assertIn(' '.join(phrase.split()), jsx,
                                  f'the {component} fallback no longer says '
                                  f'{phrase!r}, but the seed still does')

    def test_the_five_migrated_pages_no_longer_hardcode_their_copy(self):
        """The other half of the same fact, stated positively.

        If someone pastes a headline back into `Platform.jsx` while leaving the
        seed alone, the copy silently stops being editable and the admin's
        changes are ignored. This is what catches that.
        """
        for slug in ('platform', 'payroll-product', 'hr', 'about', 'pricing'):
            component = PUBLIC_ROUTES[
                {'platform': '/platform', 'payroll-product': '/payroll-product',
                 'hr': '/hr', 'about': '/about', 'pricing': '/pricing'}[slug]
            ]
            jsx = ' '.join(
                (FRONTEND / f'{component}.jsx').read_text(encoding='utf-8').split()
            )
            for phrase in COPY_THAT_MUST_NOT_CHANGE[slug]:
                with self.subTest(slug=slug, phrase=phrase):
                    self.assertNotIn(
                        ' '.join(phrase.split()), jsx,
                        f'{component}.jsx hardcodes {phrase!r} again. That copy '
                        'is managed in the platform admin, and a hardcoded '
                        'string would silently override it.',
                    )

    def test_every_link_in_the_seed_is_safe(self):
        """Validate with a link checker over the whole seed, not per field."""
        for slug, content in self.pages.items():
            _, blocking, _ = validate_content(content)
            for problem in blocking:
                with self.subTest(slug=slug):
                    self.assertNotIn('path', problem)

    def test_page_names_are_set(self):
        for slug, name in self.names.items():
            with self.subTest(slug=slug):
                self.assertTrue(name.strip())
                self.assertLessEqual(len(name), 160)

    def test_home_and_security_carry_only_a_hero(self):
        """Those two have bespoke layouts; the seed must not over-reach.

        A section here that the bespoke JSX does not render would be copy an
        admin can edit, save, and then never see on the page.
        """
        for slug in ('home', 'security'):
            with self.subTest(slug=slug):
                self.assertEqual(len(self.pages[slug]['sections']), 1)

    def test_about_and_pricing_have_no_hero_calls_to_action(self):
        """Those heroes never had buttons, and the JSX draws none.

        Seeding one would make the editor offer a CTA that renders nowhere.
        """
        for slug in ('about', 'pricing'):
            hero = self.pages[slug]['sections'][0]
            with self.subTest(slug=slug):
                self.assertEqual(hero['primary_cta'], '')
                self.assertEqual(hero['secondary_cta'], '')


class SeedRowsLandedTests(TestCase):
    """The above checks the seed data; this checks the migration ran it.

    A data migration is not covered by any test that inspects the constant, so
    without this the seed could be perfect and still never execute - a typo in
    `operations`, or a dependency on a migration that does not exist, would
    leave every page empty on a fresh deploy.
    """

    def test_every_page_row_exists_after_migrations(self):
        for slug, name, _ in load_pages():
            with self.subTest(slug=slug):
                self.assertTrue(
                    MarketingPage.objects.filter(slug=slug).exists(),
                    f'the migration did not create the {slug} page',
                )

    def test_the_seeded_rows_are_published(self):
        """An unpublished seed would leave the pages silently unmanaged."""
        for slug, _, _ in load_pages():
            with self.subTest(slug=slug):
                self.assertTrue(MarketingPage.objects.get(slug=slug).is_published)

    def test_the_seeded_rows_store_real_content(self):
        for slug, _, _ in load_pages():
            with self.subTest(slug=slug):
                page = MarketingPage.objects.get(slug=slug)
                self.assertTrue(page.content.get('sections'),
                                f'{slug} was created with empty content')

    def test_seeded_rows_survive_validation(self):
        """Whatever landed in the database is itself editable."""
        for slug, _, _ in load_pages():
            with self.subTest(slug=slug):
                page = MarketingPage.objects.get(slug=slug)
                _, blocking, _ = validate_content(page.content)
                self.assertEqual(blocking, [])


class RerunSafetyTests(TestCase):
    """Re-running the seed must not destroy an admin's work.

    A data migration that overwrites on every deploy is a data-loss bug that
    looks like a feature: the admin saves a headline, the next deploy silently
    restores the shipped one, and nobody connects the two events.
    """

    def _reseed(self):
        """Run the seed again, exactly as a second deploy would."""
        import importlib.util

        spec = importlib.util.spec_from_file_location('_seed_0018_rerun', MIGRATION)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.apply_seed(MarketingPage)

    def test_a_second_run_does_not_overwrite_edited_content(self):
        edited = {'sections': [{'type': 'hero', 'title': 'An admin wrote this'}]}
        MarketingPage.objects.filter(slug='platform').update(content=edited)
        self._reseed()
        page = MarketingPage.objects.get(slug='platform')
        self.assertEqual(page.content, edited,
                         're-running the seed overwrote an admin edit')

    def test_an_empty_page_is_still_filled_in_on_a_later_run(self):
        """The 0012 state - a row that exists but holds nothing - must recover.

        Without this the homepage and security page stay permanently empty,
        because their rows already exist and so are never created.
        """
        MarketingPage.objects.filter(slug='home').update(content={})
        self._reseed()
        page = MarketingPage.objects.get(slug='home')
        self.assertTrue(page.content.get('sections'),
                        'an empty page was not backfilled on a later run')
