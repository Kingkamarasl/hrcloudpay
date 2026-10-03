from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from accounts.models import Company

EMPLOYMENT_STATUS_CHOICES = [
    ('active', 'Active'),
    ('terminated', 'Terminated'),
]

EMPLOYMENT_CATEGORY_CHOICES = [
    ('casual', 'Casual'),
    ('short_time', 'Short time'),
    ('long_time', 'Long time'),
]

# System employee ID prefixes by category: CA#### / ST#### / LT####
EMPLOYMENT_CATEGORY_PREFIX = {
    'casual': 'CA',
    'short_time': 'ST',
    'long_time': 'LT',
}


class Department(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='departments')
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='unique_department_per_company'),
        ]
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def employee_count(self):
        return self.employees.count()


class Employee(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='employees')
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='employee_profile',
    )

    employee_code = models.CharField(max_length=30, help_text='Internal employee ID, unique per company')
    id_card_no = models.CharField(max_length=80, blank=True, help_text='National/employee identification number')
    profile_photo = models.ImageField(
        upload_to='employee_photos/%Y/%m/',
        blank=True,
        null=True,
        help_text='Employee profile picture',
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)

    job_title = models.CharField(max_length=150, blank=True)
    department = models.CharField(max_length=150, blank=True)  # backward-compatible legacy field
    department_obj = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='employees',
    )

    base_salary = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    hire_date = models.DateField(null=True, blank=True)
    employment_status = models.CharField(
        max_length=20, choices=EMPLOYMENT_STATUS_CHOICES, default='active',
    )
    employment_category = models.CharField(
        max_length=20,
        choices=EMPLOYMENT_CATEGORY_CHOICES,
        default='long_time',
        help_text='Determines system employee ID prefix: CA (casual), ST (short time), LT (long time).',
    )
    pay_point = models.CharField(max_length=150, blank=True, help_text='Work site/duty station shown on payslips and leave forms')
    bank_account_number = models.CharField(max_length=50, blank=True, help_text='Shown on payslips - account number only, never full banking credentials')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['company', 'employee_code'], name='unique_employee_code_per_company'),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.company.name})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @classmethod
    def allocate_employee_code(cls, company, category: str) -> str:
        """Category prefix + hyphen + four random digits, e.g. ST-4821, LT-0937, CA-7610."""
        import random
        import time
        prefix = EMPLOYMENT_CATEGORY_PREFIX.get(category, 'LT')
        for _ in range(80):
            code = f"{prefix}-{random.randint(0, 9999):04d}"
            if not cls.objects.filter(company=company, employee_code=code).exists():
                return code
        return f"{prefix}-{int(time.time()) % 10000:04d}"

    @property
    def effective_department(self):
        return self.department_obj.name if self.department_obj_id else self.department

    @property
    def current_contract(self):
        # Prioritize the newest contract. If the newest one is 'upcoming', 
        # it's still the 'current' focus of the employee's record.
        return self.contracts.order_by('-start_date', '-created_at').first()


class EmployeeStatutoryProfile(models.Model):
    """Country-specific employee statutory identifiers and payroll metadata.

    Flexible JSON identifiers allow each country pack to expose its own fields
    without creating five divergent Employee models. Values are tenant-scoped
    through the employee relationship and should be treated as sensitive HR data.
    """
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name='statutory_profile')
    identifiers = models.JSONField(default=dict, blank=True)
    tax_region = models.CharField(max_length=150, blank=True)
    social_security_region = models.CharField(max_length=150, blank=True)
    bank_name = models.CharField(max_length=150, blank=True)
    bank_branch = models.CharField(max_length=150, blank=True)
    account_name = models.CharField(max_length=200, blank=True)
    mobile_money_provider = models.CharField(max_length=100, blank=True)
    mobile_money_number = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        from django.core.exceptions import ValidationError
        from regional.countries.registry import get_country_pack
        
        if not self.employee or not self.employee.company:
            return
            
        try:
            country_code = self.employee.company.country_profile.country_code
            pack = get_country_pack(country_code)
        except (AttributeError, ValueError):
            # If no country profile is set, we cannot validate identifiers
            return

        # Pack.employee_fields is a tuple of (key, label, is_required)
        required_keys = [key for key, label, required in pack.employee_fields if required]
        provided_keys = self.identifiers.keys() if self.identifiers else []

        missing = [label for key, label, required in pack.employee_fields if required and key not in provided_keys]
        if missing:
            raise ValidationError({
                'identifiers': f"Missing required statutory identifiers for {pack.name}: {', '.join(missing)}"
            })

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Statutory profile - {self.employee.full_name}'


GENDER_CHOICES = [
    ('female', 'Female'),
    ('male', 'Male'),
    ('non_binary', 'Non-binary'),
    ('prefer_not_to_say', 'Prefer not to say'),
]

MARITAL_STATUS_CHOICES = [
    ('single', 'Single'),
    ('married', 'Married'),
    ('divorced', 'Divorced'),
    ('widowed', 'Widowed'),
    ('other', 'Other'),
    ('prefer_not_to_say', 'Prefer not to say'),
]


class EmployeePersonalDetails(models.Model):
    """Optional core-HR personal record kept separate from payroll fields."""
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name='personal_details')
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=30, choices=GENDER_CHOICES, blank=True)
    marital_status = models.CharField(max_length=30, choices=MARITAL_STATUS_CHOICES, blank=True)
    nationality = models.CharField(max_length=100, blank=True)
    address_line_1 = models.CharField(max_length=255, blank=True)
    address_line_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state_region = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=30, blank=True)
    country = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Personal details - {self.employee.full_name}'


class EmergencyContact(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='emergency_contacts')
    name = models.CharField(max_length=150)
    relationship = models.CharField(max_length=100)
    phone = models.CharField(max_length=50)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_primary', 'name']
        constraints = [
            models.UniqueConstraint(fields=['employee'], condition=Q(is_primary=True), name='unique_primary_emergency_contact_per_employee'),
        ]

    def __str__(self):
        return f'{self.name} - {self.employee.full_name}'


EMPLOYMENT_EVENT_CHOICES = [
    ('hired', 'Hired'),
    ('status_change', 'Status Change'),
    ('promotion', 'Promotion'),
    ('transfer', 'Department Transfer'),
    ('job_change', 'Job/Position Change'),
    ('salary_change', 'Salary Change'),
    ('contract_change', 'Contract Change'),
    ('rehired', 'Rehired'),
    ('resigned', 'Resigned'),
    ('terminated', 'Terminated'),
    ('note', 'HR Note'),
]


class EmploymentEvent(models.Model):
    """Chronological employee lifecycle history. Sensitive before/after data is retained in audit logs."""
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='employment_events')
    event_type = models.CharField(max_length=30, choices=EMPLOYMENT_EVENT_CHOICES)
    effective_date = models.DateField(default=timezone.localdate)
    title = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_employment_events')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-effective_date', '-created_at']

    def __str__(self):
        return f'{self.employee.full_name} - {self.get_event_type_display()} - {self.effective_date}'


class Contract(models.Model):
    CONTRACT_TYPE_CHOICES = [
        ('full_time', 'Full-time'),
        ('part_time', 'Part-time'),
        ('contractor', 'Contractor'),
        ('internship', 'Internship'),
        ('temporary', 'Temporary'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='contracts')
    contract_type = models.CharField(max_length=20, choices=CONTRACT_TYPE_CHOICES, default='full_time')
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    document = models.FileField(upload_to='contracts/', null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.employee.full_name} - {self.get_contract_type_display()}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({'end_date': 'End date cannot be before the start date.'})

        if self.employee and self.start_date:
            # Check for overlaps. We allow contracts to touch boundaries (End Date of A = Start Date of B - 1 day).
            overlapping = Contract.objects.filter(
                employee=self.employee,
                start_date__lt=self.end_date if self.end_date else timezone.localdate(),
            ).filter(
                models.Q(end_date__isnull=True) | models.Q(end_date__gt=self.start_date)
            )
            if self.pk:
                overlapping = overlapping.exclude(pk=self.pk)

            if overlapping.exists():
                raise ValidationError('This period overlaps an existing contract. End or adjust the existing contract first.')

    @property
    def status(self):
        today = timezone.localdate()
        if self.start_date > today:
            return 'upcoming'
        if self.end_date and self.end_date <= today:
            return 'expired'
        return 'active'


class WarningLetter(models.Model):
    WARNING_LEVEL_CHOICES = [
        ('verbal', 'Verbal Warning'),
        ('first', 'First Written Warning'),
        ('final', 'Final Written Warning'),
        ('disciplinary', 'Disciplinary Action'),
    ]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='warning_letters')
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    warning_level = models.CharField(max_length=20, choices=WARNING_LEVEL_CHOICES, default='first')
    subject = models.CharField(max_length=200)
    incident_date = models.DateField(null=True, blank=True)
    issued_date = models.DateField(default=timezone.localdate)
    details = models.TextField()
    employee_response = models.TextField(blank=True)
    acknowledged = models.BooleanField(default=False)
    document = models.FileField(upload_to='warning_letters/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-issued_date', '-created_at']

    def __str__(self):
        return f"{self.employee.full_name} - {self.subject}"


class EmployeeAllowance(models.Model):
    """A recurring allowance for a specific employee (e.g. housing, transport)."""
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='allowances')
    name = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    is_percentage_of_base = models.BooleanField(default=False, help_text='If true, amount is treated as a % of base salary')

    def __str__(self):
        return f"{self.name} - {self.employee.full_name}"


class EmployeeDeduction(models.Model):
    """A recurring non-statutory deduction for a specific employee (e.g. loan repayment)."""
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='deductions')
    name = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    is_percentage_of_base = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} - {self.employee.full_name}"

class EmployeeDocument(models.Model):
    DOCUMENT_TYPE_CHOICES = [
        ('identity', 'Identity Document'),
        ('contract', 'Contract'),
        ('certificate', 'Certificate'),
        ('qualification', 'Qualification'),
        ('policy', 'Policy / Acknowledgement'),
        ('medical', 'Medical / Fitness'),
        ('disciplinary', 'Disciplinary'),
        ('other', 'Other'),
    ]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='documents')
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES, default='other')
    title = models.CharField(max_length=200)
    document = models.FileField(upload_to='employee_documents/')
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='uploaded_employee_documents')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.employee.full_name} - {self.title}'


class RequiredDocumentRule(models.Model):
    """Company compliance rule describing a document required for an employee."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='required_document_rules')
    name = models.CharField(max_length=200)
    document_type = models.CharField(max_length=30, choices=EmployeeDocument.DOCUMENT_TYPE_CHOICES)
    contract_type = models.CharField(max_length=20, choices=Contract.CONTRACT_TYPE_CHOICES, blank=True)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, null=True, blank=True, related_name='document_requirements')
    warning_days = models.PositiveIntegerField(default=30)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [
            # Employee-specific rules must be unique for the same employee.
            models.UniqueConstraint(
                fields=['company', 'name', 'employee', 'contract_type'],
                condition=Q(employee__isnull=False),
                name='unique_required_doc_rule_employee_scope',
            ),
            # Company-wide rules use NULL employee; a normal unique constraint
            # does not protect these because SQL NULLs are distinct.
            models.UniqueConstraint(
                fields=['company', 'name', 'contract_type'],
                condition=Q(employee__isnull=True),
                name='unique_required_doc_rule_company_scope',
            ),
        ]

    def __str__(self):
        return f'{self.company.name} - {self.name}'


class HRRequest(models.Model):
    """Requests for changes to employee records that require HR/Owner approval."""
    REQUEST_TYPES = [
        ('salary', 'Salary Change'),
        ('position', 'Position/Transfer'),
        ('contract', 'Contract Update'),
        ('document', 'Document Upload'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='hr_requests')
    request_type = models.CharField(max_length=20, choices=REQUEST_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payload = models.JSONField(help_text='The requested changes (e.g., {"new_salary": 5000})')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='hr_requests_made')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='hr_requests_approved')
    comments = models.TextField(blank=True, help_text='HR comments on approval or rejection')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_request_type_display()} for {self.employee.full_name} ({self.status})'

