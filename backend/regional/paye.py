"""Country PAYE engines for HRCloudPay's country packs.

The engine is data-driven and effective-dated. Rates/bands live in
StatutoryRule rows so historical payroll can use the rules effective on its
pay-period end date. This module intentionally does not guess at reliefs
that HRCloudPay does not yet capture in an employee record.
"""
from decimal import Decimal, ROUND_HALF_UP
from .engine import active_rules, money, calculate_statutory_contributions
from .countries.registry import COUNTRY_PACKS


def _progressive(amount, bands):
    amount = max(Decimal('0'), Decimal(amount or 0))
    tax = Decimal('0')
    lower = Decimal('0')
    for upper, rate in bands:
        if amount <= lower:
            break
        if upper is None:
            slice_amount = amount - lower
        else:
            upper = Decimal(str(upper))
            slice_amount = min(amount, upper) - lower
        if slice_amount > 0:
            tax += slice_amount * Decimal(str(rate)) / Decimal('100')
        if upper is None:
            break
        lower = upper
    return money(tax)


def _rule(country_code, as_of):
    rules = list(active_rules(country_code, as_of))
    for rule in rules:
        if rule.rule_type == 'paye':
            return rule
    return None


def paye_coverage_gap(country_code, as_of, cause='no_active_rule', detail=''):
    """Describe an inability to compute statutory PAYE, or return None.

    This exists because "no rule" and "the engine raised" both used to end in
    the same place: a payslip with income tax of zero and nothing on screen
    saying why. For a company whose country HRCloudPay *claims to support*, that
    is a compliance failure wearing a normal-looking payslip, and it is the
    failure mode most likely to be missed, because a zero tax line looks like a
    legitimate tax line.

    The distinction that matters is whether the country is one of the packs
    HRCloudPay sells:

    * a supported pack with no active rule is a gap we own - the product
      promises this jurisdiction and cannot compute it;
    * a country outside `COUNTRY_PACKS` is not a gap at all. Absence of a
      statutory rule is the expected state there, and the company is running
      its own configured brackets, which is a legitimate manual setup.

    So this returns None for the second case and never blocks a company for a
    jurisdiction we do not claim.
    """
    # The rule-exists check is conditional on the cause, and that distinction is
    # the whole point of the function. An absent rule is only a gap when there
    # is no rule to find; an engine failure is a gap *even when a perfectly good
    # rule exists*, because that rule exists and still did not produce a number.
    # Gating both on `_rule()` made the most important failure - a rule that
    # raises - the one failure that stayed silent.
    if cause != 'engine_error' and _rule(country_code, as_of) is not None:
        return None
    pack = COUNTRY_PACKS.get((country_code or '').upper())
    if pack is None:
        return None
    if cause == 'engine_error':
        message = (
            f'HRCloudPay could not apply the {pack.name} income tax rule effective '
            f'for {as_of}, so payroll tax fell back to this payroll\'s own tax '
            f'brackets and has not been checked against statute.'
        )
    else:
        message = (
            f'HRCloudPay has no verified {pack.name} income tax rule effective for '
            f'{as_of}, so payroll tax fell back to this payroll\'s own tax brackets '
            f'and has not been checked against statute.'
        )
    return {
        'code': 'statutory_paye_unavailable',
        'severity': 'blocking',
        'country_code': pack.code,
        'country_name': pack.name,
        'as_of': str(as_of),
        'cause': cause,
        'detail': detail,
        'message': message,
    }


def calculate_country_paye(country_code, gross, basic_salary, as_of, frequency='monthly',
                           deductible_contributions=None, extra_taxable_income=Decimal('0')):
    """Calculate PAYE using the active country PAYE rule.

    Returns a transparent result with annualized income, deductions, taxable
    income, annual tax and period tax.  The first release supports monthly,
    biweekly and weekly payroll by annualizing the period amount.
    """
    rule = _rule(country_code, as_of)
    if not rule:
        return None

    meta = rule.metadata or {}
    periods = {'monthly': Decimal('12'), 'biweekly': Decimal('26'), 'weekly': Decimal('52')}
    periods_per_year = periods.get(frequency, Decimal('12'))
    gross = Decimal(gross or 0)
    basic_salary = Decimal(basic_salary or 0)
    annual_gross = gross * periods_per_year
    annual_extra = Decimal(extra_taxable_income or 0)

    deductions = Decimal('0')
    deduction_lines = []
    deductible_codes = set(meta.get('deductible_contribution_codes', []))
    if deductible_contributions and deductible_codes:
        for line in deductible_contributions:
            if line.get('code') in deductible_codes:
                amount = Decimal(line.get('employee_share', '0'))
                annual_amount = amount * periods_per_year
                deductions += annual_amount
                deduction_lines.append({'code': line.get('code'), 'amount': str(money(amount))})

    # Explicit annual reliefs supplied by a future/self-service tax profile.
    annual_reliefs = Decimal(meta.get('default_annual_relief', '0'))
    taxable_annual = max(Decimal('0'), annual_gross + annual_extra - deductions - annual_reliefs)

    bands = [(b.get('upper'), b.get('rate')) for b in meta.get('bands', [])]
    annual_tax = _progressive(taxable_annual, bands)
    period_tax = money(annual_tax / periods_per_year)

    return {
        'country_code': country_code,
        'rule_code': rule.code,
        'source_reference': rule.source_reference,
        'frequency': frequency,
        'gross': str(money(gross)),
        'annualized_gross': str(money(annual_gross)),
        'employee_deductions': deduction_lines,
        'annual_deductions': str(money(deductions)),
        'annual_reliefs': str(money(annual_reliefs)),
        'annual_taxable_income': str(money(taxable_annual)),
        'annual_tax': str(money(annual_tax)),
        'period_tax': str(period_tax),
    }
