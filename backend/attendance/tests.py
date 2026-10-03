"""Tests for the attendance app.

This app had no tests of its own. The only two assertions that touched it lived
in accounts/tests.py and covered department-manager writes only, so the paths
that actually broke - cross-tenant writes, and what an employee with no linked
Employee record could read - were never exercised by anything.

The three tests named after the defect they pin are regressions for bugs that
shipped: a 500 on a cross-tenant employee id, a company-wide read leak for
unlinked employee accounts, and reversed clock times being stored as though
they were a normal day.
"""
from datetime import date as Date
from datetime import time as Time
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import AuditLog, Company, Subscription, User
from attendance.models import Attendance
from employees.models import Employee

RECORDS = '/api/attendance/records/'


def active_company(name, email):
    """A company IsCompanyActive will accept.

    IsCompanyActive rejects a company with no subscription row, so without one
    every request 403s for a reason unrelated to what a test is asserting.
    """
    company = Company.objects.create(
        name=name, email=email, is_active=True, plan='starter',
    )
    Subscription.objects.create(
        company=company, status='active',
        started_at=timezone.now(), renews_at=timezone.now() + timedelta(days=30),
    )
    return company


class AttendanceTestCase(TestCase):
    """Two tenants, an HR user and an employee in each, plus a department."""

    def setUp(self):
        self.acme = active_company('Acme', 'acme@example.com')
        self.globex = active_company('Globex', 'globex@example.com')

        self.sales = self.make_employee(self.acme, 'S1', 'Sales', 'One')
        self.eng = self.make_employee(self.acme, 'E1', 'Eng', 'One', department='Engineering')
        self.outsider = self.make_employee(self.globex, 'X1', 'External', 'One')

        self.hr = self.make_user(self.acme, 'hr', 'hr')
        self.worker = self.make_user(self.acme, 'worker', 'employee')
        self.sales.user = self.worker
        self.sales.save()

        self.client = APIClient()
        self.authenticate(self.hr)

    def make_employee(self, company, code, first, last, department='Sales'):
        return Employee.objects.create(
            company=company, employee_code=code,
            first_name=first, last_name=last,
            email=f'{code.lower()}@{company.name.lower()}.example.com',
            base_salary=1000, department=department,
        )

    def make_user(self, company, username, role, **extra):
        return User.objects.create_user(
            username=username, email=f'{username}@{company.name.lower()}.example.com',
            password='StrongPassword123!', company=company, role=role, **extra,
        )

    def authenticate(self, user):
        self.client.force_authenticate(user)
        return user

    def record(self, employee, date='2026-09-01', status='present', **extra):
        # Date and time are coerced explicitly. objects.create() stores whatever
        # it is handed, so a bare string leaves the field as a str on the
        # in-memory instance and anything that does date arithmetic on it -
        # Attendance.worked_minutes - raises TypeError. DRF's DateField and
        # TimeField do coerce on the way in, which is why the API never hit
        # this; the difference only shows when the model is built directly.
        for field, caster in (('date', Date), ('check_in', Time), ('check_out', Time)):
            value = {'date': date}.get(field, extra.get(field))
            if isinstance(value, str):
                if field == 'date':
                    date = caster.fromisoformat(value)
                else:
                    extra[field] = caster.fromisoformat(value)
        return Attendance.objects.create(
            employee=employee, date=date, status=status, **extra
        )

    def rows(self, response):
        self.assertEqual(response.status_code, 200, response.data)
        return response.data.get('results', response.data)


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------
class TenantIsolationTests(AttendanceTestCase):
    def test_posting_another_tenants_employee_is_a_400_not_a_500(self):
        """The regression: this used to escape as Employee.DoesNotExist.

        A 500 is not only a server fault. It is also distinguishable from a
        400, so iterating employee ids told an HR user in one tenant how many
        employees another tenant had and which ids were real.
        """
        response = self.client.post(RECORDS, {
            'employee': self.outsider.id, 'date': '2026-09-01', 'status': 'present',
        }, format='json')

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('employee', response.data)
        self.assertEqual(Attendance.objects.count(), 0)

    def test_a_patch_cannot_move_a_record_into_another_tenant(self):
        """The same hole through the update path.

        `employee` was an unconstrained PrimaryKeyRelatedField, and the record
        being updated was only company-scoped, so reassignment was reachable
        too - and wrote no audit row naming the destination tenant.
        """
        record = self.record(self.sales)
        response = self.client.patch(
            f'{RECORDS}{record.id}/',
            {'employee': self.outsider.id},
            format='json',
        )

        self.assertEqual(response.status_code, 400, response.data)
        record.refresh_from_db()
        self.assertEqual(record.employee_id, self.sales.id)

    def test_a_listing_never_includes_another_tenant(self):
        self.record(self.sales)
        self.record(self.outsider, date='2026-09-02')

        rows = self.rows(self.client.get(RECORDS))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['employee'], self.sales.id)

    def test_a_record_from_another_tenant_is_not_reachable_by_id(self):
        theirs = self.record(self.outsider)
        response = self.client.get(f'{RECORDS}{theirs.id}/')
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# Row-level visibility
# ---------------------------------------------------------------------------
class RowVisibilityTests(AttendanceTestCase):
    def test_an_employee_sees_only_their_own_records(self):
        self.record(self.sales)
        self.record(self.eng)

        self.authenticate(self.worker)
        rows = self.rows(self.client.get(RECORDS))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['employee'], self.sales.id)

    def test_an_employee_with_no_linked_profile_sees_nothing(self):
        """The regression: this used to return the whole company.

        The employee branch was guarded by hasattr(user, 'employee_profile'),
        which is False when no Employee row points at the account. The guard
        took the whole branch - queryset filter included - so the request fell
        through to the unfiltered company queryset. Writes were still refused
        by CanManageHROrDepartment, so the leak was read-only and therefore
        invisible to anyone testing write permissions.
        """
        orphan = self.make_user(self.acme, 'orphan', 'employee')
        self.record(self.sales)
        self.record(self.eng)

        self.authenticate(orphan)
        rows = self.rows(self.client.get(RECORDS))

        self.assertIsNone(orphan.employee_id)
        self.assertEqual(rows, [])

    def test_a_department_manager_sees_only_their_department(self):
        self.record(self.sales)
        self.record(self.eng)

        manager = self.make_user(self.acme, 'sales-mgr', 'department_manager',
                                 managed_department='Sales')
        self.authenticate(manager)
        rows = self.rows(self.client.get(RECORDS))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['employee'], self.sales.id)

    def test_a_department_manager_with_no_department_sees_nothing(self):
        """managed_department is free text and defaults to blank.

        Blank used to build a filter on department='' and, depending on the
        data, could match rows nobody manages. Empty means unmanaged.
        """
        self.record(self.sales)
        manager = self.make_user(self.acme, 'unassigned-mgr', 'department_manager')
        self.authenticate(manager)

        self.assertEqual(self.rows(self.client.get(RECORDS)), [])

    def test_hr_sees_the_whole_company(self):
        self.record(self.sales)
        self.record(self.eng)

        self.assertEqual(len(self.rows(self.client.get(RECORDS))), 2)


# ---------------------------------------------------------------------------
# Write rules
# ---------------------------------------------------------------------------
class AttendanceWriteTests(AttendanceTestCase):
    def test_one_record_per_employee_per_day(self):
        self.record(self.sales, date='2026-09-01')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.record(self.sales, date='2026-09-01')

    def test_the_same_day_is_fine_for_two_different_employees(self):
        self.record(self.sales, date='2026-09-01')
        self.record(self.eng, date='2026-09-01')
        self.assertEqual(Attendance.objects.count(), 2)

    def test_a_department_manager_cannot_record_for_another_department(self):
        manager = self.make_user(self.acme, 'eng-mgr', 'department_manager',
                                 managed_department='Sales')
        self.authenticate(manager)
        response = self.client.post(RECORDS, {
            'employee': self.eng.id, 'date': '2026-09-01', 'status': 'present',
        }, format='json')
        self.assertEqual(response.status_code, 403)

    def test_a_department_manager_can_record_for_their_own_department(self):
        manager = self.make_user(self.acme, 'sales-mgr2', 'department_manager',
                                 managed_department='Sales')
        self.authenticate(manager)
        response = self.client.post(RECORDS, {
            'employee': self.sales.id, 'date': '2026-09-01', 'status': 'present',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)


# ---------------------------------------------------------------------------
# Clock times
# ---------------------------------------------------------------------------
class ClockTimeTests(AttendanceTestCase):
    def post(self, **extra):
        payload = {'employee': self.sales.id, 'date': '2026-09-01', 'status': 'present'}
        payload.update(extra)
        return self.client.post(RECORDS, payload, format='json')

    def test_a_normal_day_is_accepted(self):
        response = self.post(check_in='09:00', check_out='17:30')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['worked_minutes'], 8 * 60 + 30)

    def test_an_overnight_shift_needs_the_flag_and_is_accepted_with_it(self):
        response = self.post(check_in='22:00', check_out='06:00', crossed_midnight=True)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['worked_minutes'], 8 * 60)

    def test_reversed_times_without_the_flag_are_refused(self):
        """The regression: this returned 201 and stored 17:00 -> 09:00.

        Nothing downstream could tell that from a night shift, so the row sat
        there looking valid until someone read the hours off it.
        """
        response = self.post(check_in='17:00', check_out='09:00')

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('check_out', response.data)
        self.assertEqual(Attendance.objects.count(), 0)

    def test_the_flag_cannot_contradict_the_times(self):
        response = self.post(check_in='09:00', check_out='17:00', crossed_midnight=True)

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('crossed_midnight', response.data)

    def test_a_check_out_without_a_check_in_is_refused(self):
        response = self.post(check_out='17:00')
        self.assertEqual(response.status_code, 400, response.data)

    def test_worked_minutes_is_absent_until_both_times_are_known(self):
        """None, not 0 - nobody clocked out and worked zero minutes differ."""
        record = self.record(self.sales, check_in='09:00')
        self.assertIsNone(record.worked_minutes)

        # A real datetime.time, the way the ORM or DRF's TimeField would leave
        # it. Assigning the raw string is not a supported state.
        record.check_out = Time.fromisoformat('17:00')
        self.assertEqual(record.worked_minutes, 8 * 60)

    def test_equal_check_in_and_check_out_is_zero_hours_not_an_error(self):
        response = self.post(check_in='09:00', check_out='09:00')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['worked_minutes'], 0)


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------
class AttendanceAuditTests(AttendanceTestCase):
    def test_creating_a_record_is_audited(self):
        response = self.client.post(RECORDS, {
            'employee': self.sales.id, 'date': '2026-09-01', 'status': 'present',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)

        entry = AuditLog.objects.filter(action='create', target_type='attendance').first()
        self.assertIsNotNone(entry, 'creating attendance wrote no audit row')
        # target_id is a CharField, so the id comes back as a string.
        self.assertEqual(entry.target_id, str(response.data['id']))
        self.assertEqual(entry.company_id, self.acme.id)

    def test_updating_a_record_is_audited_with_the_change(self):
        record = self.record(self.sales, status='present')

        response = self.client.patch(
            f'{RECORDS}{record.id}/', {'status': 'absent'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)

        entry = AuditLog.objects.filter(action='update', target_type='attendance').first()
        self.assertIsNotNone(entry, 'updating attendance wrote no audit row')
        self.assertIn('status', str(entry.metadata))

    def test_deleting_a_record_is_audited(self):
        record = self.record(self.sales)

        response = self.client.delete(f'{RECORDS}{record.id}/')
        self.assertEqual(response.status_code, 204)

        entry = AuditLog.objects.filter(action='delete', target_type='attendance').first()
        self.assertIsNotNone(entry, 'deleting attendance wrote no audit row')
        self.assertEqual(entry.target_id, str(record.id))