"""Deducting pay for unpaid absence.

The asymmetry that shapes every test here: failing to deduct costs an employer a
few days' pay, while deducting a day someone was entitled to takes money out of
someone's pay on the strength of a manager's attendance mark. So the tests
spend most of their effort on what must NOT be deducted.

There is no linkage between attendance and leave anywhere in this codebase, so
a manager can mark absent a day an approved leave request already covers. That
is the most likely way this feature hurts somebody, and it gets its own test.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Company, Subscription, User
from accounts.platform_models import FeatureFlag
from attendance.models import Attendance
from employees.models import Employee
from leave.models import LeaveRequest
from payroll.absence import absence_deduction, weekdays_in_period
from payroll.models import PayrollConfig, PayrollRun, PublicHoliday


def active_company(name, email):
    company = Company.objects.create(
        name=name, email=email, is_active=True, plan='starter',
    )
    Subscription.objects.create(
        company=company, status='active',
        started_at=timezone.now(), renews_at=timezone.now() + timedelta(days=30),
    )
    return company


class AbsenceTestCase(TestCase):
    # A full month of weekdays, so the daily rate is easy to reason about.
    PERIOD_START = date(2026, 9, 1)
    PERIOD_END = date(2026, 9, 30)

    def setUp(self):
        self.company = active_company('Acme', 'acme@example.com')
        self.employee = Employee.objects.create(
            company=self.company, employee_code='E1',
            first_name='Ada', last_name='One',
            email='ada@example.com', base_salary=Decimal('220000.00'),
            department='Sales',
        )
        self.config = PayrollConfig.objects.create(
            company=self.company, currency='NGN', pay_frequency='monthly',
            deduct_unpaid_absence=True,
        )
        FeatureFlag.objects.update_or_create(
            key='payroll_overtime',
            defaults={'name': 'Overtime', 'description': '', 'enabled': True,
                      'rollout_percent': 100, 'environment': 'all'},
        )
        self.client = APIClient()

    def absent(self, day, status='absent'):
        return Attendance.objects.create(
            employee=self.employee, date=day, status=status)

    def leave(self, day, leave_type='annual', status='approved'):
        return LeaveRequest.objects.create(
            employee=self.employee, leave_type=leave_type,
            start_date=day, end_date=day, status=status, reason='test')

    def deduct(self):
        return absence_deduction(self.employee, self.PERIOD_START, self.PERIOD_END)


class WeekdayCountTests(TestCase):
    def test_counts_monday_to_friday_only(self):
        # 2026-09-07 is a Monday, so the 7th-11th is exactly five weekdays.
        self.assertEqual(
            weekdays_in_period(date(2026, 9, 7), date(2026, 9, 11)), 5)

    def test_an_inverted_or_empty_period_is_zero(self):
        self.assertEqual(weekdays_in_period(date(2026, 9, 30), date(2026, 9, 1)), 0)
        self.assertEqual(weekdays_in_period(None, None), 0)

    def test_september_2026_has_the_expected_weekday_count(self):
        self.assertEqual(
            weekdays_in_period(date(2026, 9, 1), date(2026, 9, 30)), 22)


class AbsenceDeductionTests(AbsenceTestCase):
    def test_no_records_means_no_deduction(self):
        self.assertEqual(self.deduct()[0], Decimal('0.00'))

    def test_an_unexplained_absence_is_deducted(self):
        self.absent(date(2026, 9, 7))  # Monday
        total, lines = self.deduct()
        # 220000 / 22 weekdays = 10000 per weekday.
        self.assertEqual(total, Decimal('10000.00'))
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['date'], '2026-09-07')
        self.assertEqual(lines[0]['daily_rate'], '10000.00')

    def test_each_line_names_a_date(self):
        """A payslip saying "absence: -30,000" with no dates cannot be checked."""
        for day in (date(2026, 9, 7), date(2026, 9, 8), date(2026, 9, 9)):
            self.absent(day)
        _total, lines = self.deduct()
        self.assertEqual([l['date'] for l in lines],
                         ['2026-09-07', '2026-09-08', '2026-09-09'])

    def test_a_weekend_absence_is_never_deducted(self):
        self.absent(date(2026, 9, 12))  # Saturday
        self.assertEqual(self.deduct()[0], Decimal('0.00'))

    def test_a_public_holiday_absence_is_never_deducted(self):
        holiday = date(2026, 9, 14)  # Monday
        PublicHoliday.objects.create(
            company=self.company, date=holiday, name='Independence Day')
        self.absent(holiday)

        self.assertEqual(self.deduct()[0], Decimal('0.00'))

    def test_absent_behind_an_approved_leave_request_is_not_deducted(self):
        """The double-penalty guard, and the most likely way to hurt someone.

        Leave and attendance are not linked anywhere. A manager marking absent a
        day that an approved request already covers is an easy mistake, and
        without this check it silently becomes a wage deduction.
        """
        self.leave(date(2026, 9, 7))
        self.absent(date(2026, 9, 7))

        self.assertEqual(self.deduct()[0], Decimal('0.00'))

    def test_a_multi_day_leave_request_covers_its_whole_span(self):
        LeaveRequest.objects.create(
            employee=self.employee, leave_type='annual',
            start_date=date(2026, 9, 7), end_date=date(2026, 9, 11),
            status='approved', reason='holiday')
        for day in (7, 8, 9, 10, 11):
            self.absent(date(2026, 9, day))

        self.assertEqual(self.deduct()[0], Decimal('0.00'))

    def test_a_pending_leave_request_does_not_protect_the_day(self):
        """Pending is not approved. Someone on unapproved leave is absent."""
        self.leave(date(2026, 9, 7), status='pending')
        self.absent(date(2026, 9, 7))

        self.assertEqual(self.deduct()[0], Decimal('10000.00'))

    def test_paid_leave_marked_as_leave_is_not_deducted(self):
        self.leave(date(2026, 9, 7), leave_type='sick')
        self.absent(date(2026, 9, 7), status='leave')

        self.assertEqual(self.deduct()[0], Decimal('0.00'))

    def test_unpaid_leave_marked_as_leave_is_deducted(self):
        self.leave(date(2026, 9, 7), leave_type='unpaid')
        self.absent(date(2026, 9, 7), status='leave')

        self.assertEqual(self.deduct()[0], Decimal('10000.00'))

    def test_a_present_day_is_never_deducted(self):
        self.absent(date(2026, 9, 7), status='present')
        self.assertEqual(self.deduct()[0], Decimal('0.00'))

    def test_days_outside_the_period_are_ignored(self):
        self.absent(date(2026, 10, 1))
        self.absent(date(2026, 8, 31))

        self.assertEqual(self.deduct()[0], Decimal('0.00'))

    def test_the_deduction_never_exceeds_the_salary(self):
        """A month of absence must not produce a negative wage out of a salary."""
        for day in (1, 2, 3, 4, 7, 8, 9, 10, 11, 14, 15, 16, 17, 18,
                    21, 22, 23, 24, 25, 28, 29, 30):
            self.absent(date(2026, 9, day))
            PublicHoliday.objects.create(
                company=self.company, date=date(2026, 9, day), name='x')

        total, _lines = self.deduct()

        self.assertEqual(total, Decimal('0.00'))

    def test_it_never_touches_another_employee(self):
        colleague = Employee.objects.create(
            company=self.company, employee_code='E2',
            first_name='Ben', last_name='Two',
            email='ben@example.com', base_salary=Decimal('220000.00'),
        )
        Attendance.objects.create(
            employee=colleague, date=date(2026, 9, 7), status='absent')

        self.assertEqual(self.deduct()[0], Decimal('0.00'))


class OptInTests(AbsenceTestCase):
    def test_nothing_is_deducted_while_the_flag_is_off(self):
        self.config.deduct_unpaid_absence = False
        self.config.save()
        self.absent(date(2026, 9, 7))

        from payroll.services import calculate_payslip
        payslip = calculate_payslip(self.employee, self.config, self.make_run())

        self.assertEqual(payslip['total_other_deductions'], Decimal('0'))
        self.assertEqual(payslip['breakdown']['unpaid_absence'], [])

    def test_the_flag_defaults_to_off(self):
        """A new company must not start deducting wages unasked."""
        fresh = PayrollConfig.objects.create(
            company=active_company('Globex', 'globex@example.com'))
        self.assertFalse(fresh.deduct_unpaid_absence)

    def make_run(self):
        return PayrollRun.objects.create(
            company=self.company,
            period_start=self.PERIOD_START,
            period_end=self.PERIOD_END,
            status='draft',
        )

    def test_the_deduction_reaches_net_salary_when_enabled(self):
        run = self.make_run()
        self.absent(date(2026, 9, 7))

        from payroll.services import calculate_payslip
        payslip = calculate_payslip(self.employee, self.config, run)

        self.assertEqual(payslip['total_other_deductions'], Decimal('10000.00'))
        self.assertEqual(
            payslip['net_salary'],
            payslip['gross_salary'] - payslip['tax_amount']
            - payslip['total_contributions'] - Decimal('10000.00'),
        )