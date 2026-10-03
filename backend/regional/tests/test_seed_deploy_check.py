"""The statutory tables are seeded by a command, not a migration.

`manage.py seed_country_rules` is what populates `StatutoryRule`. It appears in
a milestone document and nowhere else - not in a deploy script, not in CI.

That was tolerable while an absent contribution rule deducted nothing. It is not
tolerable now that `contribution_coverage_gap` refuses approval when a declared
contribution scheme has no rule: a deployment that skipped the seed produces
payslips that compute correctly and are then refused at approval with
"no verified contribution rule", naming schemes the operator believes are
working.

The symptom reads as corrupt statutory data rather than a missed deploy step,
so a system check is the only thing standing between that and a support call.
"""
from datetime import date

from django.test import TestCase

from accounts.models import Company
from accounts.platform_models import Subscription
from regional.models import CompanyCountryProfile


class StatutorySeedSystemCheckTests(TestCase):
    """`manage.py check` must notice statutory data that was never seeded."""

    def company(self, name, country_code):
        company = Company.objects.create(
            name=name, email=f'{name.lower()}@example.com', is_active=True,
        )
        Subscription.objects.create(company=company, status='trial')
        CompanyCountryProfile.objects.create(
            company=company, country_code=country_code,
            currency_code='NGN', payroll_frequency='monthly',
        )
        return company

    def check(self):
        from regional.apps import statutory_data_seeded
        return statutory_data_seeded()

    def test_it_warns_when_rules_are_missing_but_tenants_exist(self):
        self.company('Unseeded Nigeria', 'NG')

        warnings = self.check()

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].id, 'regional.W001')
        self.assertIn('NG', warnings[0].msg)
        self.assertIn('seed_country_rules', warnings[0].hint)

    def test_it_names_every_affected_country(self):
        self.company('Unseeded Kenya', 'KE')
        self.company('Unseeded Egypt', 'EG')

        warnings = self.check()

        self.assertEqual(len(warnings), 1, 'one warning, not one per country')
        self.assertIn('EG', warnings[0].msg)
        self.assertIn('KE', warnings[0].msg)

    def test_it_is_silent_once_the_rules_are_seeded(self):
        """The check has to be silenceable or it is noise that gets suppressed."""
        from regional.management.commands.seed_country_rules import Command
        Command().handle()
        self.company('Seeded Nigeria', 'NG')

        self.assertEqual(self.check(), [])

    def test_a_fresh_install_with_no_tenants_stays_quiet(self):
        """Nothing to block yet, so nothing to warn about.

        Making this an Error would make `manage.py migrate` fail on a new
        database, which is the state the seed is supposed to be run against.
        """
        self.assertEqual(self.check(), [])

    def test_it_is_a_warning_not_an_error(self):
        """An Error would make `check --deploy` and `migrate` fail.

        That would block the very deploy step the check exists to prompt.
        """
        from django.core.checks import Error, Warning as DjangoWarning
        self.company('Unseeded Nigeria', 'NG')

        warnings = self.check()

        self.assertFalse(any(isinstance(w, Error) for w in warnings))
        self.assertTrue(all(isinstance(w, DjangoWarning) for w in warnings))


class SeededTenantIsApprovableTests(TestCase):
    """The real consequence: does an unseeded deployment actually break?

    This is the behaviour the check is describing, asserted directly, so the
    check cannot drift away from the thing it warns about.
    """

    def test_an_unseeded_existing_country_cannot_be_approved(self):
        from datetime import timedelta

        from decimal import Decimal

        from django.utils import timezone
        from rest_framework.test import APIClient

        from accounts.models import User
        from accounts.secrets import encrypt_secret
        from employees.models import Employee
        from payroll.models import PayrollConfig, PayrollRun
        from payroll.services import calculate_payslip
        from security.models import MFADevice, SecuritySession
        from security.utils import hash_value, totp_secret

        company = self._company_with_profile()
        config = PayrollConfig.objects.create(company=company, currency='NGN')
        employee = Employee.objects.create(
            company=company, employee_code='N1', first_name='Ada',
            last_name='Obi', email='ada@example.com',
            base_salary=Decimal('250000'),
        )
        run = PayrollRun.objects.create(
            company=company, period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 31),
        )
        run.payslips.create(
            employee=employee, **calculate_payslip(employee, config, run),
        )
        run.status = 'processed'
        run.save(update_fields=['status'])

        owner = User.objects.create_user(
            username='unseeded-owner', email='unseeded@example.com',
            password='StrongPassword123!', company=company, role='owner',
        )
        raw = 'unseeded-session'
        MFADevice.objects.create(
            user=owner, secret_encrypted=encrypt_secret(totp_secret()), enabled=True,
        )
        SecuritySession.objects.create(
            user=owner, company=company, secret_hash=hash_value(raw),
            expires_at=timezone.now() + timedelta(hours=1),
            mfa_verified=True, mfa_verified_at=timezone.now(),
        )
        client = APIClient()
        client.cookies['hrcloudpay_session'] = raw

        response = client.post(
            f'/api/payroll/runs/{run.id}/approve/', {}, format='json',
        )

        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data['code'], 'compliance_gaps_unacknowledged')
        codes = {g['code'] for g in response.data['compliance_gaps']}
        self.assertIn('statutory_contribution_unavailable', codes)

    def _company_with_profile(self):
        company = Company.objects.create(
            name='Unseeded Nigeria Co', email='unseededco@example.com', is_active=True,
        )
        Subscription.objects.create(company=company, status='trial')
        CompanyCountryProfile.objects.create(
            company=company, country_code='NG', currency_code='NGN',
            payroll_frequency='monthly',
        )
        return company