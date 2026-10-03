from django.apps import AppConfig
from django.core.checks import Warning as CheckWarning, register


class RegionalConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'regional'


def statutory_data_seeded(app_configs=None, **kwargs):
    """Warn when the statutory tables are empty but companies have employees.

    The statutory rules for the original country packs are written by
    `manage.py seed_country_rules`, not by a migration. That was safe while an
    absent contribution rule simply deducted nothing. It is no longer safe:
    `contribution_coverage_gap` treats a missing contribution rule as a blocking
    compliance gap, so on a deployment where the seed was skipped every payroll
    run for Nigeria, Ghana, Sierra Leone, Liberia and The Gambia is refused
    approval with "no verified contribution rule", naming schemes the operator
    believes are configured.

    The failure is confusing precisely because it looks like a data problem
    rather than a missing deploy step, and the payroll run looks correct right
    up until the moment it cannot be approved.

    A system check is where an operator already looks, and `check` runs in most
    deploy pipelines. It is a Warning rather than an Error on purpose: an Error
    would make `manage.py migrate` and `manage.py check --deploy` fail on a
    fresh database that has not been seeded yet, which is the normal state
    immediately after a first migration and would make the very step being
    warned about impossible to reach.

    Skipping the check on an empty `CompanyCountryProfile` table keeps a brand
    new install quiet - there are no tenants to block yet, so there is nothing
    for the missing data to affect.
    """
    from django.db import DatabaseError, OperationalError

    from regional.models import CompanyCountryProfile, StatutoryRule

    if StatutoryRule.objects.exists():
        return []

    try:
        live = list(
            CompanyCountryProfile.objects
            .exclude(country_code='')
            .values_list('country_code', flat=True)
            .distinct()
        )
    except (OperationalError, DatabaseError):
        # Before `migrate`, or with no database configured. Not this check's
        # problem to report - the migration failure is more useful.
        return []

    if not live:
        return []

    affected = sorted(set(live))
    return [CheckWarning(
        'No statutory rules are seeded, but %d company/countries have a '
        'country profile: %s.' % (len(affected), ', '.join(affected)),
        hint=(
            'Run `python manage.py seed_country_rules` before serving payroll. '
            'Until then every payslip in those countries carries a blocking '
            'compliance gap and payroll runs cannot be approved, because '
            'HRCloudPay cannot verify tax or pension figures it has no rule '
            'for. The payslip totals will still look correct.'
        ),
        id='regional.W001',
    )]