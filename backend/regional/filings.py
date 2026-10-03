"""Country statutory filing calendar and payroll-period aggregation helpers."""
from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.utils import timezone


def next_month(year, month):
    return (year + 1, 1) if month == 12 else (year, month + 1)


def due_date_for_rule(rule, period_end):
    """Calculate a filing due date from an effective-dated filing rule."""
    if rule.frequency == 'monthly':
        year, month = next_month(period_end.year, period_end.month)
        day = min(rule.due_day or 28, monthrange(year, month)[1])
        return date(year, month, day)
    if rule.frequency == 'annual':
        month = rule.due_month or 1
        day = min(rule.due_day or 31, monthrange(period_end.year + 1, month)[1])
        return date(period_end.year + 1, month, day)
    raise ValueError(f'Unsupported filing frequency: {rule.frequency}')


def filing_status(due_date, filed_at=None):
    if filed_at:
        return 'filed'
    today = timezone.localdate()
    return 'overdue' if due_date < today else 'open'


def aggregate_payroll_for_filing(payroll_run):
    """Return a generic, reviewable statutory aggregate from payslip breakdowns."""
    totals = {}
    for payslip in payroll_run.payslips.select_related('employee', 'employee__statutory_profile').all():
        breakdown = payslip.breakdown or {}
        lines = breakdown.get('statutory_contributions') or []
        for line in lines:
            code = line.get('code') or line.get('name') or 'statutory'
            bucket = totals.setdefault(code, {
                'code': code,
                'name': line.get('name') or code,
                'employee_share': Decimal('0'),
                'employer_share': Decimal('0'),
                'employee_count': 0,
                '_employee_ids': set(),
            })
            bucket['employee_share'] += Decimal(str(line.get('employee_share', '0')))
            bucket['employer_share'] += Decimal(str(line.get('employer_share', '0')))
            bucket['_employee_ids'].add(payslip.employee_id)
    result = []
    for value in totals.values():
        value['employee_share'] = str(value['employee_share'].quantize(Decimal('0.01')))
        value['employer_share'] = str(value['employer_share'].quantize(Decimal('0.01')))
        value['employee_count'] = len(value.pop('_employee_ids'))
        result.append(value)
    return result
