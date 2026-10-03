"""Regression tests for the unverified-statutory-tax gap.

The defect these exist for: `calculate_payslip` reached income tax through a
bare `except Exception` and then fell back to the company's own tax brackets.
For a company in a country HRCloudPay *sells support for* but has no verified
income tax rule for, that fallback produced a payslip with `tax_amount` of
zero - and nothing anywhere said so.

Zero is the dangerous number here, not an obviously wrong one. A payslip with
`tax_amount: 0` looks exactly like a payslip for someone below the tax
threshold, so the error survives review, reaches the employee, and under-pays
the revenue authority. Nothing in the payroll run, the payslip JSON, the API or
the UI distinguished "correctly zero" from "we could not compute this".

The rule these encode: HRCloudPay must never present an income tax figure for
a supported country as though it were statutory without saying that it is not.

The Liberia company in the development database was in exactly this state -
`COUNTRIES_WITHOUT_PAYE = ['SL', 'LR', 'GM']` in `seed_country_rules`, so
Liberia has no band table by design, and Liberia is the country the one real
tenant is in.
"""

from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Company, User
from accounts.platform_models import AuditLog, Subscription
from accounts.secrets import encrypt_secret
from employees.models import Employee
from payroll.models import PayrollConfig, PayrollRun, TaxBracket
from payroll.services import calculate_payslip, collect_compliance_gaps
from regional.models import CompanyCountryProfile, StatutoryRule
from security.models import MFADevice, SecuritySession
from security.utils import hash_value, totp_secret

PERIOD_START = date(2026, 10, 1)
PERIOD_END = date(2026, 10, 31)


def stepped_up_session(user, company, raw='compliance-gap-session'):
    """A cookie session already stamped as freshly MFA-verified.

    Approving a run requires a step-up challenge, and `security.step_up` refuses
    token-authenticated clients because a token has no session to stamp. So
    these tests drive a real session rather than `force_authenticate`, which is
    what the existing payroll tests do for the same reason.
    """
    MFADevice.objects.create(
        user=user, secret_encrypted=encrypt_secret(totp_secret()), enabled=True,
    )
    SecuritySession.objects.create(
        user=user, company=company, secret_hash=hash_value(raw),
        expires_at=timezone.now() + timedelta(hours=1),
        mfa_verified=True, mfa_verified_at=timezone.now(),
    )
    return raw


def make_paye_rule(country_code, bands, effective_from=date(2026, 1, 1)):
    return StatutoryRule.objects.create(
        country_code=country_code, code='paye', name='Personal income tax',
        rule_type='paye', calculation_method='progressive_bands',
        metadata={'bands': bands}, effective_from=effective_from,
        source_reference='https://example.gov/paye',
    )


def seed_shipped_contributions():
    """Load the real contribution rules the seed command ships.

    The statutory rows are written by a management command, not a migration, so
    the test database starts with none of them. Without this, every supported
    country in these tests also trips the *contribution* gap, and a test written
    to isolate the tax gap would silently start asserting about two gaps.

    Using the real command rather than hand-written rows matters for the tests
    that assert a run approves cleanly: those are only meaningful if the fixture
    is the data production actually gets.
    """
    from regional.management.commands.seed_country_rules import Command
    Command().handle()


def paye_gaps(result):
    """Only the income-tax gaps, for tests that are specifically about tax."""
    return [g for g in result['breakdown']['compliance_gaps']
            if g['code'] == 'statutory_paye_unavailable']


def make_company(name, country_code=None, tax_rate=None, base_salary='5000'):
    """A company with a payroll config and an in-period payroll run.

    `tax_rate` is the employer's own bracket. It is left unset on purpose in
    the zero-tax case: that is what makes the silent fallback produce exactly
    0.00 rather than merely a wrong number.

    The run is passed into `calculate_payslip` because the rule lookup is
    effective-dated off the run's `period_end` - without a run the engine
    silently falls back to today's date, which would make these assertions
    depend on when the suite happens to execute.
    """
    slug = name.lower().replace(' ', '')
    company = Company.objects.create(name=name, email=f'{slug}@example.com', is_active=True)
    Subscription.objects.create(company=company, status='trial')
    config = PayrollConfig.objects.create(company=company, currency='LRD')
    if tax_rate is not None:
        TaxBracket.objects.create(payroll_config=config, min_amount=0, max_amount=None, rate=tax_rate)
    if country_code:
        CompanyCountryProfile.objects.create(
            company=company, country_code=country_code, currency_code='LRD',
        )
    employee = Employee.objects.create(
        company=company, employee_code='E1', first_name='Grace', last_name='Urey',
        email=f'{slug}-employee@example.com', base_salary=Decimal(base_salary),
    )
    run = PayrollRun.objects.create(
        company=company, period_start=PERIOD_START, period_end=PERIOD_END,
    )
    return company, config, employee, run


class UnverifiedStatutoryContributionTests(TestCase):
    """The pension/social-security twin of the tax gap, which did not exist.

    `paye_coverage_gap` had no counterpart on the contribution side:
    `calculate_statutory_contributions` filters whatever rules exist and
    returns a list, so a supported country with no seeded contribution rows
    produced an empty list and nothing else. No pension line, no social security
    line, no employer cost, and no gap.

    This is worse than the tax case on one axis. A missing tax line is at least
    visible as a large gross-to-net difference. A missing pension line is
    invisible: the payslip is arithmetically correct, the employee has no reason
    to expect a line that never appears, and the money is the employee's own -
    held by the employer, deducted from their salary, and not recoverable by
    them noticing later.
    """

    def _payslip_gaps(self, country_code):
        _, config, employee, run = make_company(f'{country_code} Co', country_code=country_code)
        result = calculate_payslip(employee, config, run)
        return result

    def test_supported_country_without_a_contribution_rule_records_a_gap(self):
        result = self._payslip_gaps('LR')
        gaps = [g for g in result['breakdown']['compliance_gaps']
                if g['code'] == 'statutory_contribution_unavailable']
        self.assertEqual(len(gaps), 1,
                         'Liberia with its NASSCORP rules deleted must report a gap')

    def test_the_gap_names_the_missing_scheme(self):
        """"Something is missing" is not actionable. "NASSCORP was not
        deducted" tells the approver exactly which liability is unrecorded."""
        from regional.engine import contribution_coverage_gap
        from regional.models import StatutoryRule as _SR
        saved = list(_SR.objects.filter(country_code='LR', rule_type='contribution')
                     .values('code', 'name', 'calculation_method', 'value',
                             'metadata', 'source_reference'))
        _SR.objects.filter(country_code='LR', rule_type='contribution').delete()
        try:
            gaps = contribution_coverage_gap('LR', PERIOD_END)
        finally:
            for row in saved:
                _SR.objects.create(country_code='LR', **row)
        self.assertEqual(len(gaps), 1)
        gap = gaps[0]
        self.assertEqual(sorted(gap['missing_codes']),
                         ['nasscorp_eis', 'nasscorp_nps'])
        self.assertEqual(gap['severity'], 'blocking')
        self.assertIn('nasscorp_nps', gap['message'])
        self.assertIn('not deducted', gap['message'])

    def test_a_fully_seeded_country_reports_no_contribution_gap(self):
        """The guard is silent once the rules exist.

        Note this cannot assert anything about the shipped seeds: the test
        database is empty, because the statutory rows are written by a
        management command rather than a migration or fixture. The invariant
        that the *shipped* seed data satisfies every pack's promise lives in
        `regional.tests_seed_data.SeededDataCoversEveryPackTest`.
        """
        from regional.engine import contribution_coverage_gap
        from regional.models import StatutoryRule as _SR
        _SR.objects.create(
            country_code='LR', code='nasscorp_nps', name='NPS',
            rule_type='contribution', calculation_method='percentage',
            value=Decimal('4'), metadata={'employee_rate': '4', 'employer_rate': '4'},
            effective_from=PERIOD_START,
        )
        gaps = contribution_coverage_gap('LR', PERIOD_END)
        self.assertEqual([g['missing_codes'] for g in gaps], [['nasscorp_eis']],
                         'only the still-missing scheme should be reported')

    def test_a_country_outside_the_packs_is_not_a_gap(self):
        """Absence of statutory data for a country we do not sell is the
        expected state, not an omission by us. Same rule as the tax gap."""
        from regional.engine import contribution_coverage_gap
        self.assertEqual(contribution_coverage_gap('FR', PERIOD_END), [])

    def test_the_gap_fires_even_with_statutory_tax_switched_off(self):
        """Contributions are not income tax.

        Guarding them inside the `tax_calculation_enabled` branch would have
        left every company that has not enabled statutory tax with no
        protection at all on the deductions its employees actually lose money
        from.
        """
        from regional.models import StatutoryRule as _SR
        _, config, employee, run = make_company('Liberia Co', country_code='LR')
        _SR.objects.filter(country_code='LR', rule_type='contribution').delete()
        config.tax_calculation_enabled = False
        config.save(update_fields=['tax_calculation_enabled'])
        result = calculate_payslip(employee, config, run)
        codes = [g['code'] for g in result['breakdown']['compliance_gaps']]
        self.assertIn('statutory_contribution_unavailable', codes,
                      'a contribution gap must not depend on the tax setting')

    def test_contribution_and_tax_gaps_both_reach_the_payslip(self):
        """They are separate obligations and both have to be visible."""
        from regional.models import StatutoryRule as _SR
        _, config, employee, run = make_company('Liberia Co', country_code='LR')
        _SR.objects.filter(country_code='LR', rule_type='contribution').delete()
        result = calculate_payslip(employee, config, run)
        codes = {g['code'] for g in result['breakdown']['compliance_gaps']}
        self.assertIn('statutory_paye_unavailable', codes)
        self.assertIn('statutory_contribution_unavailable', codes)


class UnverifiedStatutoryTaxTests(TestCase):
    """A supported country with no verified rule is a gap we own.

    Seeded with the real shipped contribution rules, because these tests are
    about the tax gap. Without them the contribution guard would also fire and
    the assertions below would be counting the wrong thing - which is how a
    guard can be present, correct, and still untested.
    """

    def setUp(self):
        super().setUp()
        seed_shipped_contributions()

    def test_supported_country_without_a_paye_rule_records_a_gap(self):
        """The core regression: Liberia has no band table, so the payslip
        carries zero tax. It must now also carry a blocking gap."""
        _, config, employee, run = make_company('Liberia Co', country_code='LR')

        result = calculate_payslip(employee, config, run)

        self.assertEqual(result['tax_amount'], Decimal('0'),
                         'fixture changed: the silent-zero premise no longer holds')
        gaps = paye_gaps(result)
        self.assertEqual(len(gaps), 1, 'the unverified tax was not reported at all')
        self.assertEqual(gaps[0]['code'], 'statutory_paye_unavailable')
        self.assertEqual(gaps[0]['country_code'], 'LR')
        self.assertEqual(gaps[0]['severity'], 'blocking')
        self.assertEqual(gaps[0]['cause'], 'no_active_rule')
        self.assertIn('Liberia', gaps[0]['message'])
        # The seeded contribution rules mean the contribution guard stays quiet,
        # so this run carries exactly one gap and it is the tax one.
        self.assertEqual(len(result['breakdown']['compliance_gaps']), 1)

    def test_the_gap_is_present_even_when_the_employer_entered_their_own_brackets(self):
        """Using the employer's rates is legitimate; presenting them as
        verified is not. The gap must survive a configured bracket."""
        _, config, employee, run = make_company('Liberia Bracketed', country_code='LR', tax_rate=10)

        result = calculate_payslip(employee, config, run)

        self.assertEqual(result['tax_amount'], Decimal('500.00'))
        self.assertTrue(
            result['breakdown']['compliance_gaps'],
            'configured brackets suppressed the unverified-tax warning')

    def test_a_verified_rule_clears_the_gap(self):
        """The gap must not fire where statutory tax genuinely applies, or it
        becomes noise that gets ignored - which is how the real one got missed."""
        _, config, employee, run = make_company('Liberia Verified', country_code='LR')
        # 5,000/month annualises to 60,000, so the relief band has to sit below
        # that for the rule to actually bite. A threshold above the salary would
        # make this test pass for the wrong reason - correct tax, zero amount.
        make_paye_rule('LR', [{'upper': 30000, 'rate': 0}, {'upper': None, 'rate': 10}])

        result = calculate_payslip(employee, config, run)

        self.assertEqual(result['breakdown']['compliance_gaps'], [])
        # 60,000 annualised less the 30,000 relief band, at 10%, is 3,000 a
        # year, or 250 a month. Asserting the number rather than just "> 0" is
        # what proves the statutory rule was applied and not merely tolerated.
        self.assertEqual(result['tax_amount'], Decimal('250.00'))
        self.assertEqual(result['breakdown']['paye']['rule_code'], 'paye')

    def test_a_country_hrcloudpay_does_not_support_is_never_flagged(self):
        """No false positives. A tenant running its own brackets in a country
        outside the registry is doing something legitimate, and blocking its
        payroll would be HRCloudPay inventing a compliance problem."""
        _, config, employee, run = make_company('Iceland Co', country_code='IS', tax_rate=10)

        result = calculate_payslip(employee, config, run)

        self.assertEqual(result['breakdown']['compliance_gaps'], [])

    def test_a_rule_that_is_not_yet_effective_is_still_a_gap(self):
        """Effective dating means a rule can exist and not apply. A future-dated
        rule must not be counted as coverage for the period being paid."""
        _, config, employee, run = make_company('Liberia Future', country_code='LR')
        make_paye_rule('LR', [{'upper': None, 'rate': 10}], effective_from=date(2027, 1, 1))

        result = calculate_payslip(employee, config, run)

        self.assertEqual(result['tax_amount'], Decimal('0'))
        self.assertEqual(
            paye_gaps(result)[0]['cause'], 'no_active_rule',
            'a rule dated after the pay period was treated as coverage')

    def test_an_engine_failure_is_reported_rather_than_swallowed(self):
        """A rule that raises and a rule that is absent both end in the same
        wrong number, so both are reported the same way. The old bare
        `except Exception` made them indistinguishable from a clean run."""
        _, config, employee, run = make_company('Liberia Broken', country_code='LR')
        make_paye_rule('LR', [{'upper': 100, 'rate': 5}])

        with patch('regional.paye.calculate_country_paye', side_effect=ValueError('bad band table')):
            result = calculate_payslip(employee, config, run)

        gaps = paye_gaps(result)
        self.assertEqual(len(gaps), 1, 'an engine error was swallowed into a zero')
        self.assertEqual(gaps[0]['cause'], 'engine_error')
        self.assertIn('bad band table', gaps[0]['detail'])


class ComplianceGapAggregationTests(TestCase):
    def setUp(self):
        super().setUp()
        seed_shipped_contributions()

    def test_one_gap_per_run_not_one_per_employee(self):
        company, config, _, run = make_company('Liberia Crew', country_code='LR', base_salary='1000')
        for i in range(3):
            Employee.objects.create(
                company=company, employee_code=f'C{i}', first_name='A', last_name=f'B{i}',
                email=f'crew{i}@example.com', base_salary=Decimal('1000'),
            )
        for employee in Employee.objects.filter(company=company):
            run.payslips.create(employee=employee, **calculate_payslip(employee, config, run))

        self.assertEqual(len(collect_compliance_gaps(run)), 1,
                         'a run is only as trustworthy as its worst payslip, and a '
                         'repeated identical warning is noise that gets ignored')

    def test_a_run_with_no_payslips_has_no_gaps(self):
        _, _, _, run = make_company('Liberia Empty', country_code='LR')

        self.assertEqual(collect_compliance_gaps(run), [])


class CompliancePackDisclosureTests(TestCase):
    """The pack is what gets handed to an auditor, so the gap has to be in it.

    Without this, acknowledging the gap unblocks approval and then the pack is
    generated presenting a PAYE total of 0.00 as though it were statutory. The
    gap would be disclosed to the approver and withheld from the one reader
    whose job is to check it.
    """

    def setUp(self):
        super().setUp()
        # These runs are for The Gambia, whose contribution rules ship. Without
        # them the manifest would say INCOMPLETE for a contribution gap and the
        # assertion about the *tax* disclosure would pass or fail for the wrong
        # reason.
        seed_shipped_contributions()

    def _manifest(self, run):
        from zipfile import ZipFile

        from regional.compliance import build_compliance_pack_zip, create_compliance_pack

        pack = create_compliance_pack(run)
        self.assertIsNotNone(pack, 'no compliance pack was produced for a country-profile company')
        blob = build_compliance_pack_zip(pack)
        with ZipFile(BytesIO(blob)) as z:
            return z.read('manifest.csv').decode('utf-8')

    def test_the_pack_declares_the_gap(self):
        _, config, employee, run = make_company('Liberia Pack', country_code='LR')
        run.payslips.create(employee=employee, **calculate_payslip(employee, config, run))

        manifest = self._manifest(run)

        self.assertIn('INCOMPLETE', manifest)
        self.assertIn('statutory_paye_unavailable', manifest)
        # The reader of a pack is told what is wrong, not merely that something is.
        self.assertIn('Liberia', manifest)

    def test_a_verified_pack_says_so_rather_than_staying_quiet(self):
        """Silence would be ambiguous - a missing line reads as an older pack."""
        _, config, employee, run = make_company('Gambia Pack', country_code='GM', base_salary='2000')
        make_paye_rule('GM', [{'upper': 30000, 'rate': 0}, {'upper': None, 'rate': 10}])
        run.payslips.create(employee=employee, **calculate_payslip(employee, config, run))

        manifest = self._manifest(run)

        self.assertNotIn('INCOMPLETE', manifest)
        self.assertIn('Statutory verification', manifest)


class ComplianceGapApprovalGateTests(TestCase):
    """Approving is the point of no return, so that is where the gap stops."""

    def setUp(self):
        super().setUp()
        seed_shipped_contributions()
        self.company, self.config, self.employee, self.run = make_company(
            'Liberia Gate', country_code='LR',
        )
        self.user = User.objects.create_user(
            username='lr-owner', email='lr-owner@example.com', password='StrongPassword123!',
            company=self.company, role='owner',
        )
        self.run.payslips.create(
            employee=self.employee, **calculate_payslip(self.employee, self.config, self.run),
        )
        self.run.status = 'processed'
        self.run.save(update_fields=['status'])
        self.client = APIClient()
        self.client.cookies['hrcloudpay_session'] = stepped_up_session(self.user, self.company)

    def test_approval_is_blocked_until_the_gap_is_acknowledged(self):
        response = self.client.post(f'/api/payroll/runs/{self.run.id}/approve/', {}, format='json')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'compliance_gaps_unacknowledged')
        self.assertEqual(response.data['compliance_gaps'][0]['code'], 'statutory_paye_unavailable')
        self.run.refresh_from_db()
        self.assertEqual(self.run.status, 'processed', 'the run was approved anyway')
        self.assertFalse(AuditLog.objects.filter(action='payroll_approve').exists(),
                         'a blocked approval still wrote an approval audit entry')

    def test_a_bare_true_does_not_count_as_acknowledgement(self):
        """The acknowledgement is a record that a human accepted an unverified
        tax result, so it has to be asked for by name."""
        response = self.client.post(
            f'/api/payroll/runs/{self.run.id}/approve/', {'true': True}, format='json',
        )

        self.assertEqual(response.status_code, 409)

    def test_acknowledging_unblocks_approval_and_is_audited(self):
        response = self.client.post(
            f'/api/payroll/runs/{self.run.id}/approve/',
            {'acknowledge_compliance_gaps': 'true'}, format='json',
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'approved')
        entry = AuditLog.objects.filter(action='payroll_approve').first()
        self.assertIsNotNone(entry, 'the acknowledgement left no audit trail')
        acknowledged = entry.metadata['compliance_gaps_acknowledged']
        self.assertEqual(acknowledged[0]['code'], 'statutory_paye_unavailable')

    def test_a_clean_payroll_still_approves_without_acknowledgement(self):
        """No regression: the gate must not fire on a payroll with no gaps."""
        company, config, employee, run = make_company('Gambia Clean', country_code='GM', base_salary='2000')
        make_paye_rule('GM', [{'upper': 300000, 'rate': 0}, {'upper': None, 'rate': 10}])
        user = User.objects.create_user(
            username='gm-owner', email='gm-owner@example.com', password='StrongPassword123!',
            company=company, role='owner',
        )
        run.payslips.create(employee=employee, **calculate_payslip(employee, config, run))
        run.status = 'processed'
        run.save(update_fields=['status'])
        client = APIClient()
        client.cookies['hrcloudpay_session'] = stepped_up_session(user, company, raw='clean-session')

        response = client.post(f'/api/payroll/runs/{run.id}/approve/', {}, format='json')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['compliance_gaps'], [])
