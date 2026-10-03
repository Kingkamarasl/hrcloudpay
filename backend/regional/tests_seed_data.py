"""Tests pinning the statutory seed data against its sources.

This file exists because two seeded tables were found wrong in October 2026 and
nothing in the suite would have noticed:

* Nigeria's pension contribution carried 7.5% + 7.5% = 15%, the rate the Pension
  Reform Act 2014 repealed, while citing the PenCom page that states the
  replacement 8% + 10% = 18%.
* Ghana's PAYE band table did not match any published Ghana Revenue Authority
  scale - different band count, different thresholds, and a 37.5% top rate the
  current scale does not contain (35% is the maximum).

Both would have produced confidently wrong figures with no warning, which is
strictly worse than the blocking compliance gap they replaced.

These tests deliberately assert the *numbers*, not merely that rows exist. A
presence check would have passed on both wrong tables.
"""

from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from regional.countries.registry import COUNTRY_PACKS
from regional.management.commands.seed_country_rules import (
    COUNTRIES_WITHOUT_PAYE,
    PAYE_RULES,
    RULES,
    SUPPORTED_COUNTRIES,
    Command,
)
from regional.management.commands.seed_filing_rules import RULES as FILING_RULES
from regional.models import StatutoryRule


def paye_rule(country_code):
    for rule in PAYE_RULES:
        if rule['country_code'] == country_code:
            return rule
    return None


def contribution_rule(country_code, code):
    for rule in RULES:
        if rule['country_code'] == country_code and rule['code'] == code:
            return rule
    return None


class NigeriaBandTests(SimpleTestCase):
    """Nigeria Tax Act 2026, in force 1 January 2026.

    Verified against the PwC Nigeria individual tax summary and the GRA tables.
    """

    # Cumulative upper bounds. The Act publishes band *widths*; the engine
    # consumes cumulative uppers, so both have to agree.
    EXPECTED_BANDS = [
        (800000, '0'),
        (3000000, '15'),
        (12000000, '18'),
        (25000000, '21'),
        (50000000, '23'),
        (None, '25'),
    ]

    def test_the_bands_match_the_nigeria_tax_act_2026(self):
        rule = paye_rule('NG')
        self.assertIsNotNone(rule, 'Nigeria has no seeded PAYE rule')
        bands = [(b['upper'], b['rate']) for b in rule['metadata']['bands']]
        self.assertEqual(bands, self.EXPECTED_BANDS)

    def test_the_cumulative_uppers_equal_the_sum_of_the_act_band_widths(self):
        """The Act states widths (800,000 / 2,200,000 / 9,000,000 / 13,000,000 /
        25,000,000 / 25,000,000). If the cumulative table ever drifts, this is
        what catches it - a plausible-looking but wrong table still passes a
        shape check."""
        widths = [800000, 2200000, 9000000, 13000000, 25000000]
        running = 0
        expected = []
        for width in widths:
            running += width
            expected.append(running)
        expected.append(None)  # open-ended top band

        rule = paye_rule('NG')
        actual = [b['upper'] for b in rule['metadata']['bands']]
        self.assertEqual(actual, expected)


class NigeriaPensionTests(SimpleTestCase):
    """Pension Reform Act 2014 s.4(1): 10% employer + 8% employee minimum."""

    def test_the_contribution_is_18_percent_split_10_8_not_15_percent(self):
        rule = contribution_rule('NG', 'pension')
        self.assertIsNotNone(rule)
        meta = rule['metadata']
        self.assertEqual(meta['employee_rate'], '8')
        self.assertEqual(meta['employer_rate'], '10')
        self.assertEqual(
            Decimal(meta['employee_rate']) + Decimal(meta['employer_rate']),
            Decimal('18'),
        )

    def test_rule_value_matches_the_employee_rate(self):
        """`engine.calculate_statutory_contributions` reads the metadata rates and
        falls back to `rule.value` for the employee side only. A `value` that
        disagreed with `employee_rate` would apply a different rate depending on
        which branch was taken."""
        rule = contribution_rule('NG', 'pension')
        self.assertEqual(str(rule['value']), rule['metadata']['employee_rate'])

    def test_the_repealed_7_5_percent_rate_is_not_still_present(self):
        for rule in RULES:
            rates = {str(rule.get('value'))} | {str(v) for v in (rule.get('metadata') or {}).values()}
            self.assertNotIn(
                '7.5', rates,
                f'{rule["country_code"]}:{rule["code"]} still carries the repealed 7.5% rate',
            )


class GhanaIsDeliberatelyUnseededTests(SimpleTestCase):
    def test_ghana_has_no_seeded_paye_table(self):
        self.assertIsNone(
            paye_rule('GH'),
            'Ghana has a PAYE rule again. The GRA scale needs finance sign-off '
            'first -- two annual tables are in force during 2026.',
        )

    def test_ghana_is_declared_as_having_no_paye(self):
        self.assertIn('GH', COUNTRIES_WITHOUT_PAYE)


class CountriesWithoutPayeTests(SimpleTestCase):
    def test_the_list_is_honest_about_what_is_missing(self):
        """Every country that lacks a seeded PAYE rule must be declared, and
        every declared country must actually lack one.

        A country absent from this list silently computes zero income tax with
        no compliance gap - the exact defect this suite exists to prevent.
        """
        seeded = {r['country_code'] for r in PAYE_RULES}
        for country in COUNTRY_PACKS:
            if country in seeded:
                self.assertNotIn(
                    country, COUNTRIES_WITHOUT_PAYE,
                    f'{country} has a PAYE rule but is also declared as missing one',
                )
            else:
                self.assertIn(
                    country, COUNTRIES_WITHOUT_PAYE,
                    f'{country} has no PAYE rule but is not declared as missing '
                    f'one, so its payroll will silently compute zero tax',
                )

    def test_every_country_we_sell_is_either_supported_or_flagged(self):
        for country in COUNTRY_PACKS:
            self.assertIn(
                country, set(SUPPORTED_COUNTRIES) | set(COUNTRIES_WITHOUT_PAYE),
                f'{country} is neither seeded nor declared',
            )


class BandShapeTests(SimpleTestCase):
    """Malformed band tables produce plausible-looking but wrong tax.

    These checks are cheap and catch the failure mode where someone edits one
    number and leaves the structure inconsistent.
    """

    def test_each_table_ends_with_an_open_ended_top_band(self):
        for rule in PAYE_RULES:
            bands = rule['metadata']['bands']
            self.assertTrue(
                bands, f'{rule["country_code"]} has an empty band table')
            self.assertIsNone(
                bands[-1]['upper'],
                f'{rule["country_code"]} has no open-ended top band, so income '
                f'above the last threshold is taxed at nothing',
            )

    def test_upper_bounds_increase_and_rates_do_not_decrease(self):
        for rule in PAYE_RULES:
            previous_upper = 0
            previous_rate = Decimal('-1')
            for index, band in enumerate(rule['metadata']['bands']):
                if band['upper'] is not None:
                    self.assertGreater(
                        band['upper'], previous_upper,
                        f'{rule["country_code"]} band {index} does not increase',
                    )
                    previous_upper = band['upper']
                rate = Decimal(band['rate'])
                self.assertGreaterEqual(
                    rate, previous_rate,
                    f'{rule["country_code"]} band {index} rate decreases, so the '
                    f'scale is not progressive and higher earners pay less',
                )
                previous_rate = rate


class SourceReferenceTests(SimpleTestCase):
    def test_every_seeded_rate_cites_a_source(self):
        for rule in RULES + PAYE_RULES:
            self.assertTrue(
                rule.get('source_reference'),
                f'{rule["country_code"]}:{rule["code"]} has no source reference',
            )

    def test_every_seeded_filing_rule_cites_a_source(self):
        for country, code, *_rest in FILING_RULES:
            source = _rest[-2]
            self.assertTrue(source, f'{country}:{code} has no source reference')


class SeedCommandTests(TestCase):
    """The command must produce what the module-level lists describe."""

    def test_running_the_command_creates_the_declared_rules(self):
        self.assertEqual(StatutoryRule.objects.count(), 0)
        Command().handle()
        self.assertEqual(StatutoryRule.objects.count(), len(RULES) + len(PAYE_RULES))

    def test_the_seeded_nigeria_pension_row_carries_the_2014_rates(self):
        Command().handle()
        row = StatutoryRule.objects.get(country_code='NG', code='pension')
        self.assertEqual(row.metadata['employee_rate'], '8')
        self.assertEqual(row.metadata['employer_rate'], '10')

    def test_no_ghana_paye_row_is_created(self):
        Command().handle()
        self.assertFalse(
            StatutoryRule.objects.filter(country_code='GH', rule_type='paye').exists(),
        )

    def test_the_command_is_idempotent(self):
        """Re-running must update in place, not duplicate. Statutory rules are
        effective-dated, so a duplicate would shadow the real row."""
        Command().handle()
        before = StatutoryRule.objects.count()
        Command().handle()
        self.assertEqual(StatutoryRule.objects.count(), before)

    def test_effective_dates_are_in_the_past_so_the_rules_are_active(self):
        """A future effective_from would seed rows that no payroll can see, which
        looks identical to having no rules at all."""
        today = date.today()
        for rule in RULES + PAYE_RULES:
            self.assertLessEqual(
                rule['effective_from'], today,
                f'{rule["country_code"]}:{rule["code"]} is effective from '
                f'{rule["effective_from"]}, in the future',
            )


class TenNewCountryPacksTest(SimpleTestCase):
    """The ten packs added 2026-10-01, and the guarantees they ship under.

    They ship as full packs with no statutory data. That is safe only because
    two guards cover the absence, and these tests exist to prove both are still
    present - a new country added without them would produce a payslip that
    quietly omits an employee's pension.
    """

    NEW_TEN = ('KE', 'TZ', 'UG', 'RW', 'ZM', 'ZW', 'BW', 'NA', 'ZA', 'EG')

    def test_exactly_ten_new_packs_were_added(self):
        """All 54 African UN member states are present.

        This started as an exact-equality check on the original five plus ten,
        and became one over the whole of Africa when the remaining thirty-nine
        were added on 2026-10-02. It stays an exact check rather than a
        superset one on purpose: the pack list is the product's claim about
        which jurisdictions it supports, so an unlisted country slipping in is
        as much a defect as a listed one going missing.
        """
        from regional.tests_country_registry import AFRICAN_UN_MEMBERS
        self.assertEqual(sorted(COUNTRY_PACKS), sorted(AFRICAN_UN_MEMBERS))
        # The original five and the ten of 2026-10-01 remain a subset of it.
        self.assertTrue(
            (set(self.NEW_TEN) | {'NG', 'GH', 'SL', 'LR', 'GM'}).issubset(COUNTRY_PACKS)
        )

    def test_each_new_pack_is_complete(self):
        """A pack missing a currency or a timezone is not a pack."""
        for code in self.NEW_TEN:
            with self.subTest(country=code):
                pack = COUNTRY_PACKS[code]
                self.assertEqual(pack.code, code)
                self.assertTrue(pack.name, 'no display name')
                self.assertEqual(len(pack.currency), 3, 'currency must be ISO 4217')
                self.assertTrue(pack.currency.isupper(), pack.currency)
                self.assertTrue(pack.timezone.startswith('Africa/'), pack.timezone)
                self.assertEqual(pack.payroll_frequencies, ('monthly',))
                self.assertTrue(pack.employee_identifiers, 'no employee identifiers')
                self.assertTrue(pack.employee_fields, 'no employee fields')
                self.assertIn('quickbooks', pack.integration_tags)

    def test_no_new_pack_ships_with_statutory_data_invented(self):
        """The load-bearing one.

        A plausible rate table written from memory is worse than no table: it
        understates the employee's pension and the employer's liability while
        looking authoritative. The Ghana band table already had to be removed
        for exactly this reason.
        """
        for code in self.NEW_TEN:
            with self.subTest(country=code):
                for rule in RULES + PAYE_RULES:
                    self.assertNotEqual(
                        rule['country_code'], code,
                        f'{code} ships with a seeded statutory rule ({rule["code"]}) '
                        f'but no source was verified for it')

    def test_every_new_pack_declares_what_it_would_deduct(self):
        """Without this the contribution guard has nothing to check against."""
        for code in self.NEW_TEN:
            with self.subTest(country=code):
                self.assertTrue(
                    COUNTRY_PACKS[code].contribution_codes,
                    f'{code} declares no contribution codes, so a missing scheme '
                    f'there could not be detected')

    def test_the_seed_command_announces_all_ten(self):
        """The command's warning is the only way an operator finds out a country
        is blocked, so a filter that excluded the new packs would leave them
        blocked and unannounced."""
        from regional.management.commands.seed_country_rules import _announced_unverified_paye
        announced = set(_announced_unverified_paye())
        for code in self.NEW_TEN:
            self.assertIn(code, announced, f'{code} is blocked but not announced')

    def test_the_country_choices_match_the_registry(self):
        """A pack with no `COUNTRY_CHOICES` entry cannot be selected for a
        company, so it would exist in code and nowhere in the product."""
        from regional.models import COUNTRY_CHOICES
        self.assertEqual(
            sorted(code for code, _name in COUNTRY_CHOICES),
            sorted(COUNTRY_PACKS),
            'COUNTRY_CHOICES and COUNTRY_PACKS have drifted apart')


class TenNewCountryGapsTest(TestCase):
    """The runtime half of the guarantee: both guards actually fire.

    Split from `TenNewCountryPacksTest` because both gap functions read
    `StatutoryRule`, and that class is a `SimpleTestCase` with no database
    access - by design, since its other assertions are about static data.
    """

    NEW_TEN = ('KE', 'TZ', 'UG', 'RW', 'ZM', 'ZW', 'BW', 'NA', 'ZA', 'EG')
    AS_OF = date(2026, 10, 31)

    def test_every_new_pack_raises_a_blocking_paye_gap(self):
        from regional.paye import paye_coverage_gap
        for code in self.NEW_TEN:
            with self.subTest(country=code):
                gap = paye_coverage_gap(code, self.AS_OF)
                self.assertIsNotNone(gap, f'{code} has no band table and must say so')
                self.assertEqual(gap['severity'], 'blocking')
                self.assertEqual(gap['cause'], 'no_active_rule')
                self.assertEqual(gap['country_code'], code)

    def test_every_new_pack_raises_a_blocking_contribution_gap(self):
        from regional.engine import contribution_coverage_gap
        for code in self.NEW_TEN:
            with self.subTest(country=code):
                gaps = contribution_coverage_gap(code, self.AS_OF)
                self.assertEqual(len(gaps), 1, f'{code} reported no contribution gap')
                self.assertEqual(gaps[0]['severity'], 'blocking')
                self.assertEqual(
                    sorted(gaps[0]['missing_codes']),
                    sorted(COUNTRY_PACKS[code].contribution_codes),
                    f'{code} gap does not name every scheme it should')

    def test_seeding_the_original_five_silences_both_guards(self):
        """The guard has to be silenceable, or it is noise rather than a signal.

        Running the real command and re-checking proves the packs are not
        permanently blocked, and that adding rules to the seed data is the
        actual remedy rather than a code change.
        """
        from regional.management.commands.seed_country_rules import Command
        from regional.engine import contribution_coverage_gap
        from regional.paye import paye_coverage_gap
        Command().handle()
        for code in ('NG', 'GH', 'SL', 'LR', 'GM'):
            with self.subTest(country=code):
                self.assertEqual(contribution_coverage_gap(code, self.AS_OF), [],
                                 f'{code} is fully seeded but still reports a gap')
        # PAYE: only Nigeria has bands, so only Nigeria's tax gap should clear.
        self.assertIsNone(paye_coverage_gap('NG', self.AS_OF))
        for code in ('GH', 'SL', 'LR', 'GM'):
            with self.subTest(unseeded_paye=code):
                self.assertIsNotNone(paye_coverage_gap(code, self.AS_OF))


class SeededDataCoversEveryPackTest(SimpleTestCase):
    """Every pack's `contribution_codes` promise is met by the shipped seeds.

    `CountryPack.contribution_codes` is the checkable claim "for a company in
    this country HRCloudPay deducts these". `contribution_coverage_gap` raises a
    blocking gap for any declared code with no seeded rule, so a pack that
    declares a code the seed data does not contain would block every payroll
    run in that country from day one.

    That is the correct behaviour for a genuinely missing scheme, and the wrong
    behaviour for a typo. These tests separate the two by checking the shipped
    data directly - the runtime gap cannot tell them apart.
    """

    ORIGINAL_FIVE = ('NG', 'GH', 'SL', 'LR', 'GM')

    def test_the_original_five_declares_no_unseeded_contribution_code(self):
        """These are live tenants. The new guard must be silent for all of them.

        A failure here means the guard would block an existing customer's
        payroll, which is a regression rather than a safety improvement.
        """
        for code in self.ORIGINAL_FIVE:
            with self.subTest(country=code):
                pack = COUNTRY_PACKS[code]
                unseeded = [c for c in pack.contribution_codes
                            if contribution_rule(code, c) is None]
                self.assertEqual(
                    unseeded, [],
                    f'{code} declares contribution codes that the seed data does '
                    f'not contain, so every {code} payroll run would carry a '
                    f'blocking gap: {unseeded}')

    def test_every_pack_with_contribution_codes_declares_at_least_one(self):
        """Declaring a compliance domain requires saying something about it.

        A pack that quietly declares `social_security` and then names no scheme
        cannot be guarded, so the choice must be explicit rather than left to
        whoever next edits the dict. There are now three legitimate answers,
        and a fourth - neither of the two below - is what this rejects:

        * `contribution_codes` set - the scheme is known and named, so a missing
          rule is a detectable, specific gap;
        * `contributions_unverified` - contributions are known to be required
          but the collecting body is not confirmed, so the gap still fires and
          still blocks, it simply does not name a fund;
        * neither - the country genuinely has no modelled scheme, and an empty
          contribution list is then correct rather than a silent omission.
        """
        for code, pack in sorted(COUNTRY_PACKS.items()):
            with self.subTest(country=code):
                non_paye_domains = [d for d in pack.compliance_domains if d != 'paye']
                if not non_paye_domains:
                    continue
                self.assertTrue(
                    pack.contribution_codes or pack.contributions_unverified,
                    f'{code} declares the compliance domains {non_paye_domains} '
                    f'but neither contribution_codes nor contributions_unverified, '
                    f'so a missing scheme there could not be detected - set '
                    f'contributions_unverified if the obligation is real but the '
                    f'scheme name is unconfirmed')

    def test_a_pack_never_promises_a_code_it_does_not_seed(self):
        """The full invariant, for every pack that ships with statutory data.

        Newer countries deliberately ship with `contribution_codes` set and no
        seeded rules, so that they raise a visible gap rather than a silent
        zero. Those are allowed through only if they are also listed in
        `COUNTRIES_WITHOUT_PAYE`, which is the flag the seed command already
        warns from - so the warning and the runtime gap cannot disagree.
        """
        from regional.management.commands.seed_country_rules import COUNTRIES_WITHOUT_PAYE
        for code, pack in sorted(COUNTRY_PACKS.items()):
            unseeded = [c for c in pack.contribution_codes
                        if contribution_rule(code, c) is None]
            if not unseeded:
                continue
            with self.subTest(country=code):
                self.assertIn(
                    code, COUNTRIES_WITHOUT_PAYE,
                    f'{code} ships with unseeded contribution codes {unseeded} '
                    f'but is not in COUNTRIES_WITHOUT_PAYE, so the seed command '
                    f'will not warn about it even though its payroll runs will '
                    f'be blocked')