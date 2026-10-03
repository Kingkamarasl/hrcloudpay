"""An empty filing calendar must not claim the operator can fix it.

The statutory compliance page shows a filing calendar per country. When it is
empty it used to say "No seeded deadlines - run the filing-rule seed command
after installing the latest backend migration", which is advice that was true
for the original five and became false the moment the country packs expanded.

For a country whose deadlines HRCloudPay has not verified, running the command
produces nothing. Telling the user to run it anyway means an absent compliance
calendar presents as a setup step that was missed, gets retried weekly, and
never resolves - which is worse than saying plainly that the calendar is not
available for that country yet.

The distinction these pin down:

  ``none_due``   rules exist for the country, none fall in the window.
                 Expected, and the operator has nothing to do.
  ``unverified`` no verified rule exists for a country we claim to support.
                 Not the operator's to fix, and not fixable by the seed command.

The backend owns that sentence. A frontend that rebuilds it is how two
different explanations of the same empty calendar end up existing.
"""
from datetime import date

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from accounts.models import Company, User
from accounts.platform_models import Subscription
from regional.models import CompanyCountryProfile, StatutoryFilingRule
from regional.views import filing_calendar_availability


class FilingCalendarAvailabilityTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Calendar Co', email='calendar@example.com', is_active=True,
        )
        Subscription.objects.create(company=self.company, status='trial')
        self.owner = User.objects.create_user(
            username='calendar-owner', email='calendar-owner@example.com',
            password='StrongPassword123!', company=self.company, role='owner',
        )

    def profile(self, country_code):
        return CompanyCountryProfile.objects.create(
            company=self.company, country_code=country_code,
            currency_code='NGN', payroll_frequency='monthly',
        )

    def test_a_seeded_country_with_no_upcoming_due_date_is_none_due(self):
        """Rules exist, so an empty window is a real answer, not a gap."""
        self.profile('NG')
        StatutoryFilingRule.objects.create(
            country_code='NG', code='paye', name='PAYE',
            authority='Tax Authority', filing_type='tax',
            frequency='monthly', due_day=10,
            effective_from=date(2026, 1, 1),
        )
        self.assertEqual(filing_calendar_availability('NG'), 'none_due')

    def test_a_supported_country_with_no_rules_is_unverified(self):
        """The state every one of the ten new countries ships in.

        Not "none due" and not a setup step the operator missed. HRCloudPay
        simply has no verified deadline for this country.
        """
        for code in ('KE', 'TZ', 'UG', 'RW', 'ZM', 'ZW', 'BW', 'NA', 'ZA', 'EG'):
            with self.subTest(country=code):
                self.assertEqual(filing_calendar_availability(code), 'unverified')

    def test_a_country_outside_the_packs_is_also_unverified(self):
        """Absence of data for a country we do not sell is not a gap we own."""
        self.assertEqual(filing_calendar_availability('FR'), 'unverified')

    def test_a_deactivated_rule_still_counts_as_verified(self):
        """A rule switched off is a deliberate change, not missing knowledge.

        Treating it as absent would have re-introduced the same advice-to-run-a-
        useless-command problem for a country whose deadlines are known.
        """
        self.profile('LR')
        StatutoryFilingRule.objects.create(
            country_code='LR', code='paye', name='PAYE',
            authority='LRA', filing_type='tax', frequency='monthly',
            due_day=10, effective_from=date(2026, 1, 1), is_active=False,
        )
        self.assertEqual(filing_calendar_availability('LR'), 'none_due')

    def test_the_endpoint_reports_which_case_it_is(self):
        """The frontend has to be able to tell them apart."""
        self.profile('KE')
        client = APIClient()
        client.force_authenticate(self.owner)

        response = client.get('/api/regional/filing-calendar/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['filings'], [])
        self.assertEqual(response.data['calendar_status'], 'unverified')
        self.assertEqual(response.data['country'], 'KE')

    def test_the_endpoint_reports_none_due_for_a_seeded_country(self):
        self.profile('LR')
        StatutoryFilingRule.objects.create(
            country_code='LR', code='paye', name='PAYE', authority='LRA',
            filing_type='tax', frequency='annual', due_day=31, due_month=1,
            effective_from=date(2026, 1, 1),
        )
        client = APIClient()
        client.force_authenticate(self.owner)

        response = client.get('/api/regional/filing-calendar/')

        self.assertEqual(response.status_code, 200, response.data)
        # An annual January rule will always produce at least one upcoming due
        # date, so this asserts the status rather than the row count.
        self.assertEqual(response.data['calendar_status'], 'none_due')

    def test_an_unconfigured_company_is_not_given_a_country_status(self):
        """No country profile means the calendar is not the country's problem
        yet. The existing `configured: False` contract already covers it, and
        adding a status here would imply the calendar had been assessed."""
        client = APIClient()
        client.force_authenticate(self.owner)

        response = client.get('/api/regional/filing-calendar/')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data['configured'])
        self.assertNotIn('calendar_status', response.data)


class FilingCalendarCopyTests(SimpleTestCase):
    """The empty calendar must not promise a remedy that cannot work.

    Running the filing-rule seed command cannot fix an unverified country -
    there is nothing for it to seed. Telling the user to run it anyway turns a
    permanent absence into a permanent setup step that gets retried weekly and
    never resolves, which is worse than saying plainly that the calendar is not
    available.

    The JSX source is the authority here. The built bundle is additionally
    checked when present, because `frontend_dist` is gitignored and a deploy
    that copies the tree without running `npm run build` serves the previous
    copy - which would ship the wrong sentence while the source looks correct.

    `frontend_dist` being gitignored also means it is legitimately absent in a
    clean checkout, so the bundle assertions are skipped rather than failed
    there. Failing on a missing bundle would make the Python suite
    unrunnable without a Node toolchain, and would fail for the one condition
    that has nothing to do with the behaviour under test.
    """

    # The specific promise that cannot be kept.
    UNACTIONABLE = 'seed command'

    def _source(self):
        import pathlib
        # parents: [tests, regional, backend, project root]
        path = (pathlib.Path(__file__).resolve().parents[3]
                / 'frontend' / 'src' / 'pages' / 'StatutoryCompliance.jsx')
        self.assertTrue(path.exists(), f'{path} is missing')
        return path.read_text(encoding='utf-8', errors='replace')

    def _bundle(self):
        """The built bundle, or None when this checkout has not built one."""
        import pathlib
        dist = pathlib.Path(__file__).resolve().parents[2] / 'frontend_dist'
        for path in sorted(dist.glob('assets/*.js')):
            return path.read_text(encoding='utf-8', errors='replace')
        return None

    def test_the_unactionable_advice_is_gone(self):
        source = self._source()
        self.assertNotIn(
            self.UNACTIONABLE, source,
            'the filing calendar still tells users to run the seed command, '
            'which produces no result for a country with no verified rules')

    def test_the_frontend_branches_on_the_backend_status(self):
        """Otherwise the copy cannot be scoped to the case it is true for.

        A single unconditional empty-state sentence is what made the two cases
        indistinguishable in the first place.
        """
        source = self._source()
        self.assertIn('calendar_status', source,
                      'the frontend never reads calendar_status, so it cannot '
                      'tell an unverified country from one with nothing due')
        self.assertIn('unverified', source,
                      'the unverified case is never rendered')

    def test_the_unverified_copy_uses_the_backend_country_name(self):
        """The message quotes `country_name` from the API rather than a second
        copy of the country list kept in the frontend.

        A frontend copy of the country names is how the register ends up
        disagreeing with the registry.
        """
        self.assertIn('country_name', self._source(),
                      'the calendar message does not use the backend country name')

    def test_the_built_bundle_matches_the_source(self):
        """Catches a deploy that shipped a stale build.

        Skipped when `frontend_dist` has not been built, which is the correct
        state for a clean checkout.
        """
        bundle = self._bundle()
        if bundle is None:
            self.skipTest('frontend_dist not built in this checkout')
        source = self._source()
        self.assertNotIn(
            self.UNACTIONABLE, bundle,
            'the deployed bundle still contains the unactionable seed-command '
            'advice; run `npm run build` and redeploy')
        for token in ('calendar_status', 'unverified', 'country_name'):
            self.assertIn(token, bundle,
                          f'the deployed bundle is missing {token}; the source '
                          f'has it, so the build is stale')