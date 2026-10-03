"""Read-only, permission-aware HRCloudPay AI tools.

These tools deliberately execute server-side. The model never receives database credentials
and never performs writes. Every queryset is tenant-scoped to the authenticated user.
"""
from datetime import timedelta
from decimal import Decimal
import json
import logging
import re

from django.db.models import Q, Sum
from django.utils import timezone

logger = logging.getLogger(__name__)


def _scope_employees(user, qs):
    qs = qs.filter(company=user.company)
    if user.role == 'employee':
        return qs.filter(user=user)
    if user.role == 'department_manager':
        return qs.filter(department_obj__name=user.managed_department)
    return qs


def _can(user, area):
    if user.role in ('owner', 'admin'):
        return True
    if area in ('employee', 'leave', 'attendance') and user.role in ('hr', 'department_manager', 'employee'):
        return True
    if area == 'payroll' and user.role == 'finance':
        return True
    return False


def employee_summary(user):
    from employees.models import Employee
    if not _can(user, 'employee'):
        return {'error': 'You do not have permission to view workforce data.'}
    qs = _scope_employees(user, Employee.objects.all())
    active = qs.filter(employment_status='active').count()
    terminated = qs.filter(employment_status='terminated').count()
    return {'tool': 'employee_summary', 'total': qs.count(), 'active': active, 'terminated': terminated}


def current_leave(user):
    from leave.models import LeaveRequest
    if not _can(user, 'leave'):
        return {'error': 'You do not have permission to view leave data.'}
    today = timezone.localdate()
    qs = LeaveRequest.objects.filter(
        employee__company=user.company, status='approved', start_date__lte=today, end_date__gte=today,
    ).select_related('employee')
    if user.role == 'employee':
        qs = qs.filter(employee__user=user)
    elif user.role == 'department_manager':
        qs = qs.filter(employee__department_obj__name=user.managed_department)
    rows = [{'employee': r.employee.full_name, 'leave_type': r.get_leave_type_display(),
             'start_date': r.start_date.isoformat(), 'end_date': r.end_date.isoformat()} for r in qs[:100]]
    return {'tool': 'current_leave', 'count': len(rows), 'employees': rows}


def expiring_contracts(user, days=30):
    from employees.models import Contract
    if not _can(user, 'employee'):
        return {'error': 'You do not have permission to view contract data.'}
    days = max(1, min(int(days), 365))
    today = timezone.localdate()
    until = today + timedelta(days=days)
    qs = Contract.objects.filter(employee__company=user.company, end_date__gte=today, end_date__lte=until).select_related('employee')
    if user.role == 'employee':
        qs = qs.filter(employee__user=user)
    elif user.role == 'department_manager':
        qs = qs.filter(employee__department_obj__name=user.managed_department)
    rows = [{'employee': c.employee.full_name, 'contract_type': c.get_contract_type_display(),
             'end_date': c.end_date.isoformat()} for c in qs.order_by('end_date')[:100]]
    return {'tool': 'expiring_contracts', 'days': days, 'count': len(rows), 'contracts': rows}


def payroll_overview(user):
    from payroll.models import PayrollRun, Payslip
    if not _can(user, 'payroll'):
        return {'error': 'Payroll and compensation data is restricted to authorized payroll roles.'}
    run = PayrollRun.objects.filter(company=user.company).order_by('-period_end', '-id').first()
    if not run:
        return {'tool': 'payroll_overview', 'message': 'No payroll runs exist for this company.'}
    totals = run.payslips.aggregate(gross=Sum('gross_salary'), net=Sum('net_salary'), tax=Sum('tax_amount'), deductions=Sum('total_other_deductions'))
    return {
        'tool': 'payroll_overview', 'period_start': run.period_start.isoformat(), 'period_end': run.period_end.isoformat(),
        'status': run.status, 'payslips': run.payslips.count(),
        'gross': str(totals['gross'] or Decimal('0')), 'net': str(totals['net'] or Decimal('0')),
        'tax': str(totals['tax'] or Decimal('0')), 'other_deductions': str(totals['deductions'] or Decimal('0')),
    }


def attendance_summary(user):
    from attendance.models import Attendance
    if not _can(user, 'attendance'):
        return {'error': 'You do not have permission to view attendance data.'}
    today = timezone.localdate()
    first = today.replace(day=1)
    qs = Attendance.objects.filter(employee__company=user.company, date__gte=first, date__lte=today)
    if user.role == 'employee':
        qs = qs.filter(employee__user=user)
    elif user.role == 'department_manager':
        qs = qs.filter(employee__department_obj__name=user.managed_department)
    values = {status: qs.filter(status=status).count() for status in ('present', 'absent', 'half_day', 'leave')}
    return {'tool': 'attendance_summary', 'from': first.isoformat(), 'to': today.isoformat(), 'records': qs.count(), **values}



_LOOKUP_PHRASE = re.compile(
    r'^(?:.*?\b(?:about|find|search for|details for|details on|profile for|profile of|'
    r'info on|info for|lookup for|look up|record for|records for)\s+)+(.+)$',
    re.I,
)
_MAX_QUERY_WORDS = 6


def person_from_prompt(prompt):
    """Extract a likely person name/email from a natural-language request.

    Returns None when the prompt does not clearly ask about a specific person, so
    the caller can fall through to another tool instead of running a pointless
    employee query. Chained phrases ("find details for Awa Diallo") are stripped
    down to the trailing name.
    """
    text = (prompt or '').strip()
    if not text:
        return None
    match = _LOOKUP_PHRASE.match(text)
    if not match:
        return None
    candidate = re.sub(r'\s+', ' ', match.group(1)).strip(" .,?!'\"")
    if not candidate or len(candidate) > 80 or len(candidate.split()) > _MAX_QUERY_WORDS:
        return None
    if any(char.isdigit() for char in candidate):
        return None
    return candidate


def employee_lookup(user, query):
    """Look up employees by a bare name or email.

    Takes the search term itself, not a whole prompt, so it behaves the same
    whether it is called by the model's tool-calling path (which passes a name)
    or by the deterministic router (which extracts the name first).
    """
    from employees.models import Employee
    if not _can(user, 'employee'):
        return {'error': 'You do not have permission to view employee data.'}
    name = re.sub(r'\s+', ' ', str(query or '')).strip(" .,?!'\"")
    if not name:
        return {'error': 'A person name or email is required to search for an employee.'}

    # Match per token, requiring every token to appear somewhere in the record.
    # Testing the whole string against a single column cannot match a full name:
    # "Awa Diallo" is not a substring of first_name="Awa" or last_name="Diallo",
    # so the natural way to ask for a person found nobody at all.
    tokens = [token for token in name.split() if token]
    condition = Q()
    for token in tokens:
        condition &= (
            Q(first_name__icontains=token) | Q(last_name__icontains=token) | Q(email__icontains=token)
        )
    qs = _scope_employees(user, Employee.objects.all()).filter(condition)
    rows = []
    for e in qs[:10]:
        rows.append({'employee_code': e.employee_code, 'name': e.full_name, 'job_title': e.job_title,
                     'department': e.effective_department, 'employment_status': e.employment_status,
                     'hire_date': e.hire_date.isoformat() if e.hire_date else None})
    return {'tool': 'employee_lookup', 'query': name, 'count': len(rows), 'employees': rows}


def attendance_today(user):
    from attendance.models import Attendance
    if not _can(user, 'attendance'):
        return {'error': 'You do not have permission to view attendance data.'}
    today = timezone.localdate()
    qs = Attendance.objects.filter(employee__company=user.company, date=today).select_related('employee')
    if user.role == 'employee':
        qs = qs.filter(employee__user=user)
    elif user.role == 'department_manager':
        qs = qs.filter(employee__department_obj__name=user.managed_department)
    rows = [{'employee': a.employee.full_name, 'status': a.get_status_display(),
             'check_in': a.check_in.isoformat() if a.check_in else None,
             'check_out': a.check_out.isoformat() if a.check_out else None} for a in qs[:200]]
    return {'tool': 'attendance_today', 'date': today.isoformat(), 'count': len(rows), 'records': rows}


def detect_and_run(user, prompt):
    """Small deterministic router: only known read-only operations can execute.
    Returns (tool_name, result) or (None, None)."""
    text = prompt.lower()
    # A named-person request is the most specific signal we have, so it wins - but
    # only when it actually matches somebody, otherwise fall through to the other
    # routes (and ultimately the model) rather than answering "0 employees found".
    candidate = person_from_prompt(prompt)
    if candidate:
        lookup = employee_lookup(user, candidate)
        if lookup.get('count'):
            return 'employee_lookup', lookup
    if re.search(r'\b(how many|number|total|count)\b.*\b(employee|employees|staff|workforce)\b|\b(employee|employees)\b.*\b(count|number|total)\b', text):
        return 'employee_summary', employee_summary(user)
    if re.search(r'\b(on leave|currently.*leave|who.*leave|employees.*leave)\b', text):
        return 'current_leave', current_leave(user)
    if re.search(r'\b(contract|contracts)\b.*\b(expir|ending|expire)\b|\b(expir|ending)\b.*\bcontract', text):
        m = re.search(r'(\d{1,3})\s*(?:day|days)', text)
        return 'expiring_contracts', expiring_contracts(user, int(m.group(1)) if m else 30)
    if re.search(r'\b(payroll|pay run|payslip|salary|salaries|gross|net pay)\b.*\b(overview|summary|total|last|latest|month|period)\b|\b(payroll overview|payroll summary)\b', text):
        return 'payroll_overview', payroll_overview(user)
    if re.search(r'\b(who|which|list).*\b(absent|present|late|half day)\b.*\b(today|now)\b|\b(absent today|present today)\b', text):
        return 'attendance_today', attendance_today(user)
    if re.search(r'\b(attendance|absent|present|late|half day)\b.*\b(summary|overview|this month|today|report)\b|\battendance summary\b', text):
        return 'attendance_summary', attendance_summary(user)
    return None, None

# OpenAI-compatible tool definitions used by NVIDIA NIM. The functions are read-only
# and are executed only by Django after tenant/role checks inside the functions above.
AI_TOOL_DEFINITIONS = [
    {'type': 'function', 'function': {'name': 'employee_summary', 'description': 'Get the current company employee count and active/terminated counts.', 'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}},
    {'type': 'function', 'function': {'name': 'employee_lookup', 'description': 'Find employees by a person name or email. Use a narrow search term.', 'parameters': {'type': 'object', 'properties': {'query': {'type': 'string', 'description': 'Employee name or email to search for.'}}, 'required': ['query'], 'additionalProperties': False}}},
    {'type': 'function', 'function': {'name': 'current_leave', 'description': 'List employees who are currently on approved leave.', 'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}},
    {'type': 'function', 'function': {'name': 'expiring_contracts', 'description': 'List contracts expiring within a requested number of days.', 'parameters': {'type': 'object', 'properties': {'days': {'type': 'integer', 'minimum': 1, 'maximum': 365}}, 'additionalProperties': False}}},
    {'type': 'function', 'function': {'name': 'payroll_overview', 'description': 'Get the latest payroll run totals. Restricted to authorized payroll roles.', 'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}},
    {'type': 'function', 'function': {'name': 'attendance_summary', 'description': 'Get attendance totals for the current month through today.', 'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}},
    {'type': 'function', 'function': {'name': 'attendance_today', 'description': 'List today\'s attendance records visible to the current user.', 'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}},
]


def execute_ai_tool(user, name, arguments):
    """Execute exactly one allow-listed, read-only tool after server-side authorization.

    Tool arguments come straight from the model, so this boundary is untrusted: any
    failure is reported back as structured tool output rather than propagating, because
    an exception here would otherwise surface to the user as an HTTP 500 mid-chat.
    """
    args = arguments or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    if not isinstance(args, dict):
        return {'error': 'The requested tool arguments were invalid.'}
    try:
        days = max(1, min(int(args.get('days', 30)), 365))
    except (TypeError, ValueError):
        days = 30
    registry = {
        'employee_summary': lambda: employee_summary(user),
        'employee_lookup': lambda: employee_lookup(user, str(args.get('query', ''))),
        'current_leave': lambda: current_leave(user),
        'expiring_contracts': lambda: expiring_contracts(user, days),
        'payroll_overview': lambda: payroll_overview(user),
        'attendance_summary': lambda: attendance_summary(user),
        'attendance_today': lambda: attendance_today(user),
    }
    fn = registry.get(name)
    if not fn:
        return {'error': 'Requested AI tool is not available.'}
    try:
        return fn()
    except Exception:
        logger.exception('AI tool %s failed for user %s', name, getattr(user, 'id', None))
        return {'error': 'That HRCloudPay tool could not be completed. Answer without it.'}
