"""The attendance month grid, and the statuses derived for it.

Two properties are worth more than the grid rendering:

**Derived statuses must not touch `status`.** That field feeds payroll, and
`half_day` already scales pay. Late, early departure and overtime are computed
here and nowhere else - storing them would duplicate a fact check_in/check_out
already state, and a duplicate goes stale the moment someone corrects a time.

**A missing day must be drawn.** A grid that omits unmarked days reads as missing
data when it means "nobody marked this", and the person scanning for unmarked
days needs the gap visible to find it.
"""
from datetime import date, time
from types import SimpleNamespace

from django.test import TestCase

from attendance.grid import (
    DEFAULT_EXPECTED_HOURS,
    STATUS_LABELS,
    day_cells,
    month_bounds,
    summarise,
)


def record(status='present', check_in=None, check_out=None):
    return SimpleNamespace(status=status, check_in=check_in, check_out=check_out)


def build(records, year=2026, month=8, expected=DEFAULT_EXPECTED_HOURS):
    start, end = month_bounds(year, month)
    return day_cells(start, end, records, expected_hours=expected, grace_minutes=0)


class MonthBoundsTests(TestCase):
    def test_a_short_month_ends_on_the_28th(self):
        """Adding a month to a date lands in the wrong month; this must not."""
        start, end = month_bounds(2026, 2)

        self.assertEqual(start, date(2026, 2, 1))
        self.assertEqual(end, date(2026, 2, 28))

    def test_a_leap_february_ends_on_the_29th(self):
        _, end = month_bounds(2028, 2)

        self.assertEqual(end, date(2028, 2, 29))

    def test_every_month_produces_a_whole_month_of_days(self):
        for month in range(1, 13):
            start, end = month_bounds(2026, month)
            expected = [start.day for _ in range(0)]
            self.assertEqual((end - start).days + 1, len(expected) + self._days(month))

    @staticmethod
    def _days(month):
        import calendar

        return calendar.monthrange(2026, month)[1]


class DerivedStatusTests(TestCase):
    """Late, early departure and overtime - computed, never stored."""

    def test_a_punctual_day_has_no_derived_flags(self):
        cells = build({'2026-08-03': record('present', time(9, 0), time(17, 0))})

        cell = cells[2]
        self.assertEqual(cell.late_minutes, 0)
        self.assertEqual(cell.early_minutes, 0)
        self.assertEqual(cell.overtime_minutes, 0)

    def test_arriving_late_is_reported_in_minutes(self):
        cells = build({'2026-08-03': record('present', time(9, 45), time(17, 0))})

        self.assertEqual(cells[2].late_minutes, 45)

    def test_leaving_early_is_reported(self):
        cells = build({'2026-08-03': record('present', time(9, 0), time(15, 0))})

        # 09:00-15:00 is six hours against an eight-hour day.
        self.assertEqual(cells[2].early_minutes, 120)

    def test_working_past_the_day_is_overtime(self):
        cells = build({'2026-08-03': record('present', time(9, 0), time(19, 30))})

        # 09:00-19:30 is ten and a half hours against eight.
        self.assertEqual(cells[2].overtime_minutes, 150)

    def test_a_missing_checkout_invents_nothing(self):
        """An open shift is not an early departure.

        Guessing one produces a disciplinary figure nobody entered, and it would
        be derived from data that simply has not arrived yet.
        """
        cells = build({'2026-08-03': record('present', time(9, 0), None)})

        self.assertEqual(cells[2].early_minutes, 0)
        self.assertEqual(cells[2].overtime_minutes, 0)

    def test_an_absent_day_is_not_also_late(self):
        """Otherwise absence shows a lateness nobody can act on."""
        cells = build({'2026-08-03': record('absent')})

        self.assertEqual(cells[2].late_minutes, 0)

    def test_the_stored_status_is_never_rewritten(self):
        """The whole design: derived flags are presentation, `status` is truth."""
        cells = build({'2026-08-03': record('present', time(9, 45), time(17, 0))})

        self.assertEqual(cells[2].status, 'present')
        self.assertEqual(cells[2].as_dict()['status'], 'present')
        self.assertIn('late_minutes', cells[2].as_dict())

    def test_expected_hours_is_honoured(self):
        """A six-hour day is not eight, so leaving at 16:00 is not early."""
        cells = build({'2026-08-03': record('present', time(9, 0), time(16, 0))},
                      expected=7.0)

        self.assertEqual(cells[2].early_minutes, 0)


class MissingDayTests(TestCase):
    def test_an_unmarked_weekday_is_drawn_as_not_added(self):
        # Not index 0: 1 August 2026 is a Saturday, so that cell is a
        # weekend and saying anything about not_added there tested the
        # wrong thing and passed for the wrong reason.
        cells = build({})

        self.assertEqual(cells[2].date, date(2026, 8, 3))  # a Monday
        self.assertEqual(cells[2].status, 'not_added')

    def test_weekends_are_marked_rather_than_missing(self):
        """A weekend nobody was marked is not an absence, and colouring it like
        one turns a 31-day month into a month of red."""
        cells = build({})
        weekend = [c for c in cells if c.status == 'weekend']

        self.assertEqual(len(weekend), 10)  # August 2026: ten weekend days
        self.assertTrue(all(c.date.weekday() >= 5 for c in weekend))

    def test_the_month_always_has_every_day(self):
        cells = build({'2026-08-03': record()})

        self.assertEqual(len(cells), 31)


class SummaryTests(TestCase):
    def test_worked_and_expected_days_are_reported_separately(self):
        """`18/21` is a fact; a percentage invites reading six absences into it
        when some of those days were weekends."""
        records = {
            f'2026-08-{day:02d}': record('present', time(9), time(17))
            for day in range(3, 22)
            if date(2026, 8, day).weekday() < 5
        }
        summary = summarise(build(records))

        # Fifteen weekdays between the 3rd and the 21st, of twenty-one in
        # the month. Counting Saturday and Sunday as expected days would
        # make the ratio mean something else entirely - it would read as
        # nine absences when nobody missed a day.
        self.assertEqual(summary['worked_days'], 15)
        self.assertEqual(summary['expected_days'], 21)

    def test_weekends_are_excluded_from_the_expected_count(self):
        summary = summarise(build({}))

        self.assertEqual(summary['expected_days'], 21)  # 31 minus ten weekend days

    def test_late_days_are_counted_not_minutes(self):
        records = {
            '2026-08-03': record('present', time(9, 30), time(17)),
            '2026-08-04': record('present', time(9, 45), time(17)),
        }
        summary = summarise(build(records))

        self.assertEqual(summary['late_days'], 2)

    def test_overtime_is_summed_across_the_month(self):
        records = {
            '2026-08-03': record('present', time(9), time(19)),
            '2026-08-04': record('present', time(9), time(18)),
        }
        summary = summarise(build(records))

        # Two hours on the first day and one on the second.
        self.assertEqual(summary['overtime_minutes'], 120 + 60)

    def test_an_empty_month_does_not_divide_by_zero(self):
        summary = summarise([])

        self.assertEqual(summary['worked_ratio'], '0/0')


class StatusLabelTests(TestCase):
    def test_every_status_the_grid_can_emit_has_a_label(self):
        """An unlabelled glyph is a legend the reader has to guess at."""
        emitted = set(STATUS_LABELS)
        cells = build({})

        for cell in cells:
            self.assertIn(cell.status, emitted, cell.status)
