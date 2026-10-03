"""Overtime classification and amount arithmetic.

Extracted from `OvertimeEntryListCreateView.post`, which had the whole thing
inline: classify the day, look up the multiplier, divide the monthly salary by
the standard month, multiply. When attendance began feeding overtime, the same
six lines were needed in a second place, and a copy is a copy - the two paths
would agree only until one of them was edited.

Nothing here changes how an amount is calculated. The formula is the one that
was already in production, moved rather than rewritten.
"""
from datetime import date as date_cls
from decimal import Decimal

from .models import OvertimeEntry, OvertimeRule, PublicHoliday

# Statuses that can carry worked clock times. 'absent' and 'leave' never do,
# so they are skipped rather than treated as zero-hour days - a zero-hour day
# and a day nobody attended are different facts.
HOURLY_STATUSES = ('present', 'half_day')


def classify_day_type(company, work_date, override=None):
    """weekday / weekend / holiday, unless the caller says otherwise.

    An explicit override wins, which is what the manual entry form relies on:
    someone entering a Sunday shift may need it treated as a weekday, and the
    caller already knows that.
    """
    if override:
        return override
    if not work_date:
        return 'weekday'
    if not hasattr(work_date, 'weekday'):
        work_date = date_cls.fromisoformat(str(work_date))
    if PublicHoliday.objects.filter(company=company, date=work_date).exists():
        return 'holiday'
    return 'weekend' if work_date.weekday() >= 5 else 'weekday'


def multiplier_for(rule, day_type):
    return {
        'weekday': rule.weekday_multiplier,
        'weekend': rule.weekend_multiplier,
        'holiday': rule.holiday_multiplier,
    }.get(day_type, rule.weekday_multiplier)


def hourly_rate(employee, rule):
    """Monthly base salary expressed as an hourly rate."""
    if not rule.standard_hours_per_month:
        return Decimal('0')
    return employee.base_salary / rule.standard_hours_per_month


def overtime_amount(employee, rule, hours, day_type):
    hours = Decimal(str(hours))
    rate = hourly_rate(employee, rule)
    return (rate * hours * multiplier_for(rule, day_type)).quantize(Decimal('0.01'))


def overtime_hours_from_attendance(record, rule):
    """Hours worked beyond the standard day, or 0.

    `Attendance.worked_minutes` is total time on the clock; `OvertimeEntry.hours`
    is time to be paid at a premium multiplier. They are not the same quantity.
    Passing worked hours straight through would pay a whole ordinary day at 1.5x,
    so the standard day is subtracted first and only the remainder becomes
    overtime. Below the threshold the answer is zero, not a negative entry.
    """
    minutes = record.worked_minutes
    if not minutes:
        return Decimal('0')
    worked = Decimal(minutes) / Decimal(60)
    threshold = Decimal(str(rule.standard_hours_per_day))
    remainder = worked - threshold
    return remainder.quantize(Decimal('0.01')) if remainder > 0 else Decimal('0')


def sync_overtime_from_attendance(company, period_start, period_end, employee=None):
    """Create OvertimeEntry rows for attendance that ran past the standard day.

    Deliberately creates entries rather than changing how a payslip sums
    overtime. `services.py` already adds `OvertimeEntry.amount` into the payslip
    and links entries to the run at processing time; generating rows keeps that
    path - which carries the compliance tests - completely untouched, and leaves
    payroll something it can inspect, correct or delete. A wrong auto-entry is
    then one DELETE away, where a wrong payslip is a conversation.

    Idempotent by construction: a date that already has an OvertimeEntry is
    skipped. Without that, running the sync twice would pay the same overtime
    twice, and a sync endpoint that is only safe to call once is a trap.

    Returns a summary rather than the entries, so the caller can report what was
    skipped and why instead of quietly doing less than asked.
    """
    from attendance.models import Attendance

    rule, _ = OvertimeRule.objects.get_or_create(company=company)
    records = Attendance.objects.filter(
        employee__company=company,
        date__gte=period_start,
        date__lte=period_end,
        status__in=HOURLY_STATUSES,
        check_in__isnull=False,
        check_out__isnull=False,
    ).select_related('employee')
    if employee is not None:
        records = records.filter(employee=employee)

    existing = set(
        OvertimeEntry.objects.filter(
            company=company,
            employee__in=[r.employee_id for r in records],
            work_date__gte=period_start,
            work_date__lte=period_end,
        ).values_list('employee_id', 'work_date')
    )

    created, at_standard, already_present = [], 0, 0
    for record in records:
        if (record.employee_id, record.date) in existing:
            already_present += 1
            continue
        extra = overtime_hours_from_attendance(record, rule)
        if extra <= 0:
            at_standard += 1
            continue
        day_type = classify_day_type(company, record.date)
        amount = overtime_amount(record.employee, rule, extra, day_type)
        worked = Decimal(record.worked_minutes) / Decimal(60)
        entry = OvertimeEntry.objects.create(
            company=company,
            employee=record.employee,
            work_date=record.date,
            hours=extra,
            day_type=day_type,
            amount=amount,
            notes=(
                f'From attendance: {worked}h worked, '
                f'{rule.standard_hours_per_day}h standard'
            ),
        )
        created.append({
            'id': entry.id,
            'employee': record.employee.full_name,
            'work_date': str(record.date),
            'hours': str(extra),
            'day_type': day_type,
            'amount': str(amount),
        })

    return {
        'created': created,
        'created_count': len(created),
        'at_standard': at_standard,
        'already_present': already_present,
        'standard_hours_per_day': str(rule.standard_hours_per_day),
    }