"""Which stored file a requester is allowed to download.

Every uploaded file lives under a prefix set by its model's ``upload_to``. That
prefix is the only thing tying a URL to a database row, so this module turns a
storage name back into the object that owns it and then applies the same
role rules the rest of the app uses.

Why this exists at all: ``urls.py`` used to serve ``/media/`` with Django's
``static()`` helper, and only while ``DEBUG`` was true. So in production no
uploaded file was reachable at all, and the obvious "fix" - registering the same
route unconditionally - would have served every employee's identity document,
contract, medical certificate and disciplinary letter to anyone who could guess
or harvest the URL. Those objects are keyed by content-hashed-ish filenames
under a date directory, which is obscurity, not access control.

The rules below are deliberately per-kind rather than a single tenant check,
because the kinds are not equally sensitive within one company:

* ``imports/`` holds a raw employee-data export. Owner/admin only.
* ``employee_documents/`` holds identity, medical and disciplinary scans.
  HR roles and the employee themselves; explicitly *not* ``finance``, which
  holds payroll authority but no employee-record access.
* ``contracts/`` and ``warning_letters/`` follow the employee's manager or the
  employee. HR plus self.
* ``employee_photos/`` is a profile picture: self, HR, or the department
  manager who already sees the employee in their team list.
* ``ai_knowledge/`` is the raw uploaded source behind RAG. Restricted to the
  roles that may manage the knowledge base.
* ``company_logos/`` is a brand asset rendered on that company's own payslips,
  so any member of the company may fetch it.
"""
from dataclasses import dataclass

from django.apps import apps

# Roles with authority over employee records inside their own company. This
# mirrors the vocabulary in ai.access.MANAGE_KNOWLEDGE_ROLES rather than
# restating a literal, so the two cannot drift.
HR_ROLES = frozenset({'owner', 'admin', 'hr'})
COMPANY_ADMIN_ROLES = frozenset({'owner', 'admin'})


@dataclass(frozen=True)
class MediaKind:
    """One class of stored file and how to find the row that owns it."""

    prefix: str
    app_label: str
    model: str
    field: str
    label: str


# Order matters only in that no prefix is a prefix of another; they are all
# distinct directory names, so a simple first-match is well defined.
MEDIA_KINDS = (
    MediaKind('employee_documents/', 'employees', 'EmployeeDocument', 'document', 'employee document'),
    MediaKind('contracts/', 'employees', 'Contract', 'document', 'contract'),
    MediaKind('warning_letters/', 'employees', 'WarningLetter', 'document', 'warning letter'),
    MediaKind('employee_photos/', 'employees', 'Employee', 'profile_photo', 'profile photo'),
    MediaKind('imports/', 'integrations', 'ImportJob', 'uploaded_file', 'import file'),
    MediaKind('ai_knowledge/', 'ai', 'KnowledgeDocument', 'source_file', 'knowledge source'),
    MediaKind('company_logos/', 'accounts', 'Company', 'logo', 'company logo'),
)

UNKNOWN_KIND_LABEL = 'file'


def kind_for(name):
    """The MediaKind a storage name falls under, or None if it is not ours."""
    for kind in MEDIA_KINDS:
        if name.startswith(kind.prefix):
            return kind
    return None


def owner_of(name):
    """Return ``(kind, instance)`` for a storage name.

    ``instance`` is None when the name is under a known prefix but no row
    references it - a file left behind by a rollback, or a name that has been
    tampered with. Callers must treat that as a miss, never as a pass.
    """
    kind = kind_for(name)
    if kind is None:
        return None, None
    model = apps.get_model(kind.app_label, kind.model)
    try:
        instance = model._default_manager.filter(**{kind.field: name}).first()
    except Exception:
        # A malformed name can raise inside the ORM's own validation. A media
        # URL is attacker-controlled, so this must not propagate as a 500.
        return kind, None
    return kind, instance


def _company_of(kind, instance):
    if kind.model == 'Company':
        return instance
    company = getattr(instance, 'company', None)
    if company is not None:
        return company
    employee = getattr(instance, 'employee', None)
    if employee is not None:
        return getattr(employee, 'company', None)
    return None


def _is_the_employee(user, instance, kind):
    """Whether the requester is the person this file belongs to."""
    if kind.model == 'Employee':
        employee = instance
    else:
        employee = getattr(instance, 'employee', None)
    if employee is None:
        return False
    # Employee.user is a nullable OneToOne, so an employee record with no
    # linked login can never be "self".
    return bool(employee.user_id) and employee.user_id == user.pk


def _is_in_managers_team(user, instance, kind):
    """A department manager may see files for employees they manage."""
    if not user.managed_department:
        return False
    employee = instance if kind.model == 'Employee' else getattr(instance, 'employee', None)
    if employee is None:
        return False
    return bool(employee.department) and employee.department == user.managed_department


def may_access(user, name):
    """Whether ``user`` may download the stored file called ``name``.

    Returns True only when the name maps to a real row *and* the requester's
    role permits it for that kind of file.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return False

    kind, instance = owner_of(name)
    if kind is None or instance is None:
        return False

    # A platform superuser is a deliberate exception. The platform console
    # already administers every tenant, and a support engineer with no way to
    # retrieve a customer's broken upload cannot do their job. It is called out
    # here because it is the one rule in this file that crosses a tenant
    # boundary; `is_staff` alone is NOT enough, because staff is also set for
    # ordinary company users.
    if user.is_superuser:
        return True

    company = _company_of(kind, instance)
    if company is None or not user.company_id or user.company_id != company.pk:
        return False

    label = kind.label

    if label == 'company logo':
        # A brand asset on this company's own payslips and forms, so every
        # member of the company may fetch it.
        return True

    if label == 'import file':
        # A raw employee-data export. Narrowest rule in the file.
        return user.role in COMPANY_ADMIN_ROLES

    if label == 'knowledge source':
        # The raw uploaded source behind retrieval. Same roles that may manage
        # the knowledge base.
        return user.role in HR_ROLES

    if user.role in HR_ROLES:
        # Contracts, warning letters, employee documents and profile photos:
        # every HR role sees all of them for their own company.
        return True

    if label == 'profile photo':
        return _is_the_employee(user, instance, kind) or (
            user.role == 'department_manager' and _is_in_managers_team(user, instance, kind)
        )

    # contracts, warning letters, employee documents: the employee may see
    # their own. `finance` deliberately does not - it holds payroll authority
    # but no employee-record access, and these are identity, medical and
    # disciplinary documents.
    return _is_the_employee(user, instance, kind)
