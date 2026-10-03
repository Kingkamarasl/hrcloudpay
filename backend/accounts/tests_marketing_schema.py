"""Managed marketing content must be safe to render on a public page.

Two failure modes matter here, and neither is visible by reading the editor:

  * a **stored XSS**. Page content is authored by an admin and rendered into
    `href` attributes on pages every visitor loads. A `javascript:` or `data:`
    URL in a button is a script-execution hole on the platform's own origin, so
    the link scheme is a security boundary and is tested as one.

  * a **crashed landing page**. The public renderer switches on section `type`.
    An unknown type that reached storage would either throw on every visitor's
    page load or render as a silent empty gap that the editor cannot explain.

The cross-check test at the end is the one that catches the failure this file
cannot see: a section type the backend accepts but the frontend cannot draw.
That is the drift that makes "add a page" quietly produce a broken page.
"""

import pathlib
import re
import unittest

from accounts.marketing_schema import (
    MAX_SECTIONS,
    SECTION_TYPES,
    blank_content,
    first_section,
    is_valid_slug,
    validate_content,
)

FRONTEND = (
    # parents[3]: this file is backend/accounts/<file>.py, so [2] is the
    # project root and the frontend sits beside it.
    pathlib.Path(__file__).resolve().parents[2] / 'frontend' / 'src'
)


def one(type_name, **fields):
    return {'sections': [{'type': type_name, **fields}]}


class ContentShapeTests(unittest.TestCase):
    def test_an_empty_object_is_a_valid_empty_page(self):
        """Both seeded pages started as `{}`; that must not read as an error."""
        content, blocking, advisory = validate_content({})
        self.assertEqual(content, {'sections': []})
        self.assertEqual(blocking, [])
        self.assertEqual(advisory, [])

    def test_missing_and_null_content_are_treated_as_empty(self):
        for raw in (None, {}):
            with self.subTest(raw=raw):
                _, blocking, _ = validate_content(raw)
                self.assertEqual(blocking, [])

    def test_a_new_page_starts_with_a_hero(self):
        """Every landing page needs a headline, so the empty page starts with one."""
        self.assertEqual(blank_content(), {'sections': [{'type': 'hero'}]})
        _, blocking, _ = validate_content(blank_content())
        self.assertEqual(blocking, [])

    def test_content_must_be_an_object(self):
        for raw in ([], 'text', 7):
            with self.subTest(raw=raw):
                _, blocking, _ = validate_content(raw)
                self.assertEqual(blocking, ['Content must be a JSON object.'])

    def test_sections_must_be_a_list(self):
        _, blocking, _ = validate_content({'sections': {'type': 'hero'}})
        self.assertEqual(blocking, ['"sections" must be a list.'])

    def test_first_section_finds_the_hero(self):
        content = {'sections': [{'type': 'cta'}, {'type': 'hero', 'title': 'Hi'}]}
        self.assertEqual(first_section(content, 'hero'), {'type': 'hero', 'title': 'Hi'})

    def test_first_section_returns_empty_when_absent(self):
        self.assertEqual(first_section({'sections': [{'type': 'cta'}]}, 'hero'), {})
        self.assertEqual(first_section({}, 'hero'), {})
        self.assertEqual(first_section(None, 'hero'), {})


class UnknownSectionTests(unittest.TestCase):
    def test_an_unknown_section_type_is_refused_and_dropped(self):
        """Storing it would break the public renderer's switch."""
        content, blocking, _ = validate_content(
            {'sections': [{'type': 'hero', 'title': 'Kept'},
                          {'type': 'marquee', 'text': '???'}]}
        )
        self.assertEqual([s['type'] for s in content['sections']], ['hero'])
        self.assertTrue(blocking, 'an unknown section type must be reported')

    def test_a_section_without_a_type_is_refused(self):
        _, blocking, _ = validate_content({'sections': [{'title': 'No type'}]})
        self.assertTrue(blocking)

    def test_a_non_object_section_is_refused(self):
        content, blocking, _ = validate_content({'sections': ['just a string']})
        self.assertEqual(content['sections'], [])
        self.assertTrue(blocking)

    def test_every_declared_section_type_validates(self):
        """A type declared here but never exercised would be untested surface."""
        for name in SECTION_TYPES:
            with self.subTest(section=name):
                _, blocking, _ = validate_content(one(name))
                self.assertEqual(blocking, [], f'{name} rejected a blank section')


class LinkSafetyTests(unittest.TestCase):
    """`href` values are rendered on public pages. Scheme check is a boundary."""

    DANGEROUS = [
        'javascript:alert(1)',
        'JavaScript:alert(1)',
        '  javascript:alert(1)  ',
        'data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==',
        'vbscript:msgbox(1)',
        'http://example.com',
        '//evil.example.com',
        'java\tscript:alert(1)',
        'java\nscript:alert(1)',
        'JAVASCRIPT:alert(1)',
    ]

    def test_dangerous_links_are_refused_and_cleared(self):
        for href in self.DANGEROUS:
            with self.subTest(href=href):
                content, blocking, _ = validate_content(
                    one('cta', actions=[{'label': 'Go', 'href': href}])
                )
                self.assertTrue(blocking, f'{href!r} was accepted')
                stored = content['sections'][0]['actions'][0]['href']
                self.assertEqual(stored, '', f'{href!r} survived as {stored!r}')

    def test_safe_links_are_preserved(self):
        for href in ('/pricing', '/register?plan=business', '#faq',
                     'https://example.com/docs', 'HTTPS://Example.com'):
            with self.subTest(href=href):
                content, blocking, _ = validate_content(
                    one('cta', actions=[{'label': 'Go', 'href': href}])
                )
                self.assertEqual(blocking, [])
                self.assertEqual(content['sections'][0]['actions'][0]['href'], href)

    def test_a_dangerous_link_anywhere_in_a_repeated_list_is_caught(self):
        """Feature rows have no `href` field, so the value is refused as unknown.

        It is caught by the unknown-field rule rather than the scheme check, and
        the distinction matters: the important property is that nothing
        unrenderable reaches storage, which `assertNotIn` below pins down.
        """
        content, blocking, _ = validate_content(
            one('feature_rows', items=[{'title': 'Fine', 'body': 'ok'},
                                       {'title': 'Bad', 'body': 'x',
                                        'href': 'javascript:alert(1)'}])
        )
        self.assertTrue(blocking, 'an undeclared field must be reported')
        # Unknown keys are dropped rather than stored, so the injected value
        # cannot reach the renderer even if validation were bypassed.
        self.assertNotIn('href', content['sections'][0]['items'][1])

    def test_an_unknown_field_is_reported_not_silently_dropped(self):
        """A typo must not look like a successful save."""
        _, blocking, _ = validate_content(one('hero', titel='typo'))
        self.assertEqual(len(blocking), 1)
        self.assertIn('titel', blocking[0])

    def test_hero_links_are_scheme_checked_too(self):
        for field in ('primary_href', 'secondary_href'):
            with self.subTest(field=field):
                content, blocking, _ = validate_content(
                    one('hero', primary_cta='Go', **{field: 'javascript:alert(1)'})
                )
                self.assertTrue(blocking)
                self.assertEqual(content['sections'][0][field], '')

    def test_an_over_long_link_is_refused(self):
        _, blocking, _ = validate_content(
            one('cta', actions=[{'label': 'Go', 'href': '/' + 'a' * 400}])
        )
        self.assertTrue(blocking)


class TextTests(unittest.TestCase):
    def test_over_long_text_is_truncated_and_reported_as_advisory(self):
        """A long headline is a typo; losing the whole edit would be worse."""
        content, blocking, advisory = validate_content(
            one('hero', title='T' * 400)
        )
        self.assertEqual(blocking, [], 'a truncation must not block the save')
        self.assertTrue(advisory)
        self.assertEqual(len(content['sections'][0]['title']), 160)

    def test_text_is_trimmed(self):
        content, _, _ = validate_content(one('hero', title='  Hello  '))
        self.assertEqual(content['sections'][0]['title'], 'Hello')

    def test_non_text_values_are_refused(self):
        _, blocking, _ = validate_content(one('hero', title={'nested': 'dict'}))
        self.assertTrue(blocking)

    def test_missing_fields_become_empty_strings_not_nulls(self):
        """The renderer spreads these over defaults; None would render 'null'."""
        content, blocking, _ = validate_content(one('hero'))
        self.assertEqual(blocking, [])
        for value in content['sections'][0].values():
            self.assertNotIsInstance(value, type(None))

    def test_unknown_keys_are_dropped(self):
        """Storing them would let content carry fields nothing renders."""
        content, _, _ = validate_content(one('hero', title='Hi', evil='payload'))
        self.assertNotIn('evil', content['sections'][0])

    def test_repeated_item_counts_are_capped(self):
        content, blocking, _ = validate_content(
            one('feature_rows', items=[{'title': f'T{i}'} for i in range(500)])
        )
        self.assertTrue(blocking)
        self.assertEqual(len(content['sections'][0]['items']), 60)

    def test_too_many_sections_is_refused(self):
        content, blocking, _ = validate_content(
            {'sections': [{'type': 'hero'}] * (MAX_SECTIONS + 5)}
        )
        self.assertTrue(blocking)
        self.assertEqual(len(content['sections']), MAX_SECTIONS)

    def test_pricing_plans_keep_their_features_and_highlight(self):
        content, blocking, _ = validate_content(
            one('pricing',
                plans=[{'plan': 'starter', 'name': 'Starter', 'tagline': 'Small teams',
                        'features': ['Payroll', 'Payslip PDFs'], 'highlight': True},
                       {'plan': 'enterprise', 'name': 'Enterprise', 'tagline': 'Big teams',
                        'features': ['Dedicated support'], 'highlight': False}])
        )
        self.assertEqual(blocking, [])
        plans = content['sections'][0]['plans']
        self.assertEqual(plans[0]['features'], ['Payroll', 'Payslip PDFs'])
        self.assertIs(plans[0]['highlight'], True)
        self.assertIs(plans[1]['highlight'], False)

    def test_the_plan_key_survives_validation(self):
        """The card must still know which plan it describes after a save.

        The card is bound to a plan by `plan`, and `hrcloudpay.pricing_sync` looks
        the price up by that key when the page is served. If validation stripped
        it, the whole grid would fall back to author-written prices - exactly the
        duplicate source of truth this key exists to remove - and nothing else
        would fail, because the copy would still look right.
        """
        content, blocking, _ = validate_content(
            one('pricing', plans=[{'plan': 'scale', 'name': 'Scale',
                                   'tagline': 'Bigger teams',
                                   'features': ['Everything in Professional'],
                                   'highlight': False}])
        )
        self.assertEqual(blocking, [])
        self.assertEqual(content['sections'][0]['plans'][0]['plan'], 'scale')

    def test_a_stored_price_is_refused_rather_than_silently_accepted(self):
        """Reject, not quietly drop.

        `price` left the editable fields because it is derived from `PLAN_PRICES`.
        A save that still carries one is telling the admin their number was
        ignored; a save that drops it silently leaves them editing a field that
        does not exist and wondering why the page never changes.
        """
        # Third element is `advisory` (recoverable notes), not errors: an unknown
        # key is blocking because a save must be refused rather than silently
        # dropping a field the admin thought they saved.
        _, blocking, _ = validate_content(
            one('pricing', plans=[{'plan': 'starter', 'name': 'Starter',
                                   'price': '$15',
                                   'features': ['Payroll'], 'highlight': False}])
        )
        self.assertTrue(blocking, 'a stored price should be reported, not accepted')
        self.assertIn('price', ' '.join(blocking))

    def test_pricing_notes_are_kept(self):
        content, blocking, _ = validate_content(
            one('pricing', notes=[{'title': 'Upgrade any time', 'body': 'Carry over.'}])
        )
        self.assertEqual(blocking, [])
        self.assertEqual(content['sections'][0]['notes'][0]['title'], 'Upgrade any time')


class SlugTests(unittest.TestCase):
    def test_good_slugs_are_accepted(self):
        for slug in ('home', 'security', 'payroll-product', 'page2', 'a-b-c'):
            with self.subTest(slug=slug):
                self.assertTrue(is_valid_slug(slug))

    def test_bad_slugs_are_rejected(self):
        for slug in ('', 'Home', 'has space', 'trailing-', '-leading', 'a--b',
                     'under_score', '../etc', 'a/b', 'x' * 100, None, 7):
            with self.subTest(slug=slug):
                self.assertFalse(is_valid_slug(slug))


class SectionTypeParityTests(unittest.TestCase):
    """The backend's type list and the frontend's renderer must not diverge.

    A type the backend accepts but the frontend cannot draw produces a landing
    page with a silent hole in it - the admin sees a valid save, visitors see
    nothing. That is exactly the kind of break that survives review, because
    both halves are individually correct.
    """

    @classmethod
    def setUpClass(cls):
        renderer = FRONTEND / 'components' / 'MarketingSections.jsx'
        if not renderer.exists():
            raise unittest.SkipTest('frontend section renderer not present')
        cls.source = renderer.read_text(encoding='utf-8')

    def test_the_frontend_renders_every_type_the_backend_accepts(self):
        rendered = set(re.findall(r"case\s+'([a-z_]+)'\s*:", self.source))
        missing = sorted(set(SECTION_TYPES) - rendered)
        self.assertEqual(
            missing, [],
            f'the backend accepts section types the frontend cannot draw: {missing}',
        )

    def test_the_frontend_does_not_render_types_the_backend_rejects(self):
        rendered = set(re.findall(r"case\s+'([a-z_]+)'\s*:", self.source))
        extra = sorted(rendered - set(SECTION_TYPES))
        self.assertEqual(
            extra, [],
            f'the frontend renders section types the backend rejects: {extra}',
        )

    def test_every_type_has_a_label_and_a_hint_for_the_editor(self):
        """The editor builds its form from these; a blank label ships a blank box."""
        for name, definition in SECTION_TYPES.items():
            with self.subTest(section=name):
                self.assertTrue(definition.get('label'), f'{name} has no label')
                self.assertTrue(definition.get('hint'), f'{name} has no hint')
                self.assertTrue(definition.get('fields'), f'{name} has no fields')