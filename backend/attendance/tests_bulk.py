"""Bulk-marking a date for many employees.

The rule that matters most here is that an existing record is skipped rather
than overwritten. Someone who clocked in at 08:58 has real hours in that row,
and a bulk mark that flipped them to `absent` would destroy the clock times and
leave an attendance trail claiming they never arrived - silently, because the
response would still say "done".
"""
from datetime import time

from django.test import TestCase

from accounts.models import AuditLog
from attendance.models import Attendance

from .tests import AttendanceTestCase

BULK = '/api/attendance/records/bulk/'
MONDAY = '2026-09-07'


class BulkMarkTests(AttendanceTestCase):
    def setUp(self):
        super().setUp()
        self.engineering = self.make_employee(
            self.acme, 'E2', 'Eve', 'Two', department='Engineering')

    def bulk(self, **payload):
        body = {'date': MONDAY, 'status': 'absent'}
        body.update(payload)
        return self.client.post(BULK, body, format='json')

    def test_marks_every_listed_employee(self):
        response = self.bulk(employee_ids=[self.sales.id, self.eng.id])

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['created_count'], 2)
        self.assertEqual(Attendance.objects.count(), 2)

    def test_marks_a_whole_department(self):
        self.make_employee(self.acme, 'S2', 'Sam', 'Two', department='Sales')

        response = self.bulk(department='Sales')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['created_count'], 2)
        self.assertEqual(
            set(Attendance.objects.values_list('employee__department', flat=True)),
            {'Sales'},
        )

    def test_a_department_and_an_explicit_list_intersect(self):
        """Both given means both apply, not either-or."""
        response = self.bulk(department='Sales', employee_ids=[self.eng.id])

        self.assertEqual(response.data['created_count'], 0)

    def test_an_existing_record_is_skipped_not_overwritten(self):
        self.record(self.sales, date='2026-09-07',
                    check_in=time(8, 58), check_out=time(17, 30))

        response = self.bulk(employee_ids=[self.sales.id, self.eng.id])

        self.assertEqual(response.data['created_count'], 1)
        self.assertEqual(response.data['skipped_existing'], 1)
        self.assertEqual(response.data['skipped_existing_ids'], [self.sales.id])

        kept = Attendance.objects.get(employee=self.sales)
        self.assertEqual(kept.check_in, time(8, 58))
        self.assertEqual(kept.status, 'present')

    def test_a_partial_overlap_still_creates_the_rest(self):
        self.record(self.eng, date='2026-09-07')

        response = self.bulk(employee_ids=[self.sales.id, self.eng.id])

        self.assertEqual(response.data['created_count'], 1)
        self.assertEqual(Attendance.objects.count(), 2)

    def test_rerunning_the_same_bulk_marks_nothing_new(self):
        self.bulk(employee_ids=[self.sales.id])
        response = self.bulk(employee_ids=[self.sales.id])

        self.assertEqual(response.data['created_count'], 0)
        self.assertEqual(response.data['skipped_existing'], 1)
        self.assertEqual(Attendance.objects.count(), 1)

    def test_the_batch_is_written_audited(self):
        self.bulk(employee_ids=[self.sales.id, self.eng.id])

        entry = AuditLog.objects.filter(
            action='create', target_type='attendance').order_by('-id').first()

        self.assertIsNotNone(entry)
        self.assertIn('Bulk marked 2 employees', entry.message)
        metadata = entry.metadata if isinstance(entry.metadata, dict) else {}
        self.assertEqual(
            sorted(metadata.get('employee_ids', [])),
            sorted([self.sales.id, self.eng.id]),
        )

    def test_nothing_is_written_when_nothing_changes(self):
        self.bulk(employee_ids=[self.sales.id])
        AuditLog.objects.filter(target_type='attendance').delete()

        self.bulk(employee_ids=[self.sales.id])

        self.assertEqual(
            AuditLog.objects.filter(target_type='attendance').count(), 0)

    def test_the_status_is_recorded_on_each_row(self):
        self.bulk(employee_ids=[self.sales.id], status='half_day')
        self.assertEqual(Attendance.objects.get().status, 'half_day')


# ---------------------------------------------------------------------------
# Scope and validation
# ---------------------------------------------------------------------------
class BulkMarkScopeTests(AttendanceTestCase):
    def setUp(self):
        super().setUp()
        self.engineering = self.make_employee(
            self.acme, 'E2', 'Eve', 'Two', department='Engineering')

    def bulk(self, user=None, **payload):
        self.authenticate(user or self.hr)
        body = {'date': MONDAY, 'status': 'absent'}
        body.update(payload)
        return self.client.post(BULK, body, format='json')

    def test_one_employee_from_another_tenant_rejects_the_whole_batch(self):
        """19 of 20 applied with the 20th refused leaves the caller unable to
        tell which half took effect, so this is all-or-nothing."""
        response = self.bulk(employee_ids=[self.sales.id, self.outsider.id])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Attendance.objects.count(), 0)

    def test_an_unknown_employee_id_is_refused(self):
        response = self.bulk(employee_ids=[self.sales.id, 999999])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Attendance.objects.count(), 0)

    def test_a_department_manager_cannot_mark_another_department(self):
        manager = self.make_user(self.acme, 'sales-mgr', 'department_manager',
                                 managed_department='Sales')

        response = self.bulk(user=manager,
                             employee_ids=[self.sales.id, self.engineering.id])

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Attendance.objects.count(), 0)

    def test_a_department_manager_can_mark_their_own_department(self):
        manager = self.make_user(self.acme, 'sales-mgr2', 'department_manager',
                                 managed_department='Sales')

        response = self.bulk(user=manager, department='Sales')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['created_count'], 1)

    def test_an_employee_cannot_bulk_mark(self):
        response = self.bulk(user=self.worker,
                             employee_ids=[self.sales.id])

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Attendance.objects.count(), 0)

    def test_a_department_that_matches_nothing_is_not_an_error(self):
        response = self.bulk(department='Nonexistent')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['created_count'], 0)

    def test_the_date_is_required_and_must_be_iso(self):
        self.assertEqual(self.bulk(date='').status_code, 400)
        self.assertEqual(self.bulk(date='07/09/2026').status_code, 400)

    def test_an_unknown_status_is_refused(self):
        response = self.bulk(employee_ids=[self.sales.id], status='vacation')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Attendance.objects.count(), 0)

    def test_a_target_is_required(self):
        response = self.bulk()

        self.assertEqual(response.status_code, 400)