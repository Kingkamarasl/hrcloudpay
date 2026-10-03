"""Country statutory rule evaluation.

Rules are effective-dated database records.  The engine intentionally keeps
calculation mechanics separate from country data so historical payroll can
continue to use the rule set that was effective for its pay period.
"""
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Q

CENT = Decimal('0.01')


def money(value):
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def active_rules(country_code, as_of, codes=None):
    from .models import StatutoryRule
    qs = StatutoryRule.objects.filter(
        country_code=country_code,
        effective_from__lte=as_of,
        is_active=True,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=as_of))
    if codes:
        qs = qs.filter(code__in=codes)
    return qs.order_by('code', '-effective_from')


def rule_value(rule, basis):
    method = (rule.calculation_method or 'percentage').lower()
    value = Decimal(rule.value or 0)
    meta = rule.metadata or {}
    if method == 'percentage':
        amount = basis * value / Decimal('100')
    elif method == 'flat':
        amount = value
    elif method == 'percentage_capped':
        cap = Decimal(meta.get('cap', '0'))
        amount = basis * value / Decimal('100')
        if cap > 0:
            amount = min(amount, cap)
    elif method == 'percentage_on_capped_basis':
        ceiling = Decimal(meta.get('ceiling', '0'))
        capped_basis = min(basis, ceiling) if ceiling > 0 else basis
        amount = capped_basis * value / Decimal('100')
    else:
        raise ValueError(f'Unsupported statutory calculation method: {method}')
    return money(amount)


def calculate_statutory_contributions(country_code, gross, base_salary, as_of):
    """Return employee/employer statutory contributions for a country/date."""
    result = []
    for rule in active_rules(country_code, as_of):
        if rule.rule_type != 'contribution':
            continue
        meta = rule.metadata or {}
        basis_name = meta.get('basis', 'gross')
        basis = base_salary if basis_name == 'basic' else gross
        employee_rate = Decimal(meta.get('employee_rate', rule.value or 0))
        employer_rate = Decimal(meta.get('employer_rate', 0))
        employee_method = meta.get('employee_method', rule.calculation_method or 'percentage')
        employer_method = meta.get('employer_method', rule.calculation_method or 'percentage')
        employee_rule = type('Rule', (), {'value': employee_rate, 'metadata': meta, 'calculation_method': employee_method})
        employer_rule = type('Rule', (), {'value': employer_rate, 'metadata': meta, 'calculation_method': employer_method})
        employee_share = rule_value(employee_rule, basis) if employee_rate else Decimal('0.00')
        employer_share = rule_value(employer_rule, basis) if employer_rate else Decimal('0.00')
        result.append({
            'code': rule.code,
            'name': rule.name,
            'employee_share': str(employee_share),
            'employer_share': str(employer_share),
            'basis': str(money(basis)),
            'source_reference': rule.source_reference,
        })
    return result


def contribution_coverage_gap(country_code, as_of):
    """Which of a country's expected contribution rules are missing, if any.

    This is the pension/social-security twin of `paye.paye_coverage_gap`, and it
    exists because that guard had no counterpart.

    `calculate_statutory_contributions` filters whatever rules exist and returns
    a list. For a country in `COUNTRY_PACKS` with no seeded rows, that list is
    empty - so no pension line, no social security line, and no employer cost,
    and the payslip reads as though the country simply has no such scheme. The
    employee sees a take-home pay figure with their retirement deduction absent
    and has no way to tell the difference from a correctly-computed payslip.

    That is the same defect as the unverified-income-tax one, and it is worse on
    one axis: an employee who does not know a deduction was missed will not
    notice, whereas a missing tax line is at least visible as a large gross-to-net
    difference. The obligation is also the employee's own money held by the
    employer, not a payment to a revenue authority, so the loss does not surface
    as a penalty either.

    Two cases are deliberately NOT gaps:

    * a country outside `COUNTRY_PACKS` - HRCloudPay does not claim to support
      it, so an empty contribution list is the expected state, exactly as in
      `paye_coverage_gap`;
    * a country whose pack declares neither `contribution_codes` nor
      `contributions_unverified` - the pack makes no promise to deduct anything,
      so there is nothing to have failed.

    A pack that sets `contributions_unverified` is a third case, and it does
    raise a gap. The country requires contributions, HRCloudPay deducts none,
    and the scheme name has not been confirmed. Reporting that as a gap is what
    keeps the omission visible. The `cause` distinguishes it
    (`scheme_name_unconfirmed` rather than `no_active_rule`) so an approver can
    see that the missing piece is the name, not the arithmetic, and `missing_codes`
    is empty because no scheme has been positively identified.

    Returns a list of gap dicts, one per missing code, so the approver and the
    auditor are told which specific scheme was not deducted rather than just
    that "something was".
    """
    from .countries.registry import COUNTRY_PACKS

    pack = COUNTRY_PACKS.get((country_code or '').upper())
    if pack is None:
        return []
    if not pack.contribution_codes:
        if not pack.contributions_unverified:
            return []
        return [{
            'code': 'statutory_contribution_unavailable',
            'severity': 'blocking',
            'country_code': pack.code,
            'country_name': pack.name,
            'as_of': str(as_of),
            'cause': 'scheme_name_unconfirmed',
            # No scheme has been positively identified, so no code is claimed.
            # Guessing one here would put a wrong fund name in front of a
            # payroll officer, which is a worse failure than an incomplete
            # message - Burundi and DR Congo are in this state because sources
            # disagree on the name of the collecting body.
            'missing_codes': [],
            'message': (
                f'{pack.name} requires mandatory employer and employee social '
                f'security contributions, and HRCloudPay deducted none for {as_of}: '
                f'no contribution rule is seeded for this country. HRCloudPay has '
                f'also not confirmed the name of the scheme that collects them, so '
                f'this gap does not tell you which authority to pay. The obligation '
                f'is real and unmet - it is the employee\'s own money held by the '
                f'employer - so confirm the scheme with the authority before treating '
                f'the run as final.'
            ),
        }]
    present = {
        rule.code for rule in active_rules(pack.code, as_of)
        if rule.rule_type == 'contribution'
    }
    missing = [code for code in pack.contribution_codes if code not in present]
    if not missing:
        return []
    names = ', '.join(missing)
    plural = 'schemes' if len(missing) > 1 else 'scheme'
    return [{
        'code': 'statutory_contribution_unavailable',
        'severity': 'blocking',
        'country_code': pack.code,
        'country_name': pack.name,
        'as_of': str(as_of),
        'cause': 'no_active_rule',
        'missing_codes': missing,
        'message': (
            f'HRCloudPay has no verified {pack.name} contribution rule effective '
            f'for {as_of} for {names}, so {names} {"were" if len(missing) > 1 else "was"} '
            f'not deducted from this payslip. The {"statutory contributions are" if len(missing) > 1 else "statutory contribution is"} '
            f'owed and {"have" if len(missing) > 1 else "has"} not been calculated. '
            f'Add {"these" if len(missing) > 1 else "this"} {plural} to the seeded '
            f'rules, verified against the scheme in force, before treating the '
            f'run as final.'
        ),
    }]
