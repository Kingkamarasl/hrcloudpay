from datetime import date
from decimal import Decimal
from django.core.management.base import BaseCommand
from regional.models import StatutoryRule

RULES = [
    # Nigeria: Pension Reform Act 2014 s.4(1) sets the minimum at 10% employer
    # + 8% employee = 18% of monthly emolument. This row previously carried
    # 7.5% + 7.5% = 15%, which is the pre-2014 rate the Act expressly repealed,
    # while citing the very PenCom page that states the new rates.
    dict(country_code='NG', code='pension', name='Retirement pension', rule_type='contribution', calculation_method='percentage', value=Decimal('8'), metadata={'basis':'gross','employee_rate':'8','employer_rate':'10'}, effective_from=date(2026,1,1), source_reference='https://www.pencom.gov.ng/wp-content/uploads/2018/01/PRA_2014.pdf'),
    # Ghana: SSNIT contribution, 5.5% employee and 13% employer to SSNIT/social security framework.
    dict(country_code='GH', code='ssnit', name='SSNIT contribution', rule_type='contribution', calculation_method='percentage', value=Decimal('5.5'), metadata={'basis':'basic','employee_rate':'5.5','employer_rate':'13'}, effective_from=date(2026,1,1), source_reference='https://www.ssnit.org.gh/wp-content/uploads/2023/08/SSNIT-Omnibus.pdf'),
    # Sierra Leone: NASSIT 5% employee + 10% employer.
    dict(country_code='SL', code='nassit', name='NASSIT social security', rule_type='contribution', calculation_method='percentage', value=Decimal('5'), metadata={'basis':'gross','employee_rate':'5','employer_rate':'10'}, effective_from=date(2026,1,1), source_reference='https://nassit.org.sl/our-services/contributions?a=7-727-1'),
    # Liberia: NPS 4% employee + 4% employer; EIS 2% employer.
    dict(country_code='LR', code='nasscorp_nps', name='NASSCORP National Pension Scheme', rule_type='contribution', calculation_method='percentage', value=Decimal('4'), metadata={'basis':'gross','employee_rate':'4','employer_rate':'4'}, effective_from=date(2026,1,1), source_reference='https://www.nasscorp.org.lr/national-pension-scheme/'),
    dict(country_code='LR', code='nasscorp_eis', name='NASSCORP Employment Injury Scheme', rule_type='contribution', calculation_method='percentage', value=Decimal('2'), metadata={'basis':'gross','employee_rate':'0','employer_rate':'2'}, effective_from=date(2026,1,1), source_reference='https://www.nasscorp.org.lr/employment-injury-scheme/'),
    # Gambia: NPF 5% employee + 10% employer, basic salary basis.
    dict(country_code='GM', code='npf', name='SSHFC National Provident Fund', rule_type='contribution', calculation_method='percentage', value=Decimal('5'), metadata={'basis':'basic','employee_rate':'5','employer_rate':'10'}, effective_from=date(2026,1,1), source_reference='https://www.sshfc.gm/national-provident-fund'),
    dict(country_code='GM', code='iicf', name='Industrial Injuries Compensation Fund', rule_type='contribution', calculation_method='percentage_capped', value=Decimal('1'), metadata={'basis':'gross','employee_rate':'0','employer_rate':'1','cap':'15'}, effective_from=date(2026,1,1), source_reference='https://www.sshfc.gm/industrial-injury-compensation-fund'),
]

# Annual graduated PAYE bands consumed by regional.paye._progressive().
# `bands` entries are {'upper': <cumulative upper bound or None>, 'rate': <percent>};
# the final entry must have upper=None to catch the top open-ended band.
# `deductible_contribution_codes` lists contribution rule codes whose EMPLOYEE
# share reduces taxable income.
#
# These are statutory rates -- review them against the legislation in force for
# the payroll periods you run before relying on generated filings. Countries that
# have no verified PAYE rule are listed in COUNTRIES_WITHOUT_PAYE and reported by
# `manage.py seed_country_rules`, and payroll for them carries a blocking
# compliance gap, so a missing band table is never silent.
PAYE_RULES = [
    # Nigeria: graduated personal income tax bands.
    dict(
        country_code='NG', code='paye', name='Personal income tax (PAYE)',
        rule_type='paye', calculation_method='progressive_bands', value=None,
        metadata={
            'bands': [
                {'upper': 800000, 'rate': '0'},
                {'upper': 3000000, 'rate': '15'},
                {'upper': 12000000, 'rate': '18'},
                {'upper': 25000000, 'rate': '21'},
                {'upper': 50000000, 'rate': '23'},
                {'upper': None, 'rate': '25'},
            ],
            'deductible_contribution_codes': ['pension'],
            # CRS reliefs and the minimum-earnings-tax relief are not modelled by
            # regional.paye; they must be applied upstream.
            'default_annual_relief': '0',
        },
        effective_from=date(2026, 1, 1),
        source_reference='https://www.firs.gov.ng/',
    ),
    # Ghana: GRA personal income tax bands -- DELIBERATELY NOT SEEDED.
    #
    # The version this file used to carry was 3,828 / 7,656 / 12,756 / 17,856 /
    # 24,356 / 34,056 / 52,288.5 / open at 37.5%, cited against
    # https://www.gra.gov.gh/. That table does not match the GRA scale. GRA's
    # Year of Assessment 2026 tables are:
    #
    #   monthly: 588 nil | 80 @5% | 100 @10% | 2,900 @17.5% |
    #             16,000 @25% | 30,332 @30% | above 50,000 @35%
    #   annual, from 1 Sept 2026: 7,056 nil | 960 @5% | 1,200 @10% |
    #             34,800 @17.5% | 192,000 @25% | 363,984 @30% | above 600,000 @35%
    #
    # The old table had a different band count, different thresholds
    # throughout, and a 37.5% top rate the current scale does not contain
    # (35% is the maximum). `regional.paye` annualises income before applying
    # bands, so these are read as annual figures and the error would have been
    # roughly an order of magnitude on most salaries.
    #
    # It is not seeded because two annual scales are in force during 2026 (the
    # pre-1-Sept one is 5,880 / +1,320 / +1,560 / +38,000 / +192,000 / +366,240,
    # per PwC), and which governs a given payroll period is a finance decision.
    # Until that is settled Ghana has no PAYE rule, so `paye_coverage_gap`
    # reports a blocking gap and payroll approval is refused rather than
    # computing a wrong number. Ghana is in COUNTRIES_WITHOUT_PAYE for this
    # reason.
]

# Supported countries with no PAYE band table defined yet. For these,
# `regional.paye.calculate_country_paye` returns None and
# `paye_coverage_gap` reports a BLOCKING compliance gap, which
# `payroll.views.ApprovePayrollRunView` refuses to approve past. The employer
# still gets numbers from their own configured brackets, but nothing presents
# those as statutory and the acknowledgement is recorded in the audit log.
#
# Keeping this list accurate is the whole safety property here: a country
# missing from it silently computes zero income tax.
COUNTRIES_WITHOUT_PAYE = [
    # Ghana: two annual scales are in force during 2026 and which governs a
    # given payroll period is a finance decision. See PAYE_RULES above.
    'GH',
    'SL', 'LR', 'GM',
    # The ten added 2026-10-01. No verified band table exists for any of them
    # yet. They are listed here so the command's warning below is truthful, and
    # so `regional.tests_seed_data.SeededDataCoversEveryPackTest` can assert
    # that a country shipping without statutory data is at least announced as
    # shipping without it. Each one raises a BLOCKING `paye_coverage_gap` on
    # every payslip until its bands are added and verified.
    'KE', 'TZ', 'UG', 'RW', 'ZM', 'ZW', 'BW', 'NA', 'ZA', 'EG',
    # The thirty-nine added 2026-10-02, completing all 54 UN member states of
    # Africa. Same situation as the ten above: the pack exists so a company can
    # be set up, and no band table has been verified for any of them, so each
    # raises a BLOCKING `paye_coverage_gap` rather than computing a zero.
    #
    # Listing a country here is a statement that it is blocked and unannounced,
    # not a claim that it works. `regional.W001` warns at startup if this list
    # and the seeded rules disagree.
    'AO', 'BF', 'BI', 'BJ', 'CD', 'CF', 'CG', 'CI', 'CM', 'CV', 'DJ', 'DZ',
    'ER', 'ET', 'GA', 'GN', 'GQ', 'GW', 'KM', 'LS', 'LY', 'MA', 'MG', 'ML',
    'MR', 'MU', 'MW', 'MZ', 'NE', 'SC', 'SD', 'SN', 'SO', 'SS', 'ST', 'SZ',
    'TD', 'TG', 'TN',
]

SUPPORTED_COUNTRIES = sorted({r['country_code'] for r in RULES} | {r['country_code'] for r in PAYE_RULES})


def _announced_unverified_paye():
    """Packs listed as unverified that the registry actually knows about.

    The warning is the only way an operator finds out a country will be blocked,
    so it must not be filtered down to countries that already have rule rows.
    The ten packs added on 2026-10-01 have *no* rows at all, so a filter like
    `if c in SUPPORTED_COUNTRIES` would have silently excluded every one of them
    - the exact countries the warning exists for.
    """
    from regional.countries.registry import COUNTRY_PACKS
    return [c for c in COUNTRIES_WITHOUT_PAYE if c in COUNTRY_PACKS]


class Command(BaseCommand):
    help = 'Seed authoritative baseline statutory contribution rules for supported countries.'
    def handle(self, *args, **options):
        for data in RULES + PAYE_RULES:
            lookup = {k:data[k] for k in ('country_code','code','effective_from')}
            obj, created = StatutoryRule.objects.update_or_create(defaults=data, **lookup)
            self.stdout.write(f"{'Created' if created else 'Updated'} {obj}")
        missing = _announced_unverified_paye()
        if missing:
            self.stdout.write(self.style.WARNING(
                'No verified PAYE band table seeded for: %s. Payroll for these '
                'countries records a BLOCKING compliance gap on every payslip and '
                'cannot be approved until statutory bands are added to PAYE_RULES '
                'and verified against the legislation in force. This is deliberate: '
                'an unverified band table is worse than a visible gap.'
                % ', '.join(missing)
            ))
        from regional.countries.registry import COUNTRY_PACKS
        from regional.engine import contribution_coverage_gap
        from django.utils import timezone
        today = timezone.localdate()
        unseeded_contributions = {
            code: pack.contribution_codes
            for code, pack in sorted(COUNTRY_PACKS.items())
            if (pack.contribution_codes or pack.contributions_unverified)
            and contribution_coverage_gap(code, today)
        }
        if unseeded_contributions:
            # The two groups need different remedies, so they are named apart
            # rather than in one list that reads as though every country had
            # known scheme names to add.
            named = '; '.join(
                f'{code} ({", ".join(pack.contribution_codes)})'
                for code, pack in sorted(COUNTRY_PACKS.items())
                if code in unseeded_contributions and pack.contribution_codes
            )
            unnamed = '; '.join(
                code
                for code, pack in sorted(COUNTRY_PACKS.items())
                if code in unseeded_contributions and not pack.contribution_codes
            )
            self.stdout.write(self.style.WARNING(
                'No verified contribution rule seeded for: %s. Each payslip in these '
                'countries records a BLOCKING compliance gap and cannot be approved '
                'until the rules are added to RULES and verified against the scheme '
                'in force. Also deliberate: a missing pension line is invisible on a '
                'payslip, whereas a wrong one is a misstatement of an employee\'s '
                'entitlement.' % '; '.join(
                    x for x in (named, unnamed) if x
                )
            ))
            if unnamed:
                self.stdout.write(self.style.WARNING(
                    'For %s the scheme that collects contributions has not been '
                    'confirmed against the authority either, so the gap cannot name '
                    'it and you will have to confirm the fund with the authority '
                    'yourself. Do not treat a scheme name as obvious here.' % unnamed
                ))
