from decimal import Decimal
from django.db import models
from accounts.models import Company
from employees.models import Employee

LEAVE_TYPE_CHOICES = [
    ('annual', 'Annual'), ('sick', 'Sick'), ('maternity', 'Maternity'),
    ('paternity', 'Paternity'), ('compassionate', 'Compassionate'),
    ('break_off_duty', 'Break-Off Duty'), ('unpaid', 'Unpaid'), ('other', 'Other'),
]
STATUS_CHOICES = [('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')]


class LeaveRequest(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.CharField(max_length=20, choices=LEAVE_TYPE_CHOICES, default='annual')
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    reviewed_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_leave_requests')
    applied_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-applied_at']

    def __str__(self):
        return f"{self.employee.full_name} - {self.leave_type} ({self.status})"

    @property
    def days_requested(self):
        return (self.end_date - self.start_date).days + 1


class BreakRequest(models.Model):
    BREAK_TYPE_CHOICES = [
        ('short', 'Short Break'), ('lunch', 'Lunch Break'),
        ('personal', 'Personal Break'), ('other', 'Other'),
    ]
    STATUS_CHOICES = [('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='break_requests')
    break_type = models.CharField(max_length=20, choices=BREAK_TYPE_CHOICES, default='personal')
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField(null=True, blank=True)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    reviewed_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_break_requests')
    applied_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-applied_at']

    @property
    def duration_minutes(self):
        if not self.end_time:
            return None
        from datetime import datetime
        return int((datetime.combine(self.date, self.end_time) - datetime.combine(self.date, self.start_time)).total_seconds() / 60)


class LeaveAccrualPolicy(models.Model):
    """Annual entitlement and monthly accrual rate per leave type (company-configurable)."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='leave_accrual_policies')
    leave_type = models.CharField(max_length=20, choices=LEAVE_TYPE_CHOICES, default='annual')
    days_per_year = models.DecimalField(max_digits=6, decimal_places=2, default=21)
    accrue_monthly = models.BooleanField(default=True)
    allow_encashment = models.BooleanField(default=True)
    encashment_rate_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=100,
        help_text='% of daily rate paid on encashment (100 = full day rate)',
    )

    class Meta:
        unique_together = [('company', 'leave_type')]

    @property
    def monthly_accrual(self):
        return (self.days_per_year / Decimal('12')).quantize(Decimal('0.01'))


class LeaveBalance(models.Model):
    employee = models.ForeignKey('employees.Employee', on_delete=models.CASCADE, related_name='leave_balances')
    leave_type = models.CharField(max_length=20, choices=LEAVE_TYPE_CHOICES, default='annual')
    balance_days = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('employee', 'leave_type')]


class LeaveEncashment(models.Model):
    STATUS = [('pending', 'Pending'), ('approved', 'Approved'), ('paid', 'Paid'), ('rejected', 'Rejected')]
    employee = models.ForeignKey('employees.Employee', on_delete=models.CASCADE, related_name='leave_encashments')
    leave_type = models.CharField(max_length=20, choices=LEAVE_TYPE_CHOICES, default='annual')
    days = models.DecimalField(max_digits=6, decimal_places=2)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS, default='pending')
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_encashments',
    )
