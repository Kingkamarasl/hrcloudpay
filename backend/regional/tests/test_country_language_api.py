"""The language facts must reach the API, not stop at the registry.

`official_languages` and `localized_name` were added to `CountryPack` so the
compliance view could say that a French- or Arabic-speaking country's filings
are not in English. Recording them in the registry accomplishes nothing on its
own: if the API does not carry them, the frontend has to hardcode a note per
country, and 39 new countries would mean 39 new strings, each of which could
drift from the backend with nothing to catch it.

So these tests pin the transport rather than the data - the data has its own
checks in `regional.tests_country_registry.LanguageDataTest`. What is asserted
here is that every pack reaches both endpoints, that the values match the
registry exactly, and that a company configured for a country gets that
country's languages rather than a default.

The country-options endpoint is deliberately unauthenticated: it is what the
registration page reads before anyone has an account, which is also why it can
carry no company-specific data.
"""
from datetime import date

import json
import pathlib
import re
import shutil
import subprocess
import tempfile

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from accounts.models import Company, User
from accounts.platform_models import Subscription
from regional.countries.registry import COUNTRY_PACKS
from regional.models import CompanyCountryProfile

FRONTEND = (
    # parents[3], not [2]: this file is backend/regional/tests/<file>.py, so
    # [2] is backend/ and the frontend lives one level above that. The sibling
    # suite in backend/regional/ is one directory shallower and needs [2] there -
    # getting this wrong makes the whole class skip silently rather than fail.
    pathlib.Path(__file__).resolve().parents[3]
    / 'frontend' / 'src' / 'pages' / 'StatutoryCompliance.jsx'
)


class CountryOptionsLanguageTests(TestCase):
    """`GET /regional/countries/` - the registration page's country list."""

    def setUp(self):
        self.client = APIClient()

    def rows(self):
        response = self.client.get('/api/regional/countries/')
        self.assertEqual(response.status_code, 200)
        return {row['code']: row for row in response.json()}

    def test_every_pack_is_listed_with_its_languages(self):
        """All 54, not just the fifteen the list used to carry."""
        rows = self.rows()
        self.assertEqual(
            len(rows), len(COUNTRY_PACKS),
            'the country list and the registry have drifted apart in size',
        )
        for code, pack in sorted(COUNTRY_PACKS.items()):
            with self.subTest(country=code):
                self.assertIn(code, rows, f'{code} is not selectable at registration')
                self.assertEqual(
                    rows[code]['official_languages'], list(pack.official_languages),
                    f'{code} reaches the API with the wrong official languages',
                )
                self.assertEqual(
                    rows[code]['localized_name'], pack.localized_name,
                    f'{code} reaches the API with the wrong localised name',
                )

    def test_the_response_is_readable_before_signing_up(self):
        """No auth. The registration page has no session to send."""
        self.assertEqual(
            self.client.get('/api/regional/countries/').status_code, 200,
            'the registration country list requires authentication, so nobody '
            'can pick a country until they have an account',
        )

    def test_a_french_country_reaches_the_api_in_a_usable_form(self):
        """The note in the UI is only renderable if `fr` survives the trip.

        Serialised as a list rather than a bare string so the frontend can map
        it without splitting a string into characters - which is precisely the
        failure the tuple-shape test in the registry suite guards against.
        """
        row = self.rows()['SN']
        self.assertIn('fr', row['official_languages'])
        self.assertIsInstance(row['official_languages'], list)
        self.assertEqual(row['localized_name'], 'Sénégal')


class FilingCalendarLanguageTests(TestCase):
    """`GET /regional/filing-calendar/` - where the note is actually shown."""

    def setUp(self):
        self.company = Company.objects.create(
            name='Language Co', email='language@example.com', is_active=True,
        )
        Subscription.objects.create(company=self.company, status='trial')
        self.owner = User.objects.create_user(
            username='language-owner', email='language-owner@example.com',
            password='StrongPassword123!', company=self.company, role='owner',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def profile(self, country_code, company=None):
        return CompanyCountryProfile.objects.create(
            company=company or self.company, country_code=country_code,
            currency_code='XOF', payroll_frequency='monthly',
        )

    def calendar(self, country_code, company=None, user=None):
        self.profile(country_code, company=company)
        if user is not None:
            self.client.force_authenticate(user)
        response = self.client.get(
            '/api/regional/filing-calendar/', {'days': 120})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_the_company_gets_its_own_countries_languages(self):
        body = self.calendar('CI')
        pack = COUNTRY_PACKS['CI']
        self.assertEqual(body['official_languages'], list(pack.official_languages))
        self.assertEqual(body['localized_name'], pack.localized_name)
        self.assertIn('fr', body['official_languages'])

    def test_the_language_follows_the_company_not_a_fixed_country(self):
        """Two companies on different countries must not see each other's data.

        The whole reason to source this from the pack is that a hardcoded note
        would necessarily be about one country. A single shared literal is the
        bug this replaces.
        """
        first = self.calendar('SN')
        self.assertIn('fr', first['official_languages'])

        other = Company.objects.create(
            name='Other Co', email='other@example.com', is_active=True,
        )
        Subscription.objects.create(company=other, status='trial')
        other_owner = User.objects.create_user(
            username='other-owner', email='other-owner@example.com',
            password='StrongPassword123!', company=other, role='owner',
        )
        second = self.calendar('ZA', company=other, user=other_owner)
        self.assertNotIn(
            'fr', second['official_languages'],
            'a South African company was shown French, which is the hardcoded-'
            'note failure this design is meant to make impossible',
        )
        self.assertEqual(
            second['official_languages'], list(COUNTRY_PACKS['ZA'].official_languages),
        )

    def test_morocco_reports_amazigh_and_not_french(self):
        """The subtle one, pinned at the transport layer too.

        French runs Morocco's administration and banks, so a frontend author
        reaching for "French" would be locally reasonable and still wrong.
        """
        body = self.calendar('MA')
        self.assertIn('ar', body['official_languages'])
        self.assertIn('zgh', body['official_languages'])
        self.assertNotIn('fr', body['official_languages'])
        self.assertEqual(body['localized_name'], 'Maroc')

    def test_an_unconfigured_company_gets_no_language_claim(self):
        """No profile means no country, so no languages either."""
        response = self.client.get('/api/regional/filing-calendar/')
        body = response.json()
        self.assertFalse(body['configured'])
        self.assertNotIn('official_languages', body)


class ComplianceNoteRenderTests(SimpleTestCase):
    """The sentence a French-speaking employer actually reads.

    The note is assembled in the frontend from a template string, so nothing in
    Python exercises it and the only way to see what it says is to run it. The
    first version rendered "French and Arabic are an official language of your
    country" for the six packs with two non-English official languages, because
    the plural branch adjusted the verb and not the noun. That reached the UI
    uncaught, which is the whole reason this exists.

    The real function is lifted out of the JSX and executed under Node against
    every pack's real `official_languages`, so this checks shipped behaviour
    rather than a transcription of it. Skipped when Node or the frontend source
    is absent, matching the precedent in
    `regional.tests.test_filing_calendar_availability`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.node = shutil.which('node')
        if not FRONTEND.exists():
            raise cls.skipTest(cls, 'frontend source not present in this checkout')
        if not cls.node:
            raise cls.skipTest(cls, 'node is not on PATH')
        cls.source = FRONTEND.read_text(encoding='utf-8')
        cls.notes = cls._render_all()

    @classmethod
    def _render_all(cls):
        """Run `languageNote` from the JSX against every pack's languages."""
        names = cls.source.split('const LANGUAGE_NAMES = {', 1)[1].split('\n};', 1)[0]
        set_args = re.search(
            r'const NON_ENGLISH_OFFICIAL = new Set\(\[([^\]]*)\]\);', cls.source
        ).group(1)
        body = cls.source.split('function languageNote(languages) {', 1)[1].split('\n}\n', 1)[0]

        harness = (
            'const LANGUAGE_NAMES = {' + names + '\n};\n'
            'const NON_ENGLISH_OFFICIAL = new Set([' + set_args + ']);\n'
            'function languageNote(languages) {\n' + body + '\n}\n'
            'const codes = JSON.parse(process.argv[2]);\n'
            'console.log(JSON.stringify({\n'
            '  note: languageNote(codes),\n'
            '  named: (codes || []).filter((c) => NON_ENGLISH_OFFICIAL.has(c)),\n'
            '}));\n'
        )
        script = pathlib.Path(tempfile.gettempdir()) / 'hrcloudpay_note_harness.mjs'
        script.write_text(harness, encoding='utf-8')
        try:
            out = {}
            for code, pack in COUNTRY_PACKS.items():
                proc = subprocess.run(
                    [cls.node, str(script), json.dumps(list(pack.official_languages))],
                    capture_output=True, text=True, timeout=30,
                )
                if proc.returncode != 0:
                    raise AssertionError(
                        'the note function did not run for '
                        f'{code}: {proc.stderr.strip()[:300]}')
                out[code] = json.loads(proc.stdout)
            return out
        finally:
            script.unlink(missing_ok=True)

    def test_a_francophone_country_says_the_filing_language_is_not_english(self):
        for code in ('BF', 'SN', 'CI', 'CD', 'TG'):
            with self.subTest(country=code):
                note = self.notes[code]['note']
                self.assertIsNotNone(note, f'{code} gets no language note at all')
                self.assertIn('French', note)
                self.assertIn('is an official language of your country', note)
                self.assertIn("HRCloudPay's interface", note)

    def test_the_note_never_names_a_language_the_pack_does_not_declare(self):
        for code, pack in sorted(COUNTRY_PACKS.items()):
            with self.subTest(country=code):
                for lang in self.notes[code]['named']:
                    self.assertIn(
                        lang, pack.official_languages,
                        f'the note for {code} names {lang!r}, which its pack does '
                        f'not record as official',
                    )

    def test_subject_and_predicate_agree_in_number(self):
        """The grammar bug this class was written for.

        Six packs - Djibouti, Algeria, Equatorial Guinea, Comoros, Morocco and
        Chad - have two non-English official languages. The original template
        pluralised only the verb, producing "French and Arabic are an official
        language". Both branches are now checked against every pack.
        """
        plurals_seen = 0
        for code in sorted(COUNTRY_PACKS):
            with self.subTest(country=code):
                note = self.notes[code]['note']
                if note is None:
                    continue
                count = len(self.notes[code]['named'])
                if count > 1:
                    plurals_seen += 1
                    self.assertIn(
                        'are official languages of your country', note,
                        f'{code} has {count} official languages but the note '
                        f'does not use the plural predicate: {note!r}',
                    )
                    self.assertNotIn(
                        'are an official language of your country', note,
                        f'{code}: plural subject with a singular predicate',
                    )
                else:
                    self.assertIn(
                        'is an official language of your country', note,
                        f'{code} has one official language but the note does '
                        f'not use the singular predicate: {note!r}',
                    )
                    self.assertNotIn(
                        'are official languages of your country', note,
                        f'{code}: singular subject with a plural predicate',
                    )
        self.assertGreater(
            plurals_seen, 0,
            'no pack exercised the plural branch, so this run did not check it',
        )

    def test_english_speaking_countries_get_no_note(self):
        """The note must not fire where filings do run in English.

        Includes countries whose pack lists English alongside a vernacular
        language - South Africa's eleven official languages still include
        English, and its statutory filings run in it - so "English is on the
        list" is the trigger being tested, not "English is the only language".

        Egypt is deliberately absent: Arabic is its official language and
        English, though ubiquitous in commerce there, has no official status.
        """
        english_speaking = ('NG', 'GH', 'SL', 'LR', 'GM', 'ZM', 'NA',
                            'ZA', 'KE', 'UG', 'ZW', 'BW')
        for code in english_speaking:
            with self.subTest(country=code):
                self.assertIn(
                    'en', COUNTRY_PACKS[code].official_languages,
                    f'{code} was listed as English-speaking but its pack does '
                    f'not record English',
                )
                self.assertIsNone(
                    self.notes[code]['note'],
                    f'{code} has English as an official language but is shown a '
                    f'note saying its filings are not in English',
                )

    def test_morocco_is_told_about_amazigh_not_french(self):
        note = self.notes['MA']['note']
        self.assertIn('Arabic', note)
        self.assertIn('Standard Moroccan Tamazight', note)
        self.assertNotIn('French', note)

    def test_the_note_does_not_claim_to_know_the_filing_language(self):
        """It states the product is English, not that filings are French.

        Rwanda records French as official while English has been the language of
        instruction since 2008. A note asserting its filings are in French would
        be wrong there, so the sentence deliberately stops at "you will need to
        file with the authority in the statutory language yourself".
        """
        for code in sorted(COUNTRY_PACKS):
            with self.subTest(country=code):
                note = self.notes[code]['note']
                if note is None:
                    continue
                self.assertNotIn(
                    'are filed in French', note,
                    f'{code}: the note asserts a filing language it cannot know',
                )
                self.assertNotIn(
                    'in French.', note,
                    f'{code}: the note asserts a filing language it cannot know',
                )