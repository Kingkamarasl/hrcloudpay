"""The African country registry: coverage, language facts, and contribution honesty.

Three separate promises are checked here.

*Coverage* - every UN member state of Africa is selectable, and nothing that is
not one is. A country in the product list but not in the registry cannot be set
up, and one in the registry but not the list cannot be selected; the two must
agree exactly or the drift shows up as an unexplained failure for a user.

*Language* - each pack records the country's official languages. HRCloudPay has
no translation infrastructure at all (no `.po`/`.mo` catalogs, no
`LocaleMiddleware`, no `gettext` calls), so this data is never used to serve a
translated interface. It exists so the product can state a plain fact instead of
implying a capability it does not have: statutory filings in a French-speaking
country are filed in French, and HRCloudPay's interface and generated reports
are in English.

*Contributions* - no pack may ship in a state where a missing pension is
invisible. Every pack either names the schemes it should deduct, or declares
that contributions are owed with the scheme name not yet confirmed. Both raise a
blocking gap; a pack that does neither computes a silent zero.
"""

from datetime import date

from django.test import SimpleTestCase, TestCase

from regional.countries.registry import COUNTRY_PACKS, get_country_pack


# The 54 UN member states of Africa. Western Sahara is deliberately excluded: it
# is not a UN member and has no independent revenue or social security authority
# for a statutory filing to be addressed to.
AFRICAN_UN_MEMBERS = frozenset({
    'AO', 'BF', 'BI', 'BJ', 'BW', 'CD', 'CF', 'CG', 'CI', 'CM', 'CV', 'DJ',
    'DZ', 'EG', 'ER', 'ET', 'GA', 'GH', 'GM', 'GN', 'GQ', 'GW', 'KE', 'KM',
    'LR', 'LS', 'LY', 'MA', 'MG', 'ML', 'MR', 'MU', 'MW', 'MZ', 'NA', 'NE',
    'NG', 'RW', 'SC', 'SD', 'SL', 'SN', 'SO', 'SS', 'ST', 'SZ', 'TD', 'TG',
    'TN', 'TZ', 'UG', 'ZA', 'ZM', 'ZW',
})

# The thirty-nine added 2026-10-02, after the original five and the ten of
# 2026-10-01.
NEW_THIRTY_NINE = (
    'AO', 'BF', 'BI', 'CD', 'CF', 'CG', 'CI', 'CM', 'CV', 'DJ', 'DZ', 'ER',
    'ET', 'GA', 'GN', 'GQ', 'GW', 'LS', 'LY', 'MA', 'MG', 'ML', 'MR', 'MU',
    'MW', 'MZ', 'NE', 'SC', 'SD', 'SN', 'SO', 'SS', 'ST', 'SZ', 'TD', 'TG',
    'TN',
)

# Scheme names verified against at least two independent sources before being
# written into a pack. Anything not listed here was left unnamed rather than
# guessed - a wrong scheme name puts a wrong instruction in front of a payroll
# officer, which is worse than saying the name is not yet confirmed.
VERIFIED_SCHEME_NAMES = {
    'BF': ('cnss',),
    'CG': ('cnss',),
    'CI': ('cnps',),
    'CM': ('cnps',),
    'GA': ('cnss',),
    'GQ': ('inseso',),
    'MA': ('cnss',),
    'MG': ('cnaps',),
    'SN': ('cnss',),
}


class AfricanCoverageTest(SimpleTestCase):
    def test_the_registry_holds_exactly_the_african_un_member_states(self):
        self.assertEqual(
            set(COUNTRY_PACKS), set(AFRICAN_UN_MEMBERS),
            'the registry and the list of African UN member states differ',
        )

    def test_country_choices_match_the_registry(self):
        from regional.models import COUNTRY_CHOICES
        self.assertEqual(
            sorted(code for code, _name in COUNTRY_CHOICES), sorted(COUNTRY_PACKS),
            'COUNTRY_CHOICES and COUNTRY_PACKS have drifted apart',
        )

    def test_every_new_pack_is_complete(self):
        for code in NEW_THIRTY_NINE:
            with self.subTest(country=code):
                pack = COUNTRY_PACKS[code]
                self.assertEqual(pack.code, code)
                self.assertTrue(pack.name, 'no display name')
                self.assertEqual(len(pack.currency), 3, 'currency must be ISO 4217')
                self.assertTrue(pack.currency.isupper(), pack.currency)
                self.assertTrue(pack.timezone, 'no timezone')
                self.assertEqual(pack.payroll_frequencies, ('monthly',))
                self.assertTrue(pack.employee_identifiers, 'no employee identifiers')
                self.assertTrue(pack.employee_fields, 'no employee fields')
                self.assertIn('quickbooks', pack.integration_tags)

    def test_every_sequence_field_is_a_tuple_and_never_a_bare_string(self):
        """Structural guard over all 54 packs, not just the new ones.

        This exists because it actually happened. Regenerating this file
        concatenated the scheme codes of four packs - Gambia, Kenya, Liberia and
        Tanzania - into a bare string instead of a tuple:

            contribution_codes='npfiicf'   # not ('npf', 'iicf')

        Python does not reject that. It accepts it happily, because
        `('npf''iicf')` is implicit string concatenation. The damage only
        appeared downstream, where the gap engine iterated the string and
        reported the scheme name as "n, p, f, i, i, c, f" - one letter at a time.
        Every affected payroll would then have been permanently blocked with a
        nonsense message, and the fix is invisible at the point of the mistake.

        So the check is on the type, not on the contents: a bare string is
        always a bug here, because every consumer of these fields iterates them.
        """
        tuple_fields = (
            'payroll_frequencies',
            'employee_identifiers',
            'compliance_domains',
            'integration_tags',
            'contribution_codes',
            'official_languages',
        )
        for code, pack in sorted(COUNTRY_PACKS.items()):
            for field in tuple_fields:
                with self.subTest(country=code, field=field):
                    value = getattr(pack, field)
                    self.assertIsInstance(
                        value, tuple,
                        f'{code}.{field} is {type(value).__name__}, not a tuple. '
                        f'A bare string is always wrong here - iterating it '
                        f'yields one character per item, which silently corrupts '
                        f'whatever consumes this field.',
                    )
                    for member in value:
                        self.assertIsInstance(
                            member, str,
                            f'{code}.{field} contains a non-string member '
                            f'{member!r}',
                        )
                        self.assertTrue(
                            member.strip(),
                            f'{code}.{field} contains a blank member',
                        )

    def test_get_country_pack_still_rejects_unknown_codes(self):
        with self.assertRaises(ValueError):
            get_country_pack('ZZ')

    def test_no_new_pack_ships_with_invented_statutory_data(self):
        """The load-bearing check.

        A rate table written from memory is worse than no table: it understates
        the employee's pension and the employer's liability while looking
        authoritative. The Ghana band table already had to be removed for
        exactly this reason.
        """
        from regional.management.commands.seed_country_rules import PAYE_RULES, RULES
        for code in NEW_THIRTY_NINE:
            with self.subTest(country=code):
                for rule in RULES + PAYE_RULES:
                    self.assertNotEqual(
                        rule['country_code'], code,
                        f'{code} ships with a seeded statutory rule ({rule["code"]}) '
                        f'but no source was verified for it',
                    )


class TimezoneAndCurrencyTest(SimpleTestCase):
    def test_every_pack_timezone_is_a_real_iana_zone(self):
        """A timezone string that does not resolve silently breaks date handling
        for every payslip in that country, and would not show up as an error."""
        import zoneinfo
        try:
            known = zoneinfo.available_timezones()
        except Exception:  # pragma: no cover - platform without a tz database
            self.skipTest('no IANA timezone database available on this platform')
        # Windows ships a partial zone list through the registry; a small list
        # means the database is not usable as an oracle here.
        if len(known) < 300:
            self.skipTest(f'timezone database too small to be an oracle ({len(known)})')
        for code, pack in sorted(COUNTRY_PACKS.items()):
            with self.subTest(country=code):
                self.assertIn(
                    pack.timezone, known,
                    f'{code} names timezone {pack.timezone!r}, which is not an '
                    f'IANA zone identifier',
                )


class LanguageDataTest(SimpleTestCase):
    def test_every_pack_records_at_least_one_official_language(self):
        for code, pack in sorted(COUNTRY_PACKS.items()):
            with self.subTest(country=code):
                self.assertTrue(
                    pack.official_languages,
                    f'{code} records no official language, so the compliance view '
                    f'cannot state which language its filings are filed in',
                )

    def test_francophone_packs_declare_french(self):
        """The reason this field exists.

        Nineteen of the packs have French as an *official* language. A business
        in Abidjan picking "Côte d'Ivoire" in an English-only product could
        otherwise reasonably infer that its CNPS declaration can be filed through
        HRCloudPay. It cannot: the pack ships with no contribution rule and no
        report template, and the compliance gap says so. The language field is
        how the product states that fact rather than leaving it to be
        discovered.

        Deliberately excludes Morocco. French runs Morocco's administration,
        courts and banks and Morocco is a Francophonie member, but it is not
        official there, so recording it would be a false claim in a field whose
        entire purpose is stating facts. See
        `test_morocco_records_amazigh_but_not_french`.
        """
        expected_francophone = {
            'BF', 'BI', 'BJ', 'CD', 'CF', 'CG', 'CI', 'CM', 'DJ', 'GA', 'GN',
            'KM', 'MG', 'ML', 'MU', 'NE', 'RW', 'SC', 'SN', 'TD', 'TG',
        }
        for code in sorted(expected_francophone):
            with self.subTest(country=code):
                self.assertIn(
                    'fr', COUNTRY_PACKS[code].official_languages,
                    f'{code} is French-official but its pack does not record French, '
                    f'so the compliance view would tell a French-speaking employer '
                    f'that their filings are in English',
                )

    def test_morocco_records_amazigh_but_not_french(self):
        """Morocco is the genuine exclusion, and the subtle one.

        French runs Morocco's administration, courts, banks and commerce, and
        Morocco is a member of the Francophonie - so French is heavily used
        without being official. Its official languages are Arabic and Amazigh
        (Berber, official since the 2011 constitution, implemented 2019).

        This was checked against the source rather than assumed, because the
        intuitive answer for a Maghreb country is "French", and recording that
        would be a false claim in the one field whose purpose is stating facts.
        """
        languages = COUNTRY_PACKS['MA'].official_languages
        self.assertIn('ar', languages)
        self.assertIn('zgh', languages, "Morocco's official Amazigh is not recorded")
        self.assertNotIn(
            'fr', languages,
            'French is not an official language of Morocco, however widely it is used',
        )

    def test_mauritius_records_both_english_and_french(self):
        """Mauritius differs from Morocco, and the distinction is worth pinning.

        Its constitution names no official language at all. Article 49 makes
        English and French official *of the National Assembly*, and Mauritius is
        a member of both the Commonwealth and the Francophonie. Recording both is
        the standard position; recording only English - or only Creole, which is
        the lingua franca - would misstate the legal position.
        """
        self.assertEqual(
            set(COUNTRY_PACKS['MU'].official_languages), {'en', 'fr'},
            "Mauritius's pack no longer records English and French",
        )

    def test_rwanda_records_all_four_official_languages(self):
        """Correction to a claim this suite previously made.

        Rwanda was added as an Anglophone pack. English has been the language of
        instruction since 2008 and English is used in most commerce, so the
        classification was defensible - but it was incomplete. Kinyarwanda,
        French, English and Swahili are all official, and French is prominent in
        administration. Recording only English would have told a French-speaking
        Rwandan employer their filings were in English.
        """
        self.assertEqual(
            set(COUNTRY_PACKS['RW'].official_languages),
            {'rw', 'fr', 'en', 'sw'},
            "Rwanda's pack no longer records its four official languages",
        )

    def test_localised_name_is_recorded_where_the_country_uses_another_name(self):
        """Where a country's own-language name differs from the English label.

        This is a convenience label only. It is never rendered instead of the
        English name and it is never sent to a statutory authority - the exact
        authority form language is part of the per-country report work that has
        not been done for any of these countries.
        """
        expected = {
            'BJ': 'Bénin',
            'CD': 'République démocratique du Congo',
            'CF': 'République centrafricaine',
            'CG': 'République du Congo',
            'CM': 'Cameroun',
            'DZ': 'Algérie',
            'ER': 'Érythrée',
            'ET': 'Éthiopie',
            'GN': 'Guinée',
            'GQ': 'Guinée équatoriale',
            'KM': 'Comores',
            'LY': 'Libye',
            'MA': 'Maroc',
            'MZ': 'Moçambique',
            'SN': 'Sénégal',
            'ST': 'São Tomé-et-Príncipe',
            'TD': 'Tchad',
            'TN': 'Tunisie',
        }
        for code, localised in expected.items():
            with self.subTest(country=code):
                self.assertEqual(
                    COUNTRY_PACKS[code].localized_name, localised,
                    f'{code} does not record its own-language name',
                )

    def test_no_pack_records_a_localised_name_the_map_does_not_expect(self):
        """The inverse of the check above.

        Listing only the names that were easy would leave the rest unverified -
        a misspelt or truncated localised name would pass. This asserts the
        recorded set is exactly the reviewed one, so a newly added localised
        name has to be checked and then listed here.
        """
        recorded = {
            code: pack.localized_name
            for code, pack in COUNTRY_PACKS.items()
            if pack.localized_name
        }
        self.assertEqual(len(recorded), 18, 'the number of localised names changed')
        for code, localised in recorded.items():
            with self.subTest(country=code):
                self.assertTrue(
                    localised.strip() == localised and localised,
                    f'{code} records a localised name that is blank or padded',
                )

    def test_localised_name_is_empty_when_it_matches_the_english_name(self):
        """Keeps the field meaningful - a localised_name identical to `name` is
        noise, and would hide a real omission."""
        for code, pack in sorted(COUNTRY_PACKS.items()):
            with self.subTest(country=code):
                self.assertNotEqual(
                    pack.localized_name, pack.name,
                    f'{code} records a localised name identical to its English name',
                )

    def test_every_official_language_can_be_named_by_the_frontend(self):
        """The registry and the UI's language map cannot drift apart.

        `StatutoryCompliance.jsx` turns these ISO codes into English names to
        render the "filings are not in English" note. The two structures live in
        different files in different languages, so nothing else keeps them
        aligned: a country added next year with, say, Wolof would render as the
        bare string "wo" in front of a payroll officer.

        So the map is read out of the JSX source and checked against every code
        any pack actually declares. Same precedent as
        `regional.tests.test_filing_calendar_availability`, which reads the
        frontend to check it quotes the backend's country name.
        """
        import pathlib
        import re

        source = (pathlib.Path(__file__).resolve().parents[2]
                 / 'frontend' / 'src' / 'pages' / 'StatutoryCompliance.jsx')
        if not source.exists():
            self.skipTest('frontend source not present in this checkout')
        text = source.read_text(encoding='utf-8')
        match = re.search(
            r'const LANGUAGE_NAMES = \{(.*?)\};', text, re.S)
        self.assertIsNotNone(
            match, 'LANGUAGE_NAMES is missing from StatutoryCompliance.jsx, so '
                   'no official language can be named in the UI')
        named = set(re.findall(r"^\s*([a-z]{2,3}):\s*'", match.group(1), re.M))

        declared = {lang for pack in COUNTRY_PACKS.values()
                    for lang in pack.official_languages}
        unnamed = sorted(declared - named)
        self.assertEqual(
            unnamed, [],
            f'these official languages have no English name in '
            f'StatutoryCompliance.jsx and would render as bare codes: {unnamed}',
        )

    def test_the_pack_never_promises_a_translated_interface(self):
        """Guards the boundary this decision drew.

        The product is English-only. Recording a country's languages must not
        drift into claiming it can serve that language - the field is a fact
        about the jurisdiction, not a capability flag.
        """
        for code, pack in sorted(COUNTRY_PACKS.items()):
            with self.subTest(country=code):
                self.assertFalse(
                    hasattr(pack, 'ui_language'),
                    f'{code} declares a ui_language, but this build ships no '
                    f'translation catalogs and no LocaleMiddleware',
                )


class ContributionHonestyTest(SimpleTestCase):
    def test_no_pack_is_left_unguarded(self):
        """The invariant that keeps a missing pension visible.

        A pack with non-PAYE compliance domains must either name the schemes it
        deducts, or declare that contributions are owed with the scheme name not
        yet confirmed. Doing neither computes a silent zero on every payslip:
        no pension line, no employer cost, and nothing on the payslip to tell an
        employee that the deduction their own money depends on was skipped.
        """
        for code, pack in sorted(COUNTRY_PACKS.items()):
            with self.subTest(country=code):
                if not [d for d in pack.compliance_domains if d != 'paye']:
                    continue
                self.assertTrue(
                    pack.contribution_codes or pack.contributions_unverified,
                    f'{code} declares non-PAYE compliance domains but neither names '
                    f'a contribution scheme nor declares contributions unconfirmed, '
                    f'so a missing deduction could not be detected',
                )

    def test_a_pack_does_not_both_name_schemes_and_call_them_unconfirmed(self):
        """If the names are known they are the names the approver is told.

        Both together would mean the gap message either named a scheme or said
        it could not, and the two would disagree depending on which branch ran.
        """
        for code, pack in sorted(COUNTRY_PACKS.items()):
            with self.subTest(country=code):
                self.assertFalse(
                    pack.contribution_codes and pack.contributions_unverified,
                    f'{code} both names contribution schemes and declares them '
                    f'unconfirmed',
                )

    def test_only_verified_scheme_names_are_written_down(self):
        """The names in this file were each confirmed against at least two
        independent sources. Anything not in that map was left unnamed, which is
        what `contributions_unverified` records."""
        for code in NEW_THIRTY_NINE:
            with self.subTest(country=code):
                pack = COUNTRY_PACKS[code]
                self.assertEqual(
                    pack.contribution_codes, VERIFIED_SCHEME_NAMES.get(code, ()),
                    f'{code} names contribution codes that were not verified '
                    f'before being written into the registry',
                )

    def test_named_schemes_do_not_ship_with_seed_data(self):
        """Naming a scheme makes it a promise the gap enforces, so the seed data
        must not already satisfy it - otherwise the country would appear
        supported while computing no contribution at all."""
        from regional.management.commands.seed_country_rules import RULES

        def seeded(country_code, code):
            for rule in RULES:
                if rule['country_code'] == country_code and rule['code'] == code:
                    return rule
            return None

        for code in NEW_THIRTY_NINE:
            for scheme in COUNTRY_PACKS[code].contribution_codes:
                with self.subTest(country=code, scheme=scheme):
                    self.assertIsNone(
                        seeded(code, scheme),
                        f'{code}/{scheme} has seed data, so it is no longer one of '
                        f'the unverified countries this suite covers',
                    )


class ContributionGapTest(TestCase):
    """Split from the classes above because both gap paths read `StatutoryRule`
    and `SimpleTestCase` has no database access."""

    AS_OF = date(2026, 10, 31)

    def test_every_new_pack_raises_a_blocking_paye_gap(self):
        from regional.paye import paye_coverage_gap
        for code in NEW_THIRTY_NINE:
            with self.subTest(country=code):
                gap = paye_coverage_gap(code, self.AS_OF)
                self.assertIsNotNone(gap, f'{code} has no band table and must say so')
                self.assertEqual(gap['severity'], 'blocking')
                self.assertEqual(gap['cause'], 'no_active_rule')

    def test_every_new_pack_raises_a_blocking_contribution_gap(self):
        from regional.engine import contribution_coverage_gap
        for code in NEW_THIRTY_NINE:
            with self.subTest(country=code):
                gaps = contribution_coverage_gap(code, self.AS_OF)
                self.assertEqual(
                    len(gaps), 1, f'{code} reported no contribution gap, so a missing '
                                  f'deduction would be invisible on its payslips',
                )
                self.assertEqual(gaps[0]['severity'], 'blocking')

    def test_a_pack_with_verified_names_has_the_gap_name_them(self):
        from regional.engine import contribution_coverage_gap
        for code, schemes in VERIFIED_SCHEME_NAMES.items():
            with self.subTest(country=code):
                gap = contribution_coverage_gap(code, self.AS_OF)[0]
                self.assertEqual(sorted(gap['missing_codes']), sorted(schemes))
                for scheme in schemes:
                    self.assertIn(scheme, gap['message'])

    def test_the_unconfirmed_branch_names_no_scheme(self):
        """The point of the third state.

        Where the scheme name is not confirmed, the gap must say so rather than
        guess. A wrong name would tell a payroll officer to chase the wrong fund,
        which is a worse failure than an incomplete message.
        """
        from regional.engine import contribution_coverage_gap
        for code in NEW_THIRTY_NINE:
            pack = COUNTRY_PACKS[code]
            if pack.contribution_codes:
                continue
            with self.subTest(country=code):
                self.assertTrue(pack.contributions_unverified)
                gap = contribution_coverage_gap(code, self.AS_OF)[0]
                self.assertEqual(
                    gap['missing_codes'], [],
                    f'{code} declares no verified scheme name, so the gap must not '
                    f'claim to have identified one',
                )
                self.assertEqual(gap['cause'], 'scheme_name_unconfirmed')
                self.assertIn('contribution', gap['message'].lower())

    def test_the_whole_african_registry_is_guarded_not_just_the_new_countries(self):
        """One country slipping through the guard is the whole defect, so this
        asserts over every pack rather than the new ones."""
        from regional.engine import contribution_coverage_gap
        for code, pack in sorted(COUNTRY_PACKS.items()):
            with self.subTest(country=code):
                has_domains = [d for d in pack.compliance_domains if d != 'paye']
                gaps = contribution_coverage_gap(code, self.AS_OF)
                if has_domains and (pack.contribution_codes or pack.contributions_unverified):
                    self.assertTrue(gaps, f'{code} declares contributions but is unguarded')
                elif not pack.contribution_codes and not pack.contributions_unverified:
                    self.assertEqual(gaps, [], f'{code} declares nothing, so it must not gap')