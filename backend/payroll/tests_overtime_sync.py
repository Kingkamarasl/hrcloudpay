"""Attendance -> overtime sync.

The arithmetic here pays real money, so the tests pin the two mistakes that
would overpay rather than the ones that would merely look wrong:

- treating hours worked as hours of overtime, so an ordinary 8-hour day is paid
  at the 1.5x weekday multiplier
- paying the same date twice when the sync runs a second time

Nothing here changed how an OvertimeEntry amount is calculated - that formula
moved from the view into payroll/overtime.py unchanged. What is new is the
threshold and the idempotence.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Company, Subscription, User
from accounts.platform_models import FeatureFlag
from attendance.models import Attendance
from employees.models import Employee
from payroll.models import OvertimeEntry, OvertimeRule, PublicHoliday

SYNC = '/api/payroll/overtime/sync-from-attendance/'
RULES = '/api/payroll/overtime/rules/'
ENTRIES = '/api/payroll/overtime/entries/'

# A Monday, so weekday/weekend classification is unambiguous in the tests.
MONDAY = date(2026, 9, 7)
SATURDAY = date(2026, 9, 12)
PERIOD = {'period_start': MONDAY.isoformat(), 'period_end': '2026-09-30'}


def active_company(name, email):
    company = Company.objects.create(
        name=name, email=email, is_active=True, plan='starter',
    )
    Subscription.objects.create(
        company=company, status='active',
        started_at=timezone.now(), renews_at=timezone.now() + timedelta(days=30),
    )
    return company


class SyncTestCase(TestCase):
    def setUp(self):
        self.company = active_company('Acme', 'acme@example.com')
        self.employee = Employee.objects.create(
            company=self.company, employee_code='E1',
            first_name='Ada', last_name='One',
            email='ada@example.com', base_salary=Decimal('173000.00'),
            department='Sales',
        )
        self.finance = User.objects.create_user(
            username='finance', email='fin@example.com',
            password='StrongPassword123!', company=self.company, role='finance',
        )
        self.rule = OvertimeRule.objects.create(
            company=self.company,
            weekday_multiplier=Decimal('1.5'),
            weekend_multiplier=Decimal('2.0'),
            holiday_multiplier=Decimal('2.0'),
            standard_hours_per_month=Decimal('173'),
            standard_hours_per_day=Decimal('8'),
        )
        # Every overtime endpoint is behind the payroll_overtime feature flag,
        # which is off by default. Without this the whole module 403s before
        # reaching any of the arithmetic under test.
        FeatureFlag.objects.update_or_create(
            key='payroll_overtime',
            defaults={
                'name': 'Overtime', 'description': '', 'enabled': True,
                'rollout_percent': 100, 'environment': 'all',
            },
        )
        self.client = APIClient()
        self.client.force_authenticate(self.finance)

    def attend(self, day, check_in, check_out, status='present', **extra):
        return Attendance.objects.create(
            employee=self.employee, date=day, status=status,
            check_in=time(*check_in), check_out=time(*check_out), **extra,
        )

    def sync(self, **overrides):
        payload = dict(PERIOD)
        payload.update(overrides)
        return self.client.post(SYNC, payload, format='json')


# ---------------------------------------------------------------------------
# The threshold: worked hours are not overtime hours
# ---------------------------------------------------------------------------
class OvertimeThresholdTests(SyncTestCase):
    def test_an_ordinary_day_creates_nothing(self):
        """The mistake this whole feature exists to avoid.

        worked_minutes is time on the clock. OvertimeEntry.hours is time paid at
        a premium. Passing one through as the other would pay a full ordinary
        day at 1.5x - roughly tripling the correct overtime for a normal week.
        """
        self.attend(MONDAY, (9, 0), (17, 0))

        body = self.sync().json()

        self.assertEqual(body['created_count'], 0)
        self.assertEqual(body['at_standard'], 1)
        self.assertEqual(OvertimeEntry.objects.count(), 0)

    def test_exactly_the_standard_day_creates_nothing(self):
        self.attend(MONDAY, (9, 0), (17, 0))
        self.assertEqual(self.sync().json()['created_count'], 0)

    def test_time_beyond_the_standard_day_becomes_overtime(self):
        """9:00-19:00 is a 10-hour day, so 2 hours are overtime - not 10."""
        self.attend(MONDAY, (9, 0), (19, 0))

        body = self.sync().json()

        self.assertEqual(body['created_count'], 1)
        entry = OvertimeEntry.objects.get()
        self.assertEqual(entry.hours, Decimal('2.00'))
        self.assertEqual(entry.day_type, 'weekday')

    def test_a_half_hour_past_standard_still_counts(self):
        self.attend(MONDAY, (9, 0), (17, 30))
        self.sync()
        self.assertEqual(OvertimeEntry.objects.get().hours, Decimal('0.50'))

    def test_the_amount_uses_the_premium_multiplier(self):
        """173000 / 173 = 1000/hr. 2h at 1.5x = 3000.00."""
        self.attend(MONDAY, (9, 0), (19, 0))
        self.sync()

        entry = OvertimeEntry.objects.get()
        self.assertEqual(entry.amount, Decimal('3000.00'))

    def test_a_configured_standard_day_is_honoured(self):
        """A 6-hour day makes an 8-hour shift 2 hours of overtime."""
        self.rule.standard_hours_per_day = Decimal('6')
        self.rule.save()
        self.attend(MONDAY, (9, 0), (17, 0))

        self.sync()
        self.assertEqual(OvertimeEntry.objects.get().hours, Decimal('2.00'))

    def test_an_overnight_shift_measures_the_whole_shift(self):
        """22:00 -> 06:00 is 8 hours, not negative, and not overtime."""
        self.attend(SATURDAY, (22, 0), (6, 0), crossed_midnight=True)
        self.assertEqual(self.sync().json()['created_count'], 0)

    def test_a_long_overnight_shift_earns_overtime(self):
        """22:00 -> 07:00 next day is 9 hours, so 1 hour of overtime."""
        self.attend(SATURDAY, (22, 0), (7, 0), crossed_midnight=True)
        self.sync()

        entry = OvertimeEntry.objects.get()
        self.assertEqual(entry.hours, Decimal('1.00'))
        self.assertEqual(entry.day_type, 'weekend')


# ---------------------------------------------------------------------------
# Day-type classification
# ---------------------------------------------------------------------------
class DayTypeTests(SyncTestCase):
    def test_a_sunday_shift_uses_the_weekend_multiplier(self):
        PublicHoliday.objects.create(
            company=self.company, date=SATURDAY, name='Test holiday')
        self.attend(SATURDAY, (9, 0), (21, 0))  # 12h -> 4h overtime

        self.sync()
        entry = OvertimeEntry.objects.get()

        self.assertEqual(entry.day_type, 'holiday')
        # 1000/hr * 4h * 2.0
        self.assertEqual(entry.amount, Decimal('8000.00'))

    def test_a_plain_weekend_uses_the_weekend_multiplier(self):
        self.attend(SATURDAY, (9, 0), (21, 0))
        self.sync()
        self.assertEqual(OvertimeEntry.objects.get().day_type, 'weekend')

    def test_a_company_holiday_is_not_taken_from_another_tenant(self):
        PublicHoliday.objects.create(
            company=active_company('Globex', 'globex@example.com'),
            date=MONDAY, name='Their holiday')
        self.attend(MONDAY, (9, 0), (19, 0))

        self.sync()
        self.assertEqual(OvertimeEntry.objects.get().day_type, 'weekday')


# ---------------------------------------------------------------------------
# Which records are considered
# ---------------------------------------------------------------------------
class RecordSelectionTests(SyncTestCase):
    def test_absent_and_leave_days_are_ignored(self):
        self.attend(MONDAY, (9, 0), (19, 0), status='absent')
        self.attend(date(2026, 9, 8), (9, 0), (19, 0), status='leave')

        body = self.sync().json()

        self.assertEqual(body['created_count'], 0)
        self.assertEqual(OvertimeEntry.objects.count(), 0)

    def test_a_day_with_no_clock_times_is_ignored(self):
        Attendance.objects.create(
            employee=self.employee, date=MONDAY, status='present')

        self.assertEqual(self.sync().json()['created_count'], 0)

    def test_days_outside_the_period_are_ignored(self):
        self.attend(date(2026, 10, 1), (9, 0), (19, 0))
        self.assertEqual(self.sync().json()['created_count'], 0)

    def test_one_employee_can_be_synced_on_its_own(self):
        other = Employee.objects.create(
            company=self.company, employee_code='E2',
            first_name='Ben', last_name='Two',
            email='ben@example.com', base_salary=Decimal('173000.00'),
            department='Sales',
        )
        self.attend(MONDAY, (9, 0), (19, 0))
        Attendance.objects.create(
            employee=other, date=MONDAY, status='present',
            check_in=time(9, 0), check_out=time(19, 0))

        self.sync(employee_id=self.employee.id)

        entry = OvertimeEntry.objects.get()
        self.assertEqual(entry.employee_id, self.employee.id)


# ---------------------------------------------------------------------------
# Idempotence - the expensive mistake
# ---------------------------------------------------------------------------
class IdempotenceTests(SyncTestCase):
    def test_running_the_sync_twice_does_not_pay_twice(self):
        """A sync endpoint that is only safe to call once is a trap.

        Payroll runs on a schedule and people re-run tools. Without the
        per-date guard the second run doubles real overtime for every date in
        the period, and the payslip looks entirely normal.
        """
        self.attend(MONDAY, (9, 0), (19, 0))
        self.attend(date(2026, 9, 8), (9, 0), (20, 0))

        first = self.sync().json()
        second = self.sync().json()

        self.assertEqual(first['created_count'], 2)
        self.assertEqual(second['created_count'], 0)
        self.assertEqual(second['already_present'], 2)
        self.assertEqual(OvertimeEntry.objects.count(), 2)
        # Monday 10h worked -> 2h at 1.5x = 3000. Tuesday 11h -> 3h = 4500.
        self.assertEqual(
            sum(e.amount for e in OvertimeEntry.objects.all()),
            Decimal('7500.00'),
        )

    def test_a_manually_entered_entry_is_not_duplicated(self):
        """Payroll may have already recorded the overtime by hand."""
        self.attend(MONDAY, (9, 0), (19, 0))
        OvertimeEntry.objects.create(
            company=self.company, employee=self.employee,
            work_date=MONDAY, hours=Decimal('3.00'), day_type='weekday',
            amount=Decimal('4500.00'), notes='entered by hand',
        )

        body = self.sync().json()

        self.assertEqual(body['created_count'], 0)
        self.assertEqual(body['already_present'], 1)
        self.assertEqual(OvertimeEntry.objects.count(), 1)

    def test_a_new_date_after_a_sync_is_still_picked_up(self):
        self.attend(MONDAY, (9, 0), (19, 0))
        self.sync()

        self.attend(date(2026, 9, 9), (9, 0), (19, 0))
        second = self.sync().json()

        self.assertEqual(second['created_count'], 1)
        self.assertEqual(second['already_present'], 1)


# ---------------------------------------------------------------------------
# Provenance, tenant isolation, and the endpoint contract
# ---------------------------------------------------------------------------
class SyncContractTests(SyncTestCase):
    def test_a_synced_entry_says_where_it_came_from(self):
        self.attend(MONDAY, (9, 0), (19, 0))
        self.sync()

        notes = OvertimeEntry.objects.get().notes
        self.assertIn('attendance', notes.lower())
        self.assertIn('10h worked', notes)
        # The standard day is interpolated as a Decimal, so it reads 8.00.
        self.assertIn('8.00h standard', notes)

    def test_the_sync_never_reaches_another_tenant(self):
        theirs = active_company('Globex', 'globex@example.com')
        their_employee = Employee.objects.create(
            company=theirs, employee_code='X1', first_name='X', last_name='One',
            email='x@example.com', base_salary=Decimal('173000.00'),
        )
        OvertimeRule.objects.create(company=theirs)
        Attendance.objects.create(
            employee=their_employee, date=MONDAY, status='present',
            check_in=time(9, 0), check_out=time(19, 0))

        self.sync()

        self.assertEqual(OvertimeEntry.objects.count(), 0)

    def test_hr_cannot_run_the_sync(self):
        """Payroll is a separate domain: CanManagePayroll excludes HR."""
        hr = User.objects.create_user(
            username='hr', email='hr@example.com',
            password='StrongPassword123!', company=self.company, role='hr',
        )
        self.client.force_authenticate(hr)
        self.assertEqual(self.sync().status_code, 403)

    def test_the_period_is_required(self):
        response = self.client.post(SYNC, {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_an_inverted_period_is_refused(self):
        response = self.sync(period_start='2026-09-30', period_end='2026-09-01')
        self.assertEqual(response.status_code, 400)

    def test_the_standard_day_is_editable_and_reported(self):
        response = self.client.put(RULES, {'standard_hours_per_day': '7.5'}, format='json')

        self.assertEqual(response.status_code, 200)
        # DecimalField normalises the scale on save.
        self.assertEqual(response.json()['standard_hours_per_day'], '7.50')

    def test_a_zero_standard_day_is_refused(self):
        response = self.client.put(RULES, {'standard_hours_per_day': '0'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_manual_entry_still_agrees_with_the_sync(self):
        """Both paths classify and price a day the same way.

        The formula was moved out of the view rather than copied, so this is a
        guard against the copy drifting back in. The two entries are on
        different dates on purpose: on the same date the sync would correctly
        skip, and there would be nothing to compare.
        """
        PublicHoliday.objects.create(
            company=self.company, date=SATURDAY, name='Test holiday')
        second_saturday = date(2026, 9, 19)
        PublicHoliday.objects.create(
            company=self.company, date=second_saturday, name='Another holiday')

        manual = self.client.post(ENTRIES, {
            'employee_id': self.employee.id,
            'work_date': SATURDAY.isoformat(),
            'hours': '2',
        }, format='json')
        self.assertEqual(manual.status_code, 201, manual.data)

        # 10h worked -> 2h overtime, on a day that is also a company holiday.
        self.attend(second_saturday, (9, 0), (19, 0))
        self.sync()

        hand = OvertimeEntry.objects.get(id=manual.json()['id'])
        synced = OvertimeEntry.objects.exclude(id=hand.id).get()

        self.assertEqual(synced.day_type, hand.day_type)
        self.assertEqual(synced.day_type, 'holiday')
        self.assertEqual(synced.amount, hand.amount)