"""Reading a month of attendance out of a spreadsheet.

The workflow this exists for: a department manager keeps attendance in a
spreadsheet all month and submits it to HR at the end. That makes this a bulk
write into the same table payroll reads, at the end of a period, from a file
nobody validated - which is exactly the shape of operation where a careless
implementation quietly corrupts data and nobody finds out until payday.

So nothing here writes. This module only ever produces a *plan*: for each row,
whether it would create, update, leave alone, or fail, and why. The caller
shows that to a human before anything is committed, and commits through a
separate endpoint. Validation is per-row and never stops at the first bad line,
because a manager who fixes rows one at a time gives up.
"""
import csv
import io
from datetime import date as date_cls
from datetime import datetime, time as time_cls

# Header spellings seen in the wild. Matching is on a normalised form (lower
# case, underscores and spaces collapsed) so "Check In", "check_in" and
# "CHECK-IN" are the same column.
COLUMN_ALIASES = {
    'employee': ('employee', 'employee code', 'employee id', 'employee name',
                 'staff', 'staff id', 'name', 'full name', 'person'),
    'date': ('date', 'day', 'attendance date', 'work date', 'day date'),
    'status': ('status', 'attendance', 'state', 'attendance status'),
    'check_in': ('check in', 'checkin', 'in', 'time in', 'clock in',
                 'timein', 'sign in'),
    'check_out': ('check out', 'checkout', 'out', 'time out', 'clock out',
                  'timeout', 'sign out'),
    'crossed_midnight': ('crossed midnight', 'next day', 'overnight',
                         'ends next day', 'cross midnight'),
    'notes': ('notes', 'note', 'comment', 'comments', 'remarks', 'reason'),
}

# People type these into spreadsheets. Only unambiguous synonyms are accepted -
# "late" is not the same as "absent" and guessing which one someone meant is how
# a payslip goes wrong.
STATUS_SYNONYMS = {
    'present': 'present', 'p': 'present', 'yes': 'present', 'attended': 'present',
    'absent': 'absent', 'a': 'absent', 'no': 'absent', 'unexcused': 'absent',
    'half day': 'half_day', 'half day leave': 'half_day', 'half': 'half_day',
    'halfday': 'half_day', 'h': 'half_day',
    'leave': 'leave', 'on leave': 'leave', 'l': 'leave', 'annual leave': 'leave',
}

TRUE_VALUES = {'y', 'yes', 'true', '1', 'x', 't'}
FALSE_VALUES = {'n', 'no', 'false', '0', 'f', ''}

MAX_ROWS = 5000

REQUIRED_COLUMNS = ('employee', 'date')


class SpreadsheetError(Exception):
    """The file could not be read as a spreadsheet at all."""


def normalise_header(value):
    text = str(value or '').strip().lower()
    for char in ('_', '-'):
        text = text.replace(char, ' ')
    return ' '.join(text.split())


def detect_columns(header_row):
    """Map our field names onto the file's column positions.

    Returns (mapping, missing). A missing *required* column is a hard stop; a
    missing optional one just means those values stay blank.
    """
    mapping = {}
    for index, raw in enumerate(header_row):
        normalised = normalise_header(raw)
        if not normalised:
            continue
        for field, aliases in COLUMN_ALIASES.items():
            if field in mapping:
                continue
            if normalised in aliases:
                mapping[field] = index
                break
    missing = [field for field in REQUIRED_COLUMNS if field not in mapping]
    return mapping, missing


def read_table(uploaded_file):
    """Return (header_row, rows) from an .xlsx or .csv upload.

    Only the first sheet is read. A manager's month is one table; a workbook
    with a pivot on the second sheet is not something to guess at.
    """
    name = (getattr(uploaded_file, 'name', '') or '').lower()
    try:
        raw = uploaded_file.read()
    except Exception as exc:  # pragma: no cover - defensive
        raise SpreadsheetError(f'Could not read the uploaded file: {exc}')
    if not raw:
        raise SpreadsheetError('The uploaded file is empty.')

    if name.endswith('.csv'):
        text = raw.decode('utf-8-sig', errors='replace')
        reader = csv.reader(io.StringIO(text))
        all_rows = [row for row in reader if any(str(c).strip() for c in row)]
    elif name.endswith(('.xlsx', '.xlsm')):
        try:
            from openpyxl import load_workbook
            workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
            sheet = workbook.worksheets[0]
            all_rows = [
                [cell for cell in row]
                for row in sheet.iter_rows(values_only=True)
                if any(c is not None and str(c).strip() for c in row)
            ]
            workbook.close()
        except SpreadsheetError:
            raise
        except Exception as exc:
            raise SpreadsheetError(
                f'That .xlsx file could not be opened: {exc}. If it was created '
                'in Excel, save it as .xlsx rather than .xls or .csv.'
            )
    else:
        raise SpreadsheetError(
            'Unsupported file type. Upload an .xlsx or a .csv.'
        )

    if not all_rows:
        raise SpreadsheetError('The uploaded file has no rows.')
    if len(all_rows) < 2:
        raise SpreadsheetError(
            'The file has a header row but no data rows. That is what an '
            'unmodified template looks like - fill in the Attendance sheet '
            'first.'
        )
    return all_rows[0], all_rows[1:]


def parse_date(value):
    """Accept the several ways a date arrives from a spreadsheet."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date_cls):
        return value
    text = str(value or '').strip()
    if not text:
        return None
    for pattern in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y',
                    '%d-%b-%Y', '%Y/%m/%d', '%d.%m.%Y'):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def parse_time(value):
    """Return (time, had_explicit_clock) or (None, False).

    Excel returns a datetime for a date-time cell and a time for a time cell, so
    both shapes have to be handled. `had_explicit_clock` distinguishes "the cell
    said 09:00" from "the cell said nothing", because those mean different
    things when deciding whether a second time is missing.
    """
    if isinstance(value, datetime):
        return value.time(), True
    if isinstance(value, time_cls):
        return value, True
    text = str(value or '').strip()
    if not text:
        return None, False
    for pattern in ('%H:%M', '%H:%M:%S', '%I:%M %p', '%I:%M:%S %p'):
        try:
            return datetime.strptime(text.upper(), pattern).time(), True
        except ValueError:
            continue
    return None, False


def parse_status(value):
    text = normalise_header(value)
    if not text:
        return None
    return STATUS_SYNONYMS.get(text)


def parse_bool(value):
    text = normalise_header(value)
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    return None


def resolve_employee(company, value, cache):
    """Find an employee from whatever the manager typed.

    Employee code first, then email, then full name - in that order of
    unambiguity. Names collide and email can be typed with a stray space, so
    neither can be the primary key. Resolution is restricted to the company,
    and an unmatched value returns None rather than the nearest match: a
    "did you mean" here would silently record the wrong person.
    """
    from employees.models import Employee

    key = str(value or '').strip()
    if not key:
        return None, 'employee is blank'
    if key in cache:
        return cache[key], cache.get(f'__err__{key}')
    lowered = key.lower()

    employee = Employee.objects.filter(company=company, employee_code__iexact=key).first()
    if employee is None and '@' in key:
        employee = Employee.objects.filter(company=company, email__iexact=key).first()
    if employee is None:
        matches = list(
            Employee.objects.filter(company=company, first_name__iexact=key)
            .values_list('id', flat=True)[:2]
        )
        if len(matches) == 1:
            employee = Employee.objects.filter(id=matches[0]).first()
        elif len(matches) > 1:
            cache[key] = None
            cache[f'__err__{key}'] = f'"{key}" matches {len(matches)} people; use the employee code'
            return None, cache[f'__err__{key}']

    if employee is None:
        cache[key] = None
        cache[f'__err__{key}'] = f'no employee in this company matches "{key}"'
        return None, cache[f'__err__{key}']
    cache[key] = employee
    return employee, None


def build_plan(company, uploaded_file, scope_check, filename=None):
    """Parse and validate a file into a per-row plan. Writes nothing.

    `scope_check(employee)` decides whether the caller may record attendance for
    that employee; rows failing it are reported rather than dropped, because a
    manager who uploads their whole department and gets a short count back has
    no way to tell a permission problem from a typo.
    """
    header_row, raw_rows = read_table(uploaded_file)
    mapping, missing = detect_columns(header_row)
    if missing:
        raise SpreadsheetError(
            'The file is missing required column(s): '
            + ', '.join(missing)
            + '. Download the template to get the expected headings.'
        )

    if len(raw_rows) > MAX_ROWS:
        raise SpreadsheetError(
            f'The file has {len(raw_rows)} rows; the limit is {MAX_ROWS}. '
            'Upload one department-month at a time.'
        )

    from .models import Attendance

    plan = []
    employee_cache = {}
    seen = {}

    def cell(row, field):
        index = mapping.get(field)
        if index is None or index >= len(row):
            return None
        return row[index]

    for offset, row in enumerate(raw_rows):
        number = offset + 2  # row 1 is the header
        errors = []

        employee, employee_error = resolve_employee(
            company, cell(row, 'employee'), employee_cache)
        if employee_error:
            errors.append(employee_error)

        day = parse_date(cell(row, 'date'))
        if day is None:
            errors.append('date is missing or not a date we recognise')

        status = parse_status(cell(row, 'status'))
        if status is None:
            if cell(row, 'status') not in (None, ''):
                errors.append(
                    f'status "{cell(row, "status")}" is not one of present, '
                    'absent, half day, leave')
            else:
                status = 'present'
                errors.append('status is blank; assuming present')

        check_in, _had_in = parse_time(cell(row, 'check_in'))
        check_out, _had_out = parse_time(cell(row, 'check_out'))
        crossed = parse_bool(cell(row, 'crossed_midnight')) or False

        if check_out and not check_in:
            errors.append('a check-out was given with no check-in')
        if check_in and check_out:
            if crossed and check_out > check_in:
                errors.append(
                    'marked as ending next day, but the check-out is later '
                    'than the check-in on the same day')
            elif not crossed and check_out < check_in:
                errors.append(
                    'the check-out is earlier than the check-in; tick the '
                    'next-day column if the shift ends the following day')

        notes = str(cell(row, 'notes') or '').strip()[:255]

        action = 'error' if errors else 'create'
        existing = None
        if not errors and employee is not None and day is not None:
            key = (employee.id, day)
            if key in seen:
                errors.append(
                    'this employee and date appear more than once in the file; '
                    'only the first is used')
                action = 'error'
            else:
                seen[key] = True
                existing = Attendance.objects.filter(
                    employee=employee, date=day).first()
                if existing is not None:
                    unchanged = (
                        existing.status == status
                        and existing.check_in == check_in
                        and existing.check_out == check_out
                        and existing.crossed_midnight == crossed
                    )
                    action = 'unchanged' if unchanged else 'update'

        if employee is not None and not any('not in scope' in e for e in errors):
            if not scope_check(employee):
                errors.append('you cannot record attendance for this employee')
                action = 'error'

        plan.append({
            'row': number,
            'employee_ref': str(cell(row, 'employee') or ''),
            'employee_id': employee.id if employee else None,
            'employee_name': employee.full_name if employee else '',
            'date': day.isoformat() if day else None,
            'status': status,
            'check_in': check_in.strftime('%H:%M') if check_in else None,
            'check_out': check_out.strftime('%H:%M') if check_out else None,
            'crossed_midnight': crossed,
            'notes': notes,
            'action': action,
            'errors': errors,
        })

    summary = {
        'create': sum(1 for p in plan if p['action'] == 'create'),
        'update': sum(1 for p in plan if p['action'] == 'update'),
        'unchanged': sum(1 for p in plan if p['action'] == 'unchanged'),
        'error': sum(1 for p in plan if p['action'] == 'error'),
    }
    return {
        'filename': filename or getattr(uploaded_file, 'name', ''),
        'columns': {field: header_row[index] if index < len(header_row) else ''
                    for field, index in mapping.items()},
        'rows': plan,
        'summary': summary,
        'total_rows': len(plan),
    }


TEMPLATE_HEADERS = [
    'employee_code', 'date', 'status', 'check_in', 'check_out',
    'crossed_midnight', 'notes',
]

TEMPLATE_EXAMPLE = [
    ['EMP-001', '2026-09-01', 'present', '09:00', '17:00', 'no', ''],
    ['EMP-001', '2026-09-02', 'present', '09:00', '19:30', 'no', 'Long day'],
    ['EMP-002', '2026-09-01', 'leave', '', '', 'no', 'Approved annual leave'],
    ['EMP-002', '2026-09-03', 'absent', '', '', 'no', 'No contact'],
    ['EMP-003', '2026-09-05', 'present', '22:00', '06:00', 'yes', 'Night shift'],
]


def build_template():
    """An .xlsx the manager fills in, so the headings are never a guess.

    The example rows live on a second sheet. Putting them on the sheet that gets
    filled in would mean an unmodified template previews as five rows that all
    fail to resolve to an employee - which teaches the manager that the format
    is broken by showing them its own error output. As it is, uploading the
    untouched template gives "a header row but no data rows", which is true.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Attendance'
    sheet.append(TEMPLATE_HEADERS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for column, width in zip('ABCDEFG', (16, 12, 12, 10, 10, 18, 28)):
        sheet.column_dimensions[column].width = width

    example = workbook.create_sheet('Example')
    example.append(TEMPLATE_HEADERS)
    for row in TEMPLATE_EXAMPLE:
        example.append(row)

    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    buffer.seek(0)
    return buffer