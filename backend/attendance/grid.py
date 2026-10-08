"""A month of attendance per employee, shaped for a calendar grid.

Why this exists
---------------
The only way to read attendance was a flat list, which stops being readable at
about two weeks of history. A month grid - one row per employee, one column per
day - answers "who was late this month" at a glance, and it is the view most HR
tools lead with because it is the one people actually use.

Derived statuses, not stored ones
---------------------------------
Late, early departure and overtime are computed here from `check_in` and
`check_out` against the day's expected hours. They are deliberately *not* new
status values:

- `status` feeds payroll. `half_day` already scales pay, and adding values to
  that field changes what every existing pay run means. A late arrival that
  crosses no threshold should not silently become a pay-affecting status.
- Storing a derived value duplicates a fact that check_in/check_out already
  state, and the copy goes stale the moment someone corrects a time.
- Recomputing is cheap and always right for the data as it stands now.

So the stored vocabulary stays exactly as it was - present, absent, half_day,
leave - and these three are presentation. A day can be both present and late,
which the grid shows as a present tick with a late marker beside it, and a total
can disagree with a headcount because they answer different questions.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

# Expected hours in a day, used to decide what "late" and "overtime" mean.
# Overridable per request; this is the default rather than a constant because a
# shift pattern is not universal and the alternative is a hardcoded answer to a
# question every company answers differently.
DEFAULT_EXPECTED_HOURS = 8.0

# How long after the shift start counts as late. Zero by default: arriving at the
# hour is on time, and inventing a grace period here would quietly change what
# the grid says without telling anyone it had.
DEFAULT_GRACE_MINUTES = 0

STATUS_LABELS = {
    'present': 'Present',
    'absent': 'Absent',
    'half_day': 'Half Day',
    'leave': 'On Leave',
    'weekend': 'Weekend',
    'not_added': 'Not Added',
    'holiday': 'Holiday',
}


@dataclass(frozen=True)
class GridDay:
    date: date
    status: str | None
    late_minutes: int = 0
    early_minutes: int = 0
    overtime_minutes: int = 0
    check_in: str | None = None
    check_out: str | None = None

    def as_dict(self):
        payload = {
            'date': self.date.isoformat(),
            'status': self.status or 'not_added',
        }
        if self.late_minutes:
            payload['late_minutes'] = self.late_minutes
        if self.early_minutes:
            payload['early_minutes'] = self.early_minutes
        if self.overtime_minutes:
            payload['overtime_minutes'] = self.overtime_minutes
        if self.check_in:
            payload['check_in'] = self.check_in
        if self.check_out:
            payload['check_out'] = self.check_out
        return payload


def month_bounds(year: int, month: int):
    """First and last day of a month.

    `calendar.monthrange` rather than constructing a date and adding a month:
    adding a month to the 31st of a short month lands in the wrong month, and
    this is a function a calendar UI will call for every month it displays.
    """
    days = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, days)


def _minutes(value):
    return value.hour * 60 + value.minute if value is not None else None


def day_cells(start: date, end: date, records: dict, *, expected_hours: float,
               grace_minutes: int) -> list:
    """Every day in the range, with its status and derived timings.

    Missing days are emitted as `not_added` rather than omitted. A calendar grid
    with holes reads as missing data when it means "nobody was marked", and an
    HR person scanning for unmarked people needs the hole drawn to find it.
    """
    expected = expected_hours * 60
    shift_start_minutes = 9 * 60  # 09:00, the conventional start
    cells = []
    cursor = start
    while cursor <= end:
        record = records.get(cursor.isoformat())
        if record is None:
            status = 'weekend' if cursor.weekday() >= 5 else 'not_added'
            cells.append(GridDay(date=cursor, status=status))
            cursor += timedelta(days=1)
            continue

        status = record.status
        in_min = _minutes(record.check_in)
        out_min = _minutes(record.check_out)
        late = early = overtime = 0

        if status == 'present' and in_min is not None:
            late = max(0, in_min - shift_start_minutes - grace_minutes)
        if status in ('present', 'half_day') and out_min is not None and expected:
            worked = out_min - in_min if in_min is not None else 0
            # Only ever derived from a real end time. A missing checkout means
            # an open shift, and guessing an early departure from it invents a
            # disciplinary record nobody entered.
            if worked > 0:
                early = max(0, expected - worked) if status == 'present' else 0
                overtime = max(0, worked - expected) if status == 'present' else 0

        cells.append(GridDay(
            date=cursor, status=status, late_minutes=late, early_minutes=early,
            overtime_minutes=overtime,
            check_in=record.check_in.strftime('%H:%M') if record.check_in else None,
            check_out=record.check_out.strftime('%H:%M') if record.check_out else None,
        ))
        cursor += timedelta(days=1)
    return cells


def summarise(cells: list) -> dict:
    """Per-employee totals for the month.

    Worked days and expected days are reported separately rather than as a
    percentage, because "18/21" is a fact and "86%" invites the reading that six
    absences happened, when some of those days were weekends the employee was
    never expected to work.
    """
    counts = {}
    expected_days = 0
    worked_days = 0
    for cell in cells:
        # By date, not by status. A Saturday somebody actually worked is not a
        # day they were expected to work, so it must not inflate the expected
        # count - but judging the weekend by `status` treats it as a weekday
        # precisely because a record exists, which is the case where being
        # fussy about it matters. It still counts as worked.
        if cell.date.weekday() >= 5 and cell.status != 'present':
            continue
        expected_days += 1
        if cell.status is None:
            continue
        counts[cell.status] = counts.get(cell.status, 0) + 1
        if cell.status in ('present', 'half_day'):
            worked_days += 1

    return {
        'counts': counts,
        'expected_days': expected_days,
        'worked_days': worked_days,
        'late_days': sum(1 for c in cells if c.late_minutes),
        'overtime_minutes': sum(c.overtime_minutes for c in cells),
        'worked_ratio': f'{worked_days}/{expected_days}' if expected_days else '0/0',
    }