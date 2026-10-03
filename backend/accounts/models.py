import uuid

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ObjectDoesNotExist
from django.db import models

PLAN_CHOICES = [
    ('starter', 'Starter'),
    ('business', 'Business'),
    ('professional', 'Professional'),
    ('scale', 'Scale'),
    ('enterprise', 'Enterprise'),
]

# Ceiling on employee records a company may hold, by plan. `None` means
# unlimited. Ordering in PLAN_CHOICES is the upgrade ladder, so a new tier must
# be inserted between the tiers it sits between rather than appended.
#
# Starter carries 30 employees rather than 10 because the old 10 ceiling put a
# cliff in the middle of the commonest small-business size: a company with 12
# employees had to jump from $15 to $49 for 2 spare seats. Starter and Business
# are now separated mostly on capability (Business adds attendance, leave and
# reports) rather than capacity, which matches how the public pricing page
# describes them.
PLAN_EMPLOYEE_LIMITS = {
    'starter': 30,
    'business': 50,
    'professional': 150,
    'scale': 400,
    'enterprise': None,  # unlimited
}


class Company(models.Model):
    """
    A tenant on the platform. Every user, employee, and payroll record
    belongs to exactly one company. All API querysets must be filtered
    by company to keep tenants isolated from each other.
    """
    name = models.CharField(max_length=255)
    country = models.CharField(max_length=100, blank=True)
    address = models.CharField(max_length=255, blank=True, help_text='Shown on payslips and printed HR forms')
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=30, blank=True)

    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='starter')

    # Company branding: uploaded by the owner/admin and rendered on payslips,
    # break-request forms and other printed HR documents. Each company owns its
    # own logo so the same shared platform feels like a native part of their business.
    logo = models.ImageField(
        upload_to='company_logos/%Y/%m/',
        blank=True, null=True,
        max_length=500,
        help_text='Company logo shown on payslips and break request forms.',
    )

    is_active = models.BooleanField(default=False)
    activation_token = models.UUIDField(default=uuid.uuid4, editable=False)

    # Set to True once the company has completed the post-activation
    # payroll onboarding form (tax brackets, contributions, currency).
    payroll_configured = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    @property
    def employee_limit(self):
        return PLAN_EMPLOYEE_LIMITS.get(self.plan)


ROLE_CHOICES = [
    ('owner', 'Owner'),
    ('admin', 'Admin'),
    ('hr', 'HR Manager'),
    ('finance', 'Finance Manager'),
    ('department_manager', 'Department Manager'),
    ('employee', 'Employee'),
]


class User(AbstractUser):
    """
    Custom user tied to a Company. Every user is created under a
    company - there is no public/independent user signup, only company
    registration (which creates the 'owner') and staff invites created
    by an owner/admin from inside the app (see accounts/views.py
    CompanyUsersView).

    Roles:
      - owner / admin: full access to everything for the company.
      - hr: manages employees, contracts, attendance, and leave -
            no payroll/financial access.
      - finance: manages payroll config, runs, approvals, payments,
            and reports - no employee-record editing access.
      - department_manager: scoped HR-lite access limited to the
            employees in `managed_department`.
      - employee: self-service only (own profile, attendance, leave,
            payslips).
    """
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='users',
        null=True, blank=True,
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='owner')

    # Only meaningful when role == 'department_manager'. Free-text to
    # match Employee.department, since departments aren't a separate
    # model in this MVP.
    managed_department = models.CharField(max_length=150, blank=True)

    @property
    def employee_id(self):
        """PK of the linked Employee record, or None when the user has no profile.

        The reverse side of a OneToOneField (``Employee.user`` with
        ``related_name='employee_profile'``) exposes the related *object* only --
        Django never creates a matching ``employee_profile_id`` attribute on this
        model. Use this property instead of ``user.employee_profile_id``.
        """
        try:
            return self.employee_profile.id
        except ObjectDoesNotExist:
            # Raised by the reverse descriptor when no Employee is linked.
            return None

    def __str__(self):
        return self.username

# Platform control-center models live in a separate module to keep the tenant
# models above stable and easy to read.
from .platform_models import Subscription, AuditLog, SuspensionEvent, PlatformNotification, SupportTicket, PaymentProviderConfig, PaymentEvent, PaymentPlan, PaymentTransaction  # noqa: E402,F401
