from rest_framework.permissions import SAFE_METHODS, BasePermission

from .billing import AI_DENIAL_MESSAGE, ai_allowed, ai_refusal_body


class IsCompanyMember(BasePermission):
    """Only allow access to authenticated users who belong to a company."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.company_id is not None
        )


class IsCompanyActive(BasePermission):
    """
    Blocks access to core HR/payroll features until the company has
    activated its account (via the emailed activation link) and has a
    valid subscription state.
    """

    message = (
        'Your company account is not yet activated. '
        'Please contact your platform administrator or support so they can '
        'activate your company. Once activated you will have full access to '
        'Integrations, data migration, and all other features.'
    )

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.company_id is not None):
            self.message = 'Authentication required.'
            return False

        company = user.company
        if not company.is_active:
            self.message = (
                'Your company account is not yet activated. '
                'Please contact your platform administrator or support so they can '
                'activate your company. Once activated you will have full access to '
                'Integrations, data migration, and all other features.'
            )
            return False

        from .billing import subscription_state
        state = subscription_state(company)
        if not state.get('allowed', False):
            reason = state.get('reason') or 'Your subscription is not currently active.'
            self.message = (
                f'{reason} '
                'Please contact your platform administrator or update billing '
                'to restore full access.'
            )
            return False

        return True


class IsOwnerOrAdmin(BasePermission):
    """Restricts write actions to owner/admin roles, read-only for others."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in ('owner', 'admin')
        )


class IsOwnerOrAdminOnly(BasePermission):
    """
    Owner/admin only, for ALL methods including reads. Use this on
    company-wide aggregate views (payroll summaries, dashboards) that
    should never be visible to an 'employee'-role self-service login.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in ('owner', 'admin')
        )


class IsOwnerAdminOrRecordOwner(BasePermission):
    """
    Reads are allowed for any company member (queryset scoping decides
    what they actually see). Writes are always allowed for owner/admin.
    An 'employee'-role user may only write a record tied to their own
    Employee profile - checked against the 'employee' field in the
    submitted data (create) or on the object itself (update/delete).
    This closes the gap where a self-service employee login could
    otherwise create or modify another employee's record by simply
    submitting a different employee id.
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.role in ('owner', 'admin'):
            return True
        if request.user.role == 'employee' and hasattr(request.user, 'employee_profile'):
            employee_id = request.data.get('employee')
            return employee_id is not None and str(employee_id) == str(request.user.employee_id)
        return False

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if request.user.role in ('owner', 'admin'):
            return True
        if request.user.role == 'employee' and hasattr(request.user, 'employee_profile'):
            return obj.employee_id == request.user.employee_id
        return False


class CanManageHR(BasePermission):
    """
    Write access for owner/admin/hr - the roles allowed to manage
    employee records, contracts, and allowances/deductions. Read is
    open to any company member; row-level scoping (self-only for
    'employee', department-only for 'department_manager') is handled
    in each view's get_queryset.
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in ('owner', 'admin', 'hr')
        )


class CanManageHROrDepartment(BasePermission):
    """
    Used for Attendance and Leave Requests, which HR manages company-
    wide but a Department Manager may only manage for their own team.

    - owner/admin/hr: full read+write on any record in the company.
    - department_manager: write only permitted when the record's
      employee belongs to `request.user.managed_department`.
    - employee: write only permitted for their own record (via
      IsOwnerAdminOrRecordOwner's rule, mirrored here).
    - Reads are open to any company member; get_queryset scopes what
      each role actually sees.
    """

    def _employee_in_scope(self, request, employee):
        user = request.user
        if user.role in ('owner', 'admin', 'hr'):
            return True
        if user.role == 'department_manager':
            return bool(user.managed_department) and employee.department == user.managed_department
        if user.role == 'employee' and hasattr(user, 'employee_profile'):
            return employee.id == user.employee_id
        return False

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.role in ('owner', 'admin', 'hr'):
            return True
        if user.role in ('department_manager', 'employee'):
            employee_id = request.data.get('employee')
            if employee_id is None:
                return False
            from employees.models import Employee
            try:
                employee = Employee.objects.get(id=employee_id, company=user.company)
            except Employee.DoesNotExist:
                return False
            return self._employee_in_scope(request, employee)
        return False

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return self._employee_in_scope(request, obj.employee)


class CanApproveForDepartment(BasePermission):
    """
    Gates the leave approve/reject actions: owner/admin/hr can approve
    anyone's leave; a department_manager can only approve/reject leave
    for employees in their own managed_department.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in ('owner', 'admin', 'hr', 'department_manager')
        )

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.role in ('owner', 'admin', 'hr'):
            return True
        if user.role == 'department_manager':
            return bool(user.managed_department) and obj.employee.department == user.managed_department
        return False


class CanManagePayroll(BasePermission):
    """
    Payroll is a separate domain from HR: only owner/admin/finance may
    read or write ANYTHING in the payroll app (config, runs, approvals,
    payments, exports, summaries, dashboard). No safe-method bypass -
    HR managers and department managers have zero payroll visibility,
    matching the separation-of-duties split the business asked for.
    Employee-role self-service payslip access is handled separately
    (PayslipViewSet has its own row-level scoping) and does not use
    this permission class.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in ('owner', 'admin', 'finance')
        )


class CanViewCompanyAudit(BasePermission):
    """Sensitive company audit trail: owner/admin/HR/finance only."""
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role in ('owner','admin','hr','finance'))


class CanManageStatutory(BasePermission):
    """Statutory filing workflow: owner/admin/finance only (separation of duties)."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in ('owner', 'admin', 'finance')
        )


class CanManageAIDrafts(BasePermission):
    """
    AI drafts are company-persisted HR documents - employment and warning
    letters, payroll explanations and HR reports - that name identifiable
    employees. Only the roles that can also *review* a draft may create, read or
    review one, so the read path and the write path cannot diverge.

    An 'employee' or 'department_manager' login gets 403 on all methods. This is
    not a no-op guard on the read: the draft serializer returns the full
    `content` and `context`, so an ungated GET exposed warning letters about
    colleagues to every user in the company.
    """

    message = 'You do not have permission to access AI drafts.'

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in ('owner', 'admin', 'hr', 'finance')
        )

class IsAIPlanAvailable(BasePermission):
    """The AI assistant, AI drafts and the knowledge base are paid features.

    Before this existed, every AI endpoint gated on role and company membership
    only, so the cheapest plan could spend unbounded money on model tokens: a
    plan costs a flat amount per company while AI costs per token. A Starter
    tenant could push unlimited documents through the provider and generate
    unlimited drafts for $15 a month.

    403 rather than 402: the rest of this API already treats "your plan does not
    include this" as a permission outcome, and a second status code here would
    have to be handled in two places forever.

    List this *last* in ``permission_classes``, after every role check. DRF
    stops at the first failure, so putting this first would tell a Starter-plan
    ``employee`` to upgrade for a feature their role never allowed anyway.
    """

    message = AI_DENIAL_MESSAGE

    def has_permission(self, request, view):
        user = request.user
        # Leave the "who are you" and "does your company exist" decisions to the
        # permissions listed before this one. Denying here instead would replace
        # their specific messages with this one.
        if not (user and user.is_authenticated and user.company_id is not None):
            return True
        return ai_allowed(user.company)


class AIPlanGateMixin:
    """Widen a plan-gate refusal to include the fields the SPA needs.

    Every AI view mixes this in alongside ``IsAIPlanAvailable``, so the upgrade
    payload is built once instead of in ten views. It lives beside the
    permission rather than in ``ai/`` so the two halves cannot drift apart.

    The permissions are re-evaluated here to learn *which* one refused, rather
    than assuming the plan was the reason. That matters because a refusal for
    some other reason - not authenticated, wrong role, company not activated -
    must keep the plain ``{"detail": ...}`` shape its own permission chose, and
    must not tell the caller to upgrade when upgrading would change nothing.
    """

    def permission_denied(self, request, message=None, code=None):
        from rest_framework.exceptions import PermissionDenied

        user = getattr(request, 'user', None)
        for permission in self.get_permissions():
            if permission.has_permission(request, self):
                continue
            if isinstance(permission, IsAIPlanAvailable):
                raise PermissionDenied(ai_refusal_body(user))
            break
        super().permission_denied(request, message, code)
