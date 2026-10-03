"""The registration country picker must not hide or mislabel a country.

The country field used to be a native <select> listing every supported country,
which is unreadable at 54 entries. It is now a searchable combobox grouped by
subregion. That is a net gain, but it introduces two ways this screen can go
wrong that a plain <select> could not:

  * a country missing from the groups is unreachable. Nothing errors - the
    control simply has no Nigeria in it, and a prospective customer is turned
    away at signup with no indication of why;
  * a country code typed into the search box resolves to nothing, so someone who
    knows the code rather than the name cannot use the thing at all.

Both are invisible in a screenshot. They are also entirely preventable: the
picker is generated from `COUNTRY_PACKS` on the server, so the checks below
compare the frontend's own tables against that registry rather than against a
hand-kept expectation.

The accent-folding case matters for real users rather than hypothetically. The
picker deliberately matches "cote" against "Cote d'Ivoire" because a keyboard
without an easy-to-reach accent key is the common case, not the exotic one.

Skipped when Node or the frontend source is absent, matching
`regional.tests.test_country_language_api`, which drives the real JSX under
Node for the same reason.
"""
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

from regional.countries.registry import COUNTRY_PACKS

FRONTEND = (
    # parents[3]: this file is backend/regional/tests/<file>.py, so [2] is
    # backend/ and the frontend is one level above that. Getting it wrong makes
    # the class skip silently instead of failing.
    pathlib.Path(__file__).resolve().parents[3]
    / 'frontend' / 'src' / 'pages' / 'Register.jsx'
)

# ['AO', 'Angola'] and ['CI', "Cote d'Ivoire"] - both quote styles occur.
OPTION_RE = re.compile(r"\['([A-Z]{2})',\s*(?:'([^']*)'|\"([^\"]*)\")\]")


class PickerSourceTest(unittest.TestCase):
    """Checks that need only the source text, no JS runtime."""

    @classmethod
    def setUpClass(cls):
        if not FRONTEND.exists():
            raise unittest.SkipTest('frontend source not present in this checkout')
        cls.source = FRONTEND.read_text(encoding='utf-8')
        block = cls.source.split('const COUNTRY_OPTIONS = [', 1)[1].split('\n];', 1)[0]
        cls.options = [
            (code, single or double)
            for code, single, double in OPTION_RE.findall(block)
        ]

    def test_the_picker_lists_exactly_the_registry(self):
        """Same codes, and the same English names, as the server sends.

        `COUNTRY_CHOICES` and this list are two renderings of one fact. A
        country added to the registry must appear here without a second edit,
        and a stale entry here would offer a country the backend rejects.
        """
        self.assertEqual(
            [code for code, _ in self.options],
            sorted(COUNTRY_PACKS),
            'the picker and the country registry list different countries',
        )
        wrong = [
            f'{code}: picker={name!r} registry={COUNTRY_PACKS[code].name!r}'
            for code, name in self.options
            if COUNTRY_PACKS[code].name != name
        ]
        self.assertEqual(wrong, [], f'country names disagree: {wrong}')

    def test_country_is_not_still_a_plain_select(self):
        """The whole point of the change.

        Leaving the old <select> in place alongside the picker would show the
        user two controls for one field, and only the visible one would be
        validated.
        """
        self.assertNotRegex(
            self.source, r'<select[^>]*>\s*\{COUNTRY_OPTIONS',
            'the 54-entry country <select> is still rendered',
        )
        self.assertNotIn(
            '<option', self.source,
            'country options are still emitted as <option> elements',
        )

    def test_an_empty_country_is_rejected_before_the_api_call(self):
        """Replacing a <select> with a text input removes constraint validation.

        `required` on the combobox would be advisory only, so without this guard
        "no country chosen" reaches the API and comes back as an opaque 400.
        """
        self.assertRegex(
            self.source,
            r"if\s*\(!form\.country\)\s*\{[^}]*return;",
            'handleSubmit does not refuse to submit without a country',
        )
        self.assertIn('aria-required="true"', self.source,
                      'the combobox is not marked required for screen readers')

    def test_the_combobox_is_announced_as_one(self):
        """ARIA 1.2 combobox wiring.

        Without these the control degrades to an unlabelled text box: a screen
        reader announces nothing about what it is or what it controls.
        """
        for attribute in ('role="combobox"', 'aria-expanded',
                          'aria-controls', 'aria-autocomplete',
                          'aria-activedescendant'):
            with self.subTest(attribute=attribute):
                self.assertIn(attribute, self.source,
                              f'{attribute} is missing from the combobox')


class PickerBehaviourTest(unittest.TestCase):
    """Runs the picker's real filter under Node against real registry data."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.node = shutil.which('node')
        if not FRONTEND.exists():
            raise unittest.SkipTest('frontend source not present in this checkout')
        if not cls.node:
            raise unittest.SkipTest('node is not on PATH')
        cls.source = FRONTEND.read_text(encoding='utf-8')
        cls.result = cls._run()

    @classmethod
    def _harness(cls):
        """Lift the picker's tables and matcher out of the JSX verbatim."""
        def slice_between(start, end):
            return cls.source.split(start, 1)[1].split(end, 1)[0]

        options = 'const COUNTRY_OPTIONS = [' + slice_between(
            'const COUNTRY_OPTIONS = [', '\n];') + '\n];'
        groups = 'const COUNTRY_GROUPS = [' + slice_between(
            'const COUNTRY_GROUPS = [', '\n];') + '\n];'
        index = 'const SEARCH_INDEX = ' + slice_between(
            'const SEARCH_INDEX = ', ';\n\n') + ';\n'
        matcher = 'function matches(entry, query) {' + slice_between(
            'function matches(entry, query) {', '\n}') + '\n}\n'

        return (
            options + '\n' + groups + '\n' + index + '\n' + matcher
            + r'''
const probe = JSON.parse(process.argv[2]);
const flat = COUNTRY_GROUPS.flatMap((g) => g.codes);
const duplicates = flat.filter((c, i) => flat.indexOf(c) !== i);
const missing = COUNTRY_OPTIONS.map(([code]) => code).filter((c) => !flat.includes(c));

// Resolve a query exactly as the component does, accent folding included.
function resolve(query) {
  const q = query.trim().toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  return SEARCH_INDEX.filter((entry) => matches(entry, q)).map((e) => e.code);
}

const out = {
  duplicates,
  missing,
  groupCounts: COUNTRY_GROUPS.map((g) => ({ label: g.label, n: g.codes.length })),
  codes: COUNTRY_OPTIONS.map(([code]) => code),
  byName: Object.fromEntries(COUNTRY_OPTIONS.map(([c, n]) => [c, n])),
  lookups: Object.fromEntries(probe.map((q) => [q, resolve(q)])),
};
console.log(JSON.stringify(out));
'''
        )

    @classmethod
    def _run(cls):
        script = pathlib.Path(tempfile.gettempdir()) / 'hrcloudpay_picker_harness.mjs'
        script.write_text(cls._harness(), encoding='utf-8')
        # Every query the assertions below reference, plus the edge cases. Kept
        # as one explicit list because a probe that is missing from here fails
        # as a KeyError in an unrelated test, which reads like a picker bug.
        probes = [
            '', '  ', 'zzzz', 'k',
            # by name
            'nigeria', 'ghana', 'senegal', 'tanzania', 'morocco', 'eswatini',
            'comoros', 'mauritius', 'ivory', 'tome', 'swaziland',
            # by code
            'gh', 'ng', 'ci', 'zw', 'cd',
            # accent folding
            'cote', "cote d'ivoire",
            # partial and mixed case
            'moroc', 'maroc', 'ZA', 'sa', 'tza', 'sao',
        ]
        try:
            proc = subprocess.run(
                [cls.node, str(script), json.dumps(probes)],
                capture_output=True, text=True, timeout=60,
            )
            if proc.returncode != 0:
                raise AssertionError(
                    f'the picker tables did not execute: {proc.stderr.strip()[:400]}')
            return json.loads(proc.stdout)
        finally:
            script.unlink(missing_ok=True)

    def test_no_country_is_duplicated_across_the_groups(self):
        """A country listed twice appears twice in the list.

        Not cosmetic: `flat[activeIndex]` is the keyboard's index space, so a
        duplicate makes ArrowDown skip an entry and Enter commit the wrong one.
        """
        self.assertEqual(
            self.result['duplicates'], [],
            f'country codes in more than one group: {self.result["duplicates"]}',
        )

    def test_no_country_is_missing_from_the_groups(self):
        """The failure that would quietly drop a country from signup."""
        self.assertEqual(
            self.result['missing'], [],
            f'countries selectable but not reachable in the list: '
            f'{self.result["missing"]}',
        )

    def test_the_groups_cover_all_fifty_four(self):
        total = sum(g['n'] for g in self.result['groupCounts'])
        self.assertEqual(
            len(self.result['codes']), len(COUNTRY_PACKS),
            'COUNTRY_OPTIONS no longer matches the registry size',
        )
        self.assertEqual(
            total, len(COUNTRY_PACKS),
            f'group membership totals {total}, not {len(COUNTRY_PACKS)}',
        )

    def test_searching_by_name_finds_the_country(self):
        for query, expected in [
            ('nigeria', 'NG'), ('ghana', 'GH'), ('senegal', 'SN'),
            ('tanzania', 'TZ'), ('morocco', 'MA'), ('eswatini', 'SZ'),
            ('comoros', 'KM'), ('mauritius', 'MU'),
        ]:
            with self.subTest(query=query):
                self.assertIn(expected, self.result['lookups'][query])

    def test_searching_by_code_finds_the_country(self):
        """The codes are printed beside every name, so they must work as input."""
        for query, expected in [('gh', 'GH'), ('ng', 'NG'), ('ci', 'CI'),
                                ('zw', 'ZW'), ('cd', 'CD')]:
            with self.subTest(query=query):
                self.assertIn(expected, self.result['lookups'][query])

    def test_search_folds_accents_so_ascii_input_still_matches(self):
        """`cote` must reach Cote d'Ivoire.

        The registry stores the name with its accent because that is the
        country's real name; folding happens only in the search index, so the
        label on screen is unchanged.
        """
        for query in ('cote', "cote d'ivoire"):
            with self.subTest(query=query):
                self.assertIn('CI', self.result['lookups'][query])

    def test_a_query_that_matches_nothing_returns_nothing(self):
        self.assertEqual(self.result['lookups']['zzzz'], [])

    def test_an_empty_query_returns_everything(self):
        """Clearing the box has to restore the full list, not a blank panel."""
        self.assertEqual(
            len(self.result['lookups']['']), len(COUNTRY_PACKS),
            'an empty search box does not list every country',
        )

    def test_a_short_query_does_not_match_the_world(self):
        """Guards the substring match from becoming useless.

        `k` appears in very few names, but `a` appears in most - the search must
        stay useful rather than returning the whole list for any common letter.
        """
        hits = self.result['lookups']['k']
        self.assertGreater(len(hits), 0, 'a single letter matches nothing at all')
        self.assertLess(
            len(hits), len(COUNTRY_PACKS),
            'a single letter matches every country, so search filters nothing',
        )