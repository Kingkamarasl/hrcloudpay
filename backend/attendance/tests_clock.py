"""Clock in / clock out.

The interesting cases here are the ones a naive implementation gets wrong:

- a shift that starts at 22:00 and ends at 06:00 the next morning belongs to the
  day it started, so clock-out has to find that open record rather than looking
  at today
- a second clock-in must not overwrite a forgotten open shift, because that
  destroys real hours silently
- an employee can only clock themselves
"""
from datetime import time

from django.test import TestCase
from rest_framework.test import APIClient

from attendance.models import Attendance

from .tests import AttendanceTestCase

CLOCK = '/api/attendance/records/clock/'


class ClockInTests(AttendanceTestCase):
    def setUp(self):
        super().setUp()
        self.authenticate(self.worker)

    def clock(self, action, **extra):
        payload = {'action': action}
        payload.update(extra)
        return self.client.post(CLOCK, payload, format='json')

    def test_an_employee_clocks_themselves_in(self):
        response = self.clock('clock_in')

        self.assertEqual(response.status_code, 201, response.data)
        record = Attendance.objects.get()
        self.assertEqual(record.employee_id, self.sales.id)
        self.assertIsNotNone(record.check_in)
        self.assertIsNone(record.check_out)
        self.assertEqual(record.status, 'present')

    def test_clocking_in_twice_is_refused(self):
        """Otherwise a forgotten open shift is silently overwritten."""
        self.clock('clock_in')
        first = Attendance.objects.get().check_in

        response = self.clock('clock_in')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Attendance.objects.count(), 1)
        self.assertEqual(Attendance.objects.get().check_in, first)

    def test_an_employee_cannot_clock_in_for_a_colleague(self):
        """Refused, not quietly redirected to the caller.

        Ignoring the supplied id and clocking in the caller anyway returns 201
        and records the wrong person, which reaches payroll as a correction.
        """
        response = self.clock('clock_in', employee=self.eng.id)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Attendance.objects.count(), 0)

    def test_an_employee_with_no_profile_is_told_why(self):
        orphan = self.make_user(self.acme, 'orphan', 'employee')
        self.authenticate(orphan)

        response = self.clock('clock_in')

        self.assertEqual(response.status_code, 400)
        self.assertIn('not linked', str(response.data).lower())

    def test_hr_can_clock_in_on_behalf_of_an_employee(self):
        self.authenticate(self.hr)
        response = self.clock('clock_in', employee=self.sales.id)

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Attendance.objects.get().employee_id, self.sales.id)

    def test_hr_cannot_clock_in_for_another_tenant(self):
        self.authenticate(self.hr)
        response = self.clock('clock_in', employee=self.outsider.id)
        self.assertEqual(response.status_code, 400)

    def test_a_department_manager_cannot_clock_in_outside_their_department(self):
        manager = self.make_user(self.acme, 'sales-mgr', 'department_manager',
                                 managed_department='Sales')
        self.authenticate(manager)

        self.assertEqual(self.clock('clock_in', employee=self.sales.id).status_code, 201)
        self.assertEqual(self.clock('clock_in', employee=self.eng.id).status_code, 403)

    def test_an_unknown_action_is_refused(self):
        self.assertEqual(self.clock('clock_lunch').status_code, 400)
        self.assertEqual(self.clock('clock_out').status_code, 400)

    def test_clocking_in_is_audited(self):
        self.clock('clock_in')
        self.assertTrue(clock_audit_rows(), 'clock-in wrote no audit row')


    def test_anonymous_users_cannot_clock(self):
        self.client.force_authenticate(None)
        # 401 or 403 depending on the authentication classes in play; what
        # matters is that it is refused rather than recorded.
        self.assertIn(self.clock('clock_in').status_code, (401, 403))
        self.assertEqual(Attendance.objects.count(), 0)


class ClockOutTests(AttendanceTestCase):
    def setUp(self):
        super().setUp()
        self.authenticate(self.worker)

    def clock(self, action, **extra):
        payload = {'action': action}
        payload.update(extra)
        return self.client.post(CLOCK, payload, format='json')

    def test_clocking_out_completes_todays_record(self):
        self.record(self.sales, check_in=time(9, 0), date=self.today)

        response = self.clock('clock_out')

        self.assertEqual(response.status_code, 200, response.data)
        record = Attendance.objects.get()
        self.assertIsNotNone(record.check_out)
        self.assertFalse(record.crossed_midnight)

    def test_clocking_out_without_an_open_shift_is_refused(self):
        response = self.clock('clock_out')
        self.assertEqual(response.status_code, 400)
        self.assertIn('no open shift', str(response.data).lower())

    def test_clocking_out_twice_is_refused(self):
        self.record(self.sales, check_in=time(9, 0), date=self.today)
        self.assertEqual(self.clock('clock_out').status_code, 200)

        response = self.clock('clock_out')
        self.assertEqual(response.status_code, 400)

    def test_an_overnight_shift_closes_against_the_day_it_started(self):
        """The case that breaks a clock-out which looks up 'today'.

        Clocked in yesterday at 22:00, clocks out this morning. Looking for
        today's record finds nothing and the shift stays open forever, so the
        hours never reach payroll.
        """
        yesterday = self.record(
            self.sales, check_in=time(22, 0), date=self.today_minus_one)
        self.assertIsNone(yesterday.check_out)

        response = self.clock('clock_out')

        self.assertEqual(response.status_code, 200, response.data)
        yesterday.refresh_from_db()
        self.assertIsNotNone(yesterday.check_out)
        # Late evening to early morning is the next day.
        self.assertTrue(yesterday.crossed_midnight)
        self.assertEqual(yesterday.worked_minutes > 0, True)

    def test_the_most_recent_open_shift_is_the_one_closed(self):
        older = self.record(self.sales, check_in=time(22, 0),
                            date=self.today_minus_one)
        newer = self.record(self.sales, check_in=time(9, 0), date=self.today)

        self.clock('clock_out')

        older.refresh_from_db()
        newer.refresh_from_db()
        self.assertIsNone(older.check_out)
        self.assertIsNotNone(newer.check_out)

    def test_clocking_out_is_audited(self):
        self.record(self.sales, check_in=time(9, 0), date=self.today)
        self.clock('clock_out')
        self.assertTrue(clock_audit_rows(), 'clock-out wrote no audit row')

    def test_an_employee_cannot_clock_out_a_colleagues_shift(self):
        colleague = self.record(self.eng, check_in=time(22, 0),
                                date=self.today_minus_one)
        # The worker has no open shift of their own.
        response = self.clock('clock_out')
        self.assertEqual(response.status_code, 400)
        colleague.refresh_from_db()
        self.assertIsNone(colleague.check_out)


def clock_audit_rows():
    """Audit rows written by the clock actions.

    Filtered in Python rather than SQL because the clock action does not use a
    distinct target_type, and `message ILIKE ...` would be Postgres-only for no
    benefit - the suite has to run on SQLite too.
    """
    from accounts.models import AuditLog
    return [
        e for e in AuditLog.objects.filter(action__in=('create', 'update'))
        if (e.message or '').startswith('Clocked')
    ]