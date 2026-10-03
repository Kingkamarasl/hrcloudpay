"""Single source of truth for AI feature access rules.

Both the read path (which chunks a user may retrieve) and the write path (which
roles an admin may grant access to) resolve their role vocabulary from here. The
list used to be duplicated across ``knowledge_views``, ``models`` and ``services``
and drifted out of sync with ``User.ROLE_CHOICES``, which left the real
``finance`` and ``department_manager`` roles permanently ungrantable while a
phantom ``manager`` role was accepted but matched no user.
"""
from accounts.models import ROLE_CHOICES

# Every role a company user can actually hold. Derived from the model so it can
# never drift again.
ALL_COMPANY_ROLES = [role for role, _label in ROLE_CHOICES]

# Roles that may create, edit, archive, delete and reindex knowledge documents.
MANAGE_KNOWLEDGE_ROLES = {'owner', 'admin', 'hr'}

# Roles that may generate, read and review AI drafts. Drafts are company-persisted
# HR documents (employment and warning letters, payroll explanations, HR reports)
# that name identifiable employees, so this is the same set that may review them.
MANAGE_DRAFT_ROLES = ('owner', 'admin', 'hr', 'finance')


def parse_allowed_roles(value):
    """Normalise a submitted ``allowed_roles`` value to a clean list of real roles.

    Accepts the comma-joined string used by the upload form and the JSON list used
    by the API. Returns ``None`` when nothing valid was supplied, which callers
    must treat as a 400: an absent or empty selection must never silently widen to
    company-wide access.
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = [part.strip() for part in value.split(',') if part.strip()]
    if not isinstance(value, list):
        return None
    cleaned = [str(item) for item in value if str(item) in ALL_COMPANY_ROLES]
    # Preserve declaration order while removing duplicates.
    return list(dict.fromkeys(cleaned)) or None


def document_accessible_to(user, document):
    """Whether ``user`` may retrieve content from ``document``.

    An empty ``allowed_roles`` on a legacy row means "company-wide", which is how
    such rows were interpreted before the allow-list was validated on write. New
    and updated rows always carry an explicit list.
    """
    allowed = document.allowed_roles or ALL_COMPANY_ROLES
    return user.role in allowed


def can_manage_knowledge(user):
    return user.role in MANAGE_KNOWLEDGE_ROLES


def can_manage_drafts(user):
    return user.role in MANAGE_DRAFT_ROLES
