"""Process biometric punches into attendance records.

The device reports "employee X was at terminal Y at time T". Turning that into a
payroll fact is the same problem as the manual clock-in path, with two extra
complications: a punch may arrive out of order, and a midnight shift means the
clock-out punch lands on the next calendar day.

The processing rules mirror ClockView deliberately, so the two entry points
cannot disagree about what a shift is:
  * A punch-in creates a record if there is none open for that employee.
  * A punch-out finds the open record (check-in set, check-out unset) and sets
    the clock-out, handling midnight crossing.
  * A punch of unknown type is inferred from the open-record state.
  * A second punch-in while a record is open is ignored, not overwritten -
    silently replacing it would destroy hours.
  * A punch-out with no open record is recorded as an unmatched punch rather
    than inventing a clock-in time, because a fabricated check-in is a worse
    payroll error than a missing one.
"""


from datetime import datetime, timedelta

from django.utils import timezone

from attendance.models import Attendance
from employees.models import Employee


def _as_local(dt):
    # A punch carries the wall-clock time at the device, in the device's own
    # offset. Converting it to the server's time zone would silently rewrite
    # "08:00 at the Accra terminal" into "06:00" on a UTC server, which is
    # the wrong fact for an attendance record. Keep the device's wall clock.
    if timezone.is_naive(dt):
        return timezone.make_aware(dt)
    return dt


def process_punch(punch):
    """Turn a BiometricPunch into an Attendance record (or mark it ignored).

    Returns the (possibly None) Attendance record. Mutates punch.status and
    punch.error and saves them.
    """
    from biometrics.models import BiometricPunch

    employee = punch.employee
    if employee is None:
        punch.status = 'ignored'
        punch.error = 'Punch could not be matched to an employee.'
        punch.save(update_fields=['status', 'error'])
        return None

    local = _as_local(punch.punch_time)
    punch_date = local.date()
    punch_time = local.time().replace(tzinfo=None)
    ptype = punch.punch_type

    # Infer the type when the device did not say.
    if ptype == 'unknown':
        open_record = _open_record(employee)
        ptype = 'out' if open_record is not None else 'in'

    if ptype == 'in':
        # An open record means someone is still clocked in. Refuse to overwrite
        # it - a forgotten clock-out must be reconciled by a person, not by the
        # next morning's arrival.
        open_record = _open_record(employee)
        if open_record is not None:
            punch.status = 'ignored'
            punch.error = (
                '%s already has an open shift from %s. Reconcile it before '
                'recording another clock-in.' % (employee.full_name, open_record.date))
            punch.save(update_fields=['status', 'error'])
            return open_record

        # A record for today already exists and is closed - do not create a
        # duplicate day.
        existing = Attendance.objects.filter(
            employee=employee, date=punch_date).first()
        if existing is not None:
            punch.status = 'ignored'
            punch.error = (
                '%s already has an attendance record for %s.'
                % (employee.full_name, punch_date))
            punch.save(update_fields=['status', 'error'])
            return existing

        record = Attendance.objects.create(
            employee=employee, date=punch_date, status='present',
            check_in=punch_time, notes='Clocked in (biometric)',
        )
        punch.status = 'processed'
        punch.attendance_record = record
        punch.save(update_fields=['status', 'attendance_record'])
        return record

    # punch_type == 'out'
    open_record = _open_record(employee)
    if open_record is None:
        # No open shift to close. Recording a clock-out with no clock-in would
        # fabricate hours, so leave it as a punch for a person to reconcile.
        punch.status = 'failed'
        punch.error = (
            '%s has no open shift to clock out of.' % employee.full_name)
        punch.save(update_fields=['status', 'error'])
        return None

    open_record.check_out = punch_time
    # A clock-out on a later date than the clock-in means the shift crossed
    # midnight. Store it explicitly rather than inferring from the times.
    if local.date() > open_record.date:
        open_record.crossed_midnight = True
    open_record.save(update_fields=['check_out', 'crossed_midnight'])
    punch.status = 'processed'
    punch.attendance_record = open_record
    punch.save(update_fields=['status', 'attendance_record'])
    return open_record


def _open_record(employee):
    """The shift that is currently open, if any."""
    return Attendance.objects.filter(
        employee=employee, check_in__isnull=False,
        check_out__isnull=True).order_by('-date').first()


def match_employee(device, identifier):
    """Resolve a device-side identifier to an Employee at the device's company.

    Devices report their own identifiers - a badge number, a user id from their
    own database. We accept the employee's PK or employee_code, scoped to the
    device's company so a device can never record attendance for another tenant.
    """
    if identifier is None or identifier == '':
        return None
    qs = Employee.objects.filter(company=device.company)
    try:
        pk = int(identifier)
        emp = qs.filter(pk=pk).first()
        if emp is not None:
            return emp
    except (TypeError, ValueError):
        pass
    return qs.filter(employee_code__iexact=str(identifier)).first()