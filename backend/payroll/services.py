"""
Payroll calculation engine.

Deliberately country-agnostic: every rule it applies (tax brackets,
statutory contribution rates, currency) comes from the company's own
PayrollConfig, filled in during onboarding. Adding support for a new
country never requires touching this file - only the data a company
enters for itself.
"""
from decimal import Decimal
from django.utils import timezone

from .absence import absence_deduction

class StatutoryCalculationService:
    """
    Service for calculating employee statutory contributions.
    Orchestrates the regional engine and handles fallbacks to company config.
    """
    @staticmethod
    def get_contributions(employee, gross, base_salary, payroll_config, as_of=None):
        as_of = as_of or timezone.localdate()
        
        # 1. Try Regional Engine (High Priority)
        regional_lines = []
        try:
            from regional.engine import calculate_statutory_contributions
            country_profile = getattr(employee.company, 'country_profile', None)
            if country_profile:
                regional_lines = calculate_statutory_contributions(
                    country_profile.country_code, gross, base_salary, as_of
                )
        except Exception as e:
            import logging
            logging.getLogger('payroll').error(f"Regional engine failure for {employee.id}: {e}")
            regional_lines = []

        if regional_lines:
            total_employee_share = sum((Decimal(item['employee_share']) for item in regional_lines), Decimal('0'))
            return {
                'total': total_employee_share,
                'lines': regional_lines,
                'source': 'regional_engine'
            }

        # 2. Fallback to Company PayrollConfig (Legacy/Custom)
        contribution_total = Decimal('0')
        contribution_lines = []
        for contribution in payroll_config.contributions.all():
            if contribution.is_percentage:
                employee_share = gross * (contribution.employee_rate / Decimal('100'))
                employer_share = gross * (contribution.employer_rate / Decimal('100'))
            else:
                employee_share = contribution.employee_rate
                employer_share = contribution.employer_rate
            contribution_total += employee_share
            contribution_lines.append({
                'name': contribution.name,
                'employee_share': str(employee_share),
                'employer_share': str(employer_share),
            })
            
        return {
            'total': contribution_total,
            'lines': contribution_lines,
            'source': 'company_config'
        }

def collect_compliance_gaps(run):
    """Every distinct compliance gap recorded across a run's payslips.

    Derived from the payslips rather than stored on the run, so the flag that
    blocks approval cannot drift from the breakdown the payslip actually shows.
    A run is only as trustworthy as its worst payslip, and one gap is worth one
    warning rather than one per employee.
    """
    seen = {}
    for breakdown in run.payslips.values_list('breakdown', flat=True):
        for gap in (breakdown or {}).get('compliance_gaps') or []:
            seen[(gap.get('code'), gap.get('as_of'))] = gap
    return list(seen.values())


def calculate_progressive_tax(taxable_amount, tax_brackets):

    """
    Applies progressive taxation: each bracket's rate only applies to
    the slice of income that falls within that bracket, not the whole
    amount. Mirrors how most African (and global) income tax systems
    work.
    """
    taxable_amount = max(Decimal('0'), Decimal(taxable_amount))
    total_tax = Decimal('0')
    remaining = taxable_amount

    for bracket in tax_brackets.order_by('min_amount'):
        if remaining <= 0:
            break

        bracket_min = bracket.min_amount
        bracket_max = bracket.max_amount
        bracket_size = (bracket_max - bracket_min) if bracket_max is not None else None

        amount_above_min = max(Decimal('0'), taxable_amount - bracket_min)
        if bracket_size is not None:
            taxed_in_bracket = min(amount_above_min, bracket_size)
        else:
            taxed_in_bracket = amount_above_min

        if taxed_in_bracket > 0:
            total_tax += taxed_in_bracket * (bracket.rate / Decimal('100'))
            remaining -= taxed_in_bracket

    return total_tax.quantize(Decimal('0.01'))


def calculate_payslip(employee, payroll_config, payroll_run=None):
    """
    Computes gross -> tax -> statutory contributions -> other deductions
    -> net for a single employee, and returns a dict ready to build a
    Payslip instance, including a line-item breakdown.

    Includes unpaid overtime in the period, approved leave encashments
    not yet paid, and salary-advance recoveries. Tax and employee
    statutory contributions are computed on taxable gross (base +
    allowances + overtime + encashment).
    """
    base_salary = employee.base_salary

    allowance_total = Decimal('0')
    allowance_lines = []
    for allowance in employee.allowances.all():
        amount = (
            base_salary * (allowance.amount / Decimal('100'))
            if allowance.is_percentage_of_base
            else allowance.amount
        )
        allowance_total += amount
        allowance_lines.append({'name': allowance.name, 'amount': str(amount)})

    period_start = getattr(payroll_run, 'period_start', None) if payroll_run else None
    period_end = getattr(payroll_run, 'period_end', None) if payroll_run else None

    # Overtime not yet linked to a run (optionally scoped to period)
    overtime_total = Decimal('0')
    overtime_lines = []
    ot_qs = employee.overtime_entries.filter(payroll_run__isnull=True)
    if period_start and period_end:
        ot_qs = ot_qs.filter(work_date__gte=period_start, work_date__lte=period_end)
    ot_ids = list(ot_qs.values_list('id', flat=True))
    for entry in ot_qs:
        overtime_total += entry.amount or Decimal('0')
        overtime_lines.append({
            'date': str(entry.work_date),
            'hours': str(entry.hours),
            'day_type': entry.day_type,
            'amount': str(entry.amount),
        })

    # Approved leave encashments not yet paid through payroll
    encash_total = Decimal('0')
    encash_lines = []
    encash_ids = []
    try:
        from leave.models import LeaveEncashment
        encash_qs = LeaveEncashment.objects.filter(
            employee=employee, status='approved',
        )
        for enc in encash_qs:
            encash_total += enc.amount or Decimal('0')
            encash_lines.append({
                'id': enc.id,
                'leave_type': enc.leave_type,
                'days': str(enc.days),
                'amount': str(enc.amount),
            })
            encash_ids.append(enc.id)
    except Exception:
        pass

    taxable_gross = base_salary + allowance_total + overtime_total + encash_total

    # 1. Calculate Statutory Contributions (using new service)
    statutory = StatutoryCalculationService.get_contributions(
        employee, taxable_gross, base_salary, payroll_config, as_of=period_end
    )
    contribution_total = statutory['total']
    contribution_lines = statutory['lines']

    # 2. Calculate Tax (PAYE)
    #
    # There are three possible outcomes here, and the middle one used to be
    # invisible: a statutory rule exists, no statutory rule exists, or the
    # statutory engine itself raised. Only the first is trustworthy. The other
    # two both collapsed into a silent zero through a bare `except Exception`,
    # so a supported country with no tax table - or a rule that blew up - paided
    # out a normal-looking payslip that quietly under-withheld income tax. A
    # zero tax line is indistinguishable from a correct one, which is exactly
    # why this has to be recorded rather than inferred.
    tax_amount = Decimal('0')
    paye_result = None
    tax_compliance_gap = None
    # The contribution twin of the tax gap. Deliberately OUTSIDE the
    # `tax_calculation_enabled` branch: a company that has not turned on
    # statutory tax is still deducting pension and social security, and a
    # missing rule for those is just as much an undeclared omission. Putting it
    # inside would have meant a company with statutory tax off got no guard on
    # the deductions its employees actually lose money from.
    contribution_gaps = []
    _profile = getattr(employee.company, 'country_profile', None)
    if _profile:
        from regional.engine import contribution_coverage_gap
        contribution_gaps = contribution_coverage_gap(
            _profile.country_code, period_end or timezone.localdate()
        )
    if payroll_config.tax_calculation_enabled:
        from regional.paye import calculate_country_paye, paye_coverage_gap
        country_profile = getattr(employee.company, 'country_profile', None)
        as_of = period_end or timezone.localdate()
        if country_profile:
            # Use the same service to get contributions for tax deduction logic
            regional_for_tax = statutory['lines'] if statutory['source'] == 'regional_engine' else []
            try:
                paye_result = calculate_country_paye(
                    country_profile.country_code,
                    taxable_gross,
                    base_salary,
                    as_of,
                    frequency=getattr(payroll_config, 'pay_frequency', 'monthly'),
                    deductible_contributions=regional_for_tax,
                )
            except Exception as exc:
                # An engine failure is not the same fact as an absent rule, but
                # it has the same consequence for the payslip, so it is reported
                # the same way instead of disappearing into a fallback.
                paye_result = None
                tax_compliance_gap = paye_coverage_gap(
                    country_profile.country_code, as_of,
                    cause='engine_error', detail=str(exc)[:300],
                )
            if paye_result is None and tax_compliance_gap is None:
                tax_compliance_gap = paye_coverage_gap(country_profile.country_code, as_of)
        if paye_result is not None:
            tax_amount = Decimal(paye_result['period_tax'])
        else:
            # Either no country rules apply (the company configured its own
            # brackets, which is fine) or we could not verify them. The numbers
            # are produced either way so the run stays usable, but the second
            # case now carries a gap that blocks approval until acknowledged.
            tax_amount = calculate_progressive_tax(taxable_gross, payroll_config.tax_brackets)

    other_deduction_total = Decimal('0')
    deduction_lines = []
    for deduction in employee.deductions.all():
        amount = (
            base_salary * (deduction.amount / Decimal('100'))
            if deduction.is_percentage_of_base
            else deduction.amount
        )
        other_deduction_total += amount
        deduction_lines.append({'name': deduction.name, 'amount': str(amount)})

    # Salary advance recoveries (open / partial)
    advance_total = Decimal('0')
    advance_lines = []
    advance_plan = []
    for adv in employee.salary_advances.filter(status__in=['open', 'partial']).order_by('granted_on'):
        if adv.remaining <= 0:
            continue
        take = min(adv.installment_amount, adv.remaining)
        if take <= 0:
            continue
        advance_total += take
        advance_lines.append({
            'advance_id': adv.id,
            'amount': str(take),
            'remaining_before': str(adv.remaining),
        })
        advance_plan.append((adv.id, take))

    # Unpaid absence. Opt-in per company and off by default; see
    # payroll/absence.py for the rules and for everything it declines to deduct.
    absence_total = Decimal('0')
    absence_lines = []
    if getattr(payroll_config, 'deduct_unpaid_absence', False):
        absence_total, absence_lines = absence_deduction(
            employee, period_start, period_end,
        )

    net_salary = (
        taxable_gross - tax_amount - contribution_total
        - other_deduction_total - advance_total - absence_total
    )

    # Assembled here, after the tax branch above, because `tax_compliance_gap` is
    # assigned inside it. Building this list earlier silently dropped the tax
    # gap while keeping the contribution one, which is the worst possible
    # outcome for a guard: the more visible failure disappears and the less
    # visible one carries on.
    compliance_gaps = ([tax_compliance_gap] if tax_compliance_gap else []) + contribution_gaps

    return {
        'base_salary': base_salary,
        'total_allowances': allowance_total + overtime_total + encash_total,
        'gross_salary': taxable_gross,
        'tax_amount': tax_amount,
        'total_contributions': contribution_total,
        'total_other_deductions': other_deduction_total + advance_total + absence_total,
        'net_salary': net_salary,
        'breakdown': {
            'currency': payroll_config.currency,
            'allowances': allowance_lines,
            'overtime': overtime_lines,
            'leave_encashments': encash_lines,
            'statutory_contributions': contribution_lines,
            'paye': paye_result,
            'compliance_gaps': compliance_gaps,
            'other_deductions': deduction_lines,
            'unpaid_absence': absence_lines,
            'advance_recoveries': advance_lines,
            '_advance_plan': advance_plan,
            '_overtime_entry_ids': ot_ids,
            '_encashment_ids': encash_ids,
        },
    }
