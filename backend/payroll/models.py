from django.db import models
from django.core.validators import MinValueValidator

from accounts.models import Company

PAY_FREQUENCY_CHOICES = [
    ('monthly', 'Monthly'),
    ('biweekly', 'Bi-weekly'),
    ('weekly', 'Weekly'),
]


class PayrollConfig(models.Model):
    """
    Per-company payroll configuration, filled in during the onboarding
    form after account activation. This is deliberately NOT tied to a
    fixed country lookup table: each company declares its own currency,
    tax brackets, and statutory contributions, since tax/deduction
    policy differs by country (and sometimes by sector) across Africa.
    """
    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name='payroll_config')

    currency = models.CharField(max_length=10, default='USD', help_text='ISO currency code, e.g. GNF, NGN, KES, USD')
    pay_frequency = models.CharField(max_length=20, choices=PAY_FREQUENCY_CHOICES, default='monthly')

    # Tax is applied progressively across brackets (see payroll/services.py)
    tax_calculation_enabled = models.BooleanField(default=True)

    # Off by default on purpose. Whether an unpaid absence may be deducted from
    # a monthly salary is a wage-law question that varies by country and
    # sometimes by sector, and getting it wrong takes money out of an
    # employee's pay on the strength of a manager's attendance mark. Companies
    # turn it on once they have confirmed their position; see payroll/absence.py
    # for the rules and, more importantly, for everything it declines to deduct.
    deduct_unpaid_absence = models.BooleanField(default=False)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Payroll config for {self.company.name}"


class TaxBracket(models.Model):
    """
    One progressive income-tax bracket. min_amount/max_amount define the
    slice of income taxed at `rate` (percentage). Leave max_amount blank
    for the top, open-ended bracket.
    """
    payroll_config = models.ForeignKey(PayrollConfig, on_delete=models.CASCADE, related_name='tax_brackets')
    min_amount = models.DecimalField(max_digits=14, decimal_places=2)
    max_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    rate = models.DecimalField(max_digits=5, decimal_places=2, help_text='Percentage, e.g. 15.00 for 15%')

    class Meta:
        ordering = ['min_amount']

    def __str__(self):
        top = self.max_amount if self.max_amount is not None else '∞'
        return f"{self.min_amount}-{top} @ {self.rate}%"


class StatutoryContribution(models.Model):
    """
    A statutory/social contribution declared by the company, e.g.
    pension, national social security, health insurance. Can be a flat
    amount or a percentage of gross salary, split between employer and
    employee shares.
    """
    payroll_config = models.ForeignKey(PayrollConfig, on_delete=models.CASCADE, related_name='contributions')
    name = models.CharField(max_length=100, help_text='e.g. Social Security, Pension, Health Insurance')
    is_percentage = models.BooleanField(default=True)
    employee_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text='% or flat amount paid by employee')
    employer_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text='% or flat amount paid by employer')

    def __str__(self):
        return f"{self.name} ({self.payroll_config.company.name})"


class PayrollRun(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('processed', 'Processed'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='payroll_runs')
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    run_date = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='approved_payroll_runs',
    )

    class Meta:
        ordering = ['-period_start']
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'period_start', 'period_end'],
                name='unique_company_payroll_period',
            ),
        ]

    def __str__(self):
        return f"{self.company.name} payroll {self.period_start} - {self.period_end}"


class Payslip(models.Model):
    payroll_run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name='payslips')
    employee = models.ForeignKey('employees.Employee', on_delete=models.CASCADE, related_name='payslips')

    base_salary = models.DecimalField(max_digits=14, decimal_places=2)
    total_allowances = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    gross_salary = models.DecimalField(max_digits=14, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_contributions = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_other_deductions = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_salary = models.DecimalField(max_digits=14, decimal_places=2)

    # Full line-item breakdown for transparency/printing on the payslip PDF
    breakdown = models.JSONField(default=dict, blank=True)

    payment_method = models.CharField(max_length=50, blank=True, help_text='e.g. bank_transfer, mobile_money, cash')
    payment_reference = models.CharField(max_length=100, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-generated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['payroll_run', 'employee'],
                name='unique_payslip_per_run_employee',
            ),
        ]

    def __str__(self):
        return f"Payslip: {self.employee.full_name} - {self.payroll_run}"


# ---------------------------------------------------------------------------
# Milestone: overtime, salary advances, recovery
# ---------------------------------------------------------------------------

class OvertimeRule(models.Model):
    """Company multipliers for overtime by day type (labour-law configurable)."""
    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name='overtime_rule')
    weekday_multiplier = models.DecimalField(max_digits=5, decimal_places=2, default=1.5)
    weekend_multiplier = models.DecimalField(max_digits=5, decimal_places=2, default=2.0)
    holiday_multiplier = models.DecimalField(max_digits=5, decimal_places=2, default=2.0)
    # Hourly rate base: annual salary / (days * hours) approx from monthly base
    standard_hours_per_month = models.DecimalField(max_digits=6, decimal_places=2, default=173)
    # The daily equivalent, and the threshold attendance is measured against.
    # Needed because Attendance.worked_minutes is time on the clock while
    # OvertimeEntry.hours is time paid at a premium - the two are different
    # quantities, and the standard day is what separates them. 173/month over
    # ~21.6 working days is the same 8 hours, so the defaults stay consistent.
    standard_hours_per_day = models.DecimalField(max_digits=5, decimal_places=2, default=8)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"OT rules for {self.company.name}"


class OvertimeEntry(models.Model):
    DAY_TYPE = [
        ('weekday', 'Weekday'),
        ('weekend', 'Weekend'),
        ('holiday', 'Public holiday'),
    ]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='overtime_entries')
    employee = models.ForeignKey('employees.Employee', on_delete=models.CASCADE, related_name='overtime_entries')
    work_date = models.DateField()
    hours = models.DecimalField(max_digits=6, decimal_places=2, validators=[MinValueValidator(0.01)])
    day_type = models.CharField(max_length=20, choices=DAY_TYPE, default='weekday')
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notes = models.CharField(max_length=255, blank=True)
    payroll_run = models.ForeignKey(
        PayrollRun, on_delete=models.SET_NULL, null=True, blank=True, related_name='overtime_entries',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-work_date']


class SalaryAdvance(models.Model):
    STATUS = [
        ('open', 'Open'),
        ('partial', 'Partially recovered'),
        ('cleared', 'Cleared'),
        ('cancelled', 'Cancelled'),
    ]
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='salary_advances')
    employee = models.ForeignKey('employees.Employee', on_delete=models.CASCADE, related_name='salary_advances')
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0.01)])
    remaining = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    installment_amount = models.DecimalField(
        max_digits=14, decimal_places=2,
        validators=[MinValueValidator(0.01)],
        help_text='Amount recovered automatically each payroll run',
    )
    reason = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default='open')
    granted_on = models.DateField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if self.remaining is None:
            self.remaining = self.amount
        super().save(*args, **kwargs)


class AdvanceRecovery(models.Model):
    advance = models.ForeignKey(SalaryAdvance, on_delete=models.CASCADE, related_name='recoveries')
    payslip = models.ForeignKey(Payslip, on_delete=models.CASCADE, related_name='advance_recoveries')
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    recovered_at = models.DateTimeField(auto_now_add=True)


class PublicHoliday(models.Model):
    """Company-defined public holidays for overtime day_type classification."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='public_holidays')
    date = models.DateField()
    name = models.CharField(max_length=120)
    class Meta:
        unique_together = [('company', 'date')]
        ordering = ['date']
    def __str__(self):
        return f"{self.name} ({self.date})"
