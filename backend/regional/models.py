from django.db import models
from django.conf import settings


COUNTRY_CHOICES = [
    # Generated from `COUNTRY_PACKS`. Adding a country to the registry is the
    # only step needed; maintaining this list by hand was a drift risk, and a
    # pack with no entry here cannot be selected for a company at all.
    ('AO', 'Angola'),
    ('BF', 'Burkina Faso'),
    ('BI', 'Burundi'),
    ('BJ', 'Benin'),
    ('BW', 'Botswana'),
    ('CD', 'DR Congo'),
    ('CF', 'Central African Republic'),
    ('CG', 'Republic of the Congo'),
    ('CI', "Côte d'Ivoire"),
    ('CM', 'Cameroon'),
    ('CV', 'Cabo Verde'),
    ('DJ', 'Djibouti'),
    ('DZ', 'Algeria'),
    ('EG', 'Egypt'),
    ('ER', 'Eritrea'),
    ('ET', 'Ethiopia'),
    ('GA', 'Gabon'),
    ('GH', 'Ghana'),
    ('GM', 'The Gambia'),
    ('GN', 'Guinea'),
    ('GQ', 'Equatorial Guinea'),
    ('GW', 'Guinea-Bissau'),
    ('KE', 'Kenya'),
    ('KM', 'Comoros'),
    ('LR', 'Liberia'),
    ('LS', 'Lesotho'),
    ('LY', 'Libya'),
    ('MA', 'Morocco'),
    ('MG', 'Madagascar'),
    ('ML', 'Mali'),
    ('MR', 'Mauritania'),
    ('MU', 'Mauritius'),
    ('MW', 'Malawi'),
    ('MZ', 'Mozambique'),
    ('NA', 'Namibia'),
    ('NE', 'Niger'),
    ('NG', 'Nigeria'),
    ('RW', 'Rwanda'),
    ('SC', 'Seychelles'),
    ('SD', 'Sudan'),
    ('SL', 'Sierra Leone'),
    ('SN', 'Senegal'),
    ('SO', 'Somalia'),
    ('SS', 'South Sudan'),
    ('ST', 'São Tomé and Príncipe'),
    ('SZ', 'Eswatini'),
    ('TD', 'Chad'),
    ('TG', 'Togo'),
    ('TN', 'Tunisia'),
    ('TZ', 'Tanzania'),
    ('UG', 'Uganda'),
    ('ZA', 'South Africa'),
    ('ZM', 'Zambia'),
    ('ZW', 'Zimbabwe'),
]


class CompanyCountryProfile(models.Model):
    """Country-specific operating configuration for a company.

    This is deliberately separate from statutory rules. It stores tenant
    configuration while country packs provide the reusable product defaults.
    """
    company = models.OneToOneField('accounts.Company', on_delete=models.CASCADE, related_name='country_profile')
    country_code = models.CharField(max_length=2, choices=COUNTRY_CHOICES)
    currency_code = models.CharField(max_length=3)
    payroll_frequency = models.CharField(max_length=30, default='monthly')
    timezone = models.CharField(max_length=64, blank=True)
    onboarding_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Company Country Profile'
        verbose_name_plural = 'Company Country Profiles'

    def __str__(self):
        return f'{self.company} - {self.country_code}'


class StatutoryRule(models.Model):
    """Effective-dated country rule registry.

    Rules are data, not hard-coded branches in payroll services. Values can
    therefore change without rewriting historical payroll calculations.
    """
    country_code = models.CharField(max_length=2, choices=COUNTRY_CHOICES)
    code = models.CharField(max_length=80)
    name = models.CharField(max_length=160)
    rule_type = models.CharField(max_length=40)
    calculation_method = models.CharField(max_length=60, default='percentage')
    value = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    source_reference = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['country_code', 'code', '-effective_from']
        indexes = [
            models.Index(fields=['country_code', 'code', 'effective_from']),
            models.Index(fields=['country_code', 'effective_from', 'effective_to']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['country_code', 'code', 'effective_from'],
                name='unique_country_rule_effective',
            ),
        ]

    def __str__(self):
        return f'{self.country_code}:{self.code} ({self.effective_from})'


class StatutoryFilingRule(models.Model):
    """Effective-dated filing obligation for a country pack.

    Due dates are represented as rules rather than hard-coded in views so
    jurisdictions can change deadlines without rewriting application logic.
    """
    FREQUENCY_CHOICES = [('monthly', 'Monthly'), ('annual', 'Annual')]
    country_code = models.CharField(max_length=2, choices=COUNTRY_CHOICES)
    code = models.CharField(max_length=80)
    name = models.CharField(max_length=160)
    authority = models.CharField(max_length=160)
    filing_type = models.CharField(max_length=60, default='statutory')
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='monthly')
    due_day = models.PositiveSmallIntegerField(null=True, blank=True)
    due_month = models.PositiveSmallIntegerField(null=True, blank=True)
    source_reference = models.URLField(blank=True)
    notes = models.TextField(blank=True)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['country_code', 'code', '-effective_from']
        indexes = [
            models.Index(fields=['country_code', 'code', 'effective_from']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['country_code', 'code', 'effective_from'],
                name='unique_country_filing_rule_effective',
            ),
        ]

    def __str__(self):
        return f'{self.country_code}:{self.code} ({self.effective_from})'


class StatutoryFiling(models.Model):
    """Tenant filing obligation generated for a payroll period."""
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('reviewed', 'Reviewed'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
        ('submitted', 'Submitted'),
        ('closed', 'Closed'),
        ('overdue', 'Overdue'),
        # Retained while existing tenant records are migrated through the
        # controlled workflow. New filings do not use these states.
        ('ready', 'Ready (legacy)'),
        ('filed', 'Filed (legacy)'),
    ]
    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='statutory_filings')
    rule = models.ForeignKey(StatutoryFilingRule, on_delete=models.PROTECT, related_name='filings')
    payroll_run = models.ForeignKey('payroll.PayrollRun', on_delete=models.SET_NULL, null=True, blank=True, related_name='statutory_filings')
    period_start = models.DateField()
    period_end = models.DateField()
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    filed_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='reviewed_statutory_filings',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='approved_statutory_filings',
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='submitted_statutory_filings',
    )
    submission_reference = models.CharField(max_length=160, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['due_date', 'rule__code']
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'rule', 'period_start', 'period_end'],
                name='unique_company_statutory_filing_period',
            ),
        ]
        indexes = [
            models.Index(fields=['company', 'due_date', 'status']),
        ]

    def __str__(self):
        return f'{self.company.name} - {self.rule.name} - {self.period_end}'

    @property
    def payment_record(self):
        """Latest successful payment, kept for API backward compatibility."""
        return self.payments.filter(status='paid').order_by('-payment_date', '-created_at').first()


class StatutoryCompliancePack(models.Model):
    """A reviewable compliance package attached to one completed payroll run."""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('ready', 'Ready for Filing'),
        ('submitted', 'Submitted'),
        ('closed', 'Closed'),
    ]
    company = models.ForeignKey('accounts.Company', on_delete=models.CASCADE, related_name='statutory_compliance_packs')
    payroll_run = models.OneToOneField('payroll.PayrollRun', on_delete=models.CASCADE, related_name='statutory_compliance_pack')
    country_code = models.CharField(max_length=2, choices=COUNTRY_CHOICES)
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    filing_count = models.PositiveIntegerField(default=0)
    report_count = models.PositiveIntegerField(default=0)
    generated_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-period_end', '-generated_at']
        constraints = [
            models.UniqueConstraint(fields=['company', 'payroll_run'], name='unique_company_compliance_pack_run'),
        ]

    def __str__(self):
        return f'{self.company.name} compliance pack - {self.period_end}'

class StatutoryFilingPayment(models.Model):
    """Payment evidence for a statutory obligation; never stores banking credentials."""
    STATUS_CHOICES = [('pending','Pending'),('paid','Paid'),('failed','Failed'),('reversed','Reversed')]
    filing = models.ForeignKey(StatutoryFiling, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    payment_date = models.DateField(null=True, blank=True)
    method = models.CharField(max_length=40, blank=True)
    transaction_reference = models.CharField(max_length=160, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    receipt_reference = models.CharField(max_length=160, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='statutory_payment_records')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-payment_date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['filing'],
                condition=models.Q(status='paid'),
                name='unique_paid_payment_per_filing',
            ),
        ]
        indexes = [
            models.Index(fields=['filing', 'status']),
        ]

    def __str__(self):
        return f'{self.filing} payment'
