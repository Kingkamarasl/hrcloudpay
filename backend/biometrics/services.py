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

from django.conf import settings
from django.utils import timezone

from attendance.models import Attendance
from employees.models import Employee


def _device_wall_clock(punch):
    """The punch's wall-clock time on the device that reported it.

    A punch carries the time at the device, in the device's own offset, and
    that wall clock is the fact attendance is made of: converting it to the
    server's time zone would silently rewrite "08:00 at the Accra terminal"
    into "06:00" on a UTC server, and move the shift to the wrong day.

    The database keeps the instant, so the offset is kept beside it (see
    BiometricPunch.utc_offset_minutes) and the wall clock is reconstructed from
    the two. Reading it off the instance alone only worked while that instance
    was the one just created by this process: a punch loaded from the database
    comes back as a UTC instant, so reprocessing a stored punch - which is what
    reconciliation is - has to go through the recorded offset.
    """
    dt = punch.punch_time
    if punch.utc_offset_minutes is None:
        # No offset recorded: a punch written before the column existed, or by
        # a data fix. Keep the value as given rather than inventing one.
        if timezone.is_naive(dt):
            return timezone.make_aware(dt)
        return dt
    zone = timezone.get_fixed_timezone(punch.utc_offset_minutes)
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, zone)
    return dt.astimezone(zone)


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

    local = _device_wall_clock(punch)
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
    """Resolve a device-side identifier to (employee, matched_by).

    Which identifiers a terminal may identify someone by is that terminal's own
    choice - see BiometricDevice.match_policy - and the rule that decided is
    returned beside the employee so the punch can record it. Within the
    device's policy the rules run in a fixed order:

      1. the enrolment tying this person to this terminal (always allowed - it
         is the one identifier the device cannot lie about)
      2. the employee's code (HR-assigned and unique per company, so an exact
         match cannot be a different person)
      3. the employee's primary key - only where the device opted in

    Rule 3 used to be implicit and was tried *before* the employee code, which
    is how a terminal sending its own local IDs (1..50 is the norm) resolved to
    HRCloudPay's IDs in creation order: employee 7 on the terminal became the
    seventh employee this database happens to know, with no error and no way to
    tell afterwards. Ambiguous enrolment template IDs are still not guessed -
    two people cannot both be that template - and every match stays scoped to
    the device's company.

    Returns (None, '') when nothing matched, including for an empty or absent
    identifier.
    """
    if identifier is None or identifier == '':
        return None, ''
    from biometrics.models import BiometricEnrollment

    identifier = str(identifier)
    template_matches = list(BiometricEnrollment.objects.filter(
        device=device,
        employee__company_id=device.company_id,
        status='active',
        template_id=identifier,
    ).select_related('employee')[:2])
    if len(template_matches) == 1:
        return template_matches[0].employee, 'enrolment'
    if len(template_matches) > 1:
        return None, ''

    policy = device.match_policy
    if policy not in ('code', 'pk'):
        # 'enrolment': nothing but this terminal's own enrolment decides.
        return None, ''

    qs = Employee.objects.filter(company=device.company)
    emp = qs.filter(employee_code__iexact=identifier).first()
    if emp is not None:
        return emp, 'employee_code'

    if policy != 'pk':
        return None, ''
    try:
        pk = int(identifier)
    except (TypeError, ValueError):
        return None, ''
    emp = qs.filter(pk=pk).first()
    if emp is not None:
        return emp, 'pk'
    return None, ''


# Saturday, Sunday - the same convention payroll's absence rules use, so a
# quiet weekend is not mistaken for a broken terminal.
WEEKEND_DAYS = {5, 6}


def _is_working_day(company, day):
    """Whether anyone was expected to clock in on `day`.

    Weekends are excluded by the convention the rest of the app uses, and the
    company's own declared public holidays are excluded because those are the
    days a site is closed and a silent terminal is correct behaviour.
    """
    if day.weekday() in WEEKEND_DAYS:
        return False
    from payroll.models import PublicHoliday

    return not PublicHoliday.objects.filter(company=company, date=day).exists()


def device_health(device, now=None):
    """Whether a terminal is still reporting, and why not if it is not.

    A terminal that stops reporting leaves no trace of its own: attendance for
    everyone who clocks on it simply stops existing, which looks exactly like a
    quiet day until someone runs payroll from memory. So silence is treated as a
    signal, and the answer is one of:

      ok             reporting within the window, or silence that needs no
                     explanation (a weekend, a public holiday)
      silent         nothing for longer than BIOMETRIC_SILENCE_HOURS, and at
                     least one working day has passed since the last punch
      never_seen     registered and active, but has never reported a punch -
                     normally a terminal nobody has pointed at this server yet
      not_monitored  inactive or retired, where silence is deliberate

    This is a staleness window plus a working-day gate, not a schedule engine.
    It deliberately knows nothing about a site's normal daily rhythm beyond
    weekends and holidays: a terminal only used on Fridays reads as silent the
    rest of the week. Callers therefore show the last-seen time beside the
    status, so that judgement stays with a person instead of being hidden by the
    rule.
    """
    now = now or timezone.now()
    if device.status != 'active':
        return {'status': 'not_monitored', 'silence_hours': None,
                'detail': 'Device is %s.' % device.get_status_display()}
    if device.last_seen_at is None:
        return {'status': 'never_seen', 'silence_hours': None,
                'detail': 'No punch has ever been received from this terminal.'}

    hours = (now - device.last_seen_at).total_seconds() / 3600.0
    window = getattr(settings, 'BIOMETRIC_SILENCE_HOURS', 24)
    if hours <= window:
        return {'status': 'ok', 'silence_hours': round(hours, 1), 'detail': ''}

    # Past the window, the only question left is whether anything was expected.
    # Nothing was over a weekend or a public holiday.
    last_day = timezone.localdate(device.last_seen_at)
    today = timezone.localdate(now)
    if today == last_day:
        # The silence is inside the last-seen day, so that day is the one an
        # expectation would have come from.
        candidates = [today]
    else:
        candidates = [last_day + timedelta(days=n)
                      for n in range(1, (today - last_day).days + 1)]
    if not any(_is_working_day(device.company, day) for day in candidates):
        return {'status': 'ok', 'silence_hours': round(hours, 1),
                'detail': 'Quiet since %s, but no working day has passed.'
                          % last_day.isoformat()}

    return {
        'status': 'silent',
        'silence_hours': round(hours, 1),
        'detail': 'No punch for %.0f hours. Last seen %s.'
                  % (hours, timezone.localtime(device.last_seen_at)
                     .strftime('%Y-%m-%d %H:%M')),
    }
