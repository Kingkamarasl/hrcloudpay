"""Deducting pay for unpaid absence.

This is opt-in per company and off by default, which is the whole design. Every
rule here is biased towards *not* deducting, because the two failure modes are
not symmetric:

- not deducting an absence costs the employer a few days' pay
- deducting a day someone was legitimately entitled to costs an employee money,
  is a wage-law question, and is the kind of error that surfaces as a tribunal
  claim rather than a bug report

So a day is only deducted when every one of these is positively established:

- the company has opted in
- attendance says `absent` (or `leave` under an approved *unpaid* leave
  request - paid leave types are never deducted)
- no approved LeaveRequest covers that date. There is no linkage between
  attendance and leave anywhere in this codebase, so a manager can easily mark
  a day absent that an approved request already covers. Without this check the
  most likely outcome of enabling this is a payroll that double-penalises
  someone for leave they were granted.
- it is not a public holiday - you cannot be absent from a non-working day
- it is not a weekend

The daily rate is base salary divided by the weekdays in the period. That
varies by month, which is correct for a monthly salary, and needs no extra
configuration. A company working a six-day week would want this configurable;
that is a follow-up, not a guess.
"""
from datetime import timedelta
from decimal import Decimal

WEEKEND_DAYS = {5, 6}  # Saturday, Sunday - matching OvertimeEntry's weekday() >= 5


def weekdays_in_period(period_start, period_end):
    """How many Mon-Fri days the period covers.

    Counts the whole span rather than using a configured constant, so February
    and a five-week month both produce a sane daily rate.
    """
    if not period_start or not period_end or period_end < period_start:
        return 0
    return sum(
        1
        for offset in range((period_end - period_start).days + 1)
        if (period_start + timedelta(days=offset)).weekday() not in WEEKEND_DAYS
    )


def unpaid_absence_days(employee, period_start, period_end):
    """Attendance dates in the period that should be treated as unpaid.

    Returns a list of dates, so the caller can put them on the payslip as
    individual lines - a payslip that says "absence: -120,000" with no dates
    on it is not something anyone can check.
    """
    from attendance.models import Attendance
    from leave.models import LeaveRequest
    from payroll.models import PublicHoliday

    if not period_start or not period_end:
        return []

    records = Attendance.objects.filter(
        employee=employee,
        date__gte=period_start,
        date__lte=period_end,
    )
    if not records.exists():
        return []

    approved = list(
        LeaveRequest.objects.filter(
            employee=employee,
            status='approved',
            start_date__lte=period_end,
            end_date__gte=period_start,
        ).values_list('start_date', 'end_date', 'leave_type')
    )
    holidays = set(
        PublicHoliday.objects.filter(
            company=employee.company,
            date__gte=period_start,
            date__lte=period_end,
        ).values_list('date', flat=True)
    )

    def covering_leave(day):
        for start, end, _leave_type in approved:
            if start <= day <= end:
                return _leave_type
        return None

    deductible = []
    for record in records:
        day = record.date
        if day.weekday() in WEEKEND_DAYS or day in holidays:
            continue
        leave_type = covering_leave(day)
        if record.status == 'absent':
            # Absent with no approved leave behind it. With one behind it, the
            # employee was there by arrangement and the manager's mark is the
            # thing that is wrong.
            if leave_type is None:
                deductible.append(day)
        elif record.status == 'leave':
            if leave_type == 'unpaid':
                deductible.append(day)
    # Attendance.Meta.ordering is ['-date'], so the queryset arrives
    # newest-first. A payslip listing absences reads chronologically.
    return sorted(deductible)


def absence_deduction(employee, period_start, period_end):
    """(total, lines) for this employee, capped at the base salary.

    The cap matters: an absence deduction larger than the salary itself would
    produce a payslip that is nonsense on its face, and no amount of unpaid
    absence justifies paying a negative wage out of a monthly salary.
    """
    days = unpaid_absence_days(employee, period_start, period_end)
    if not days:
        return Decimal('0'), []

    working = weekdays_in_period(period_start, period_end)
    if not working:
        return Decimal('0'), []

    daily = (employee.base_salary / Decimal(working)).quantize(Decimal('0.01'))
    lines = [{'date': str(d), 'daily_rate': str(daily)} for d in days]
    total = daily * len(days)

    if total > employee.base_salary:
        total = employee.base_salary.quantize(Decimal('0.01'))
    return total.quantize(Decimal('0.01')), lines