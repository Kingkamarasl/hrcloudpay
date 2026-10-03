from datetime import datetime, timedelta

from django.db import models

from employees.models import Employee

STATUS_CHOICES = [
    ('present', 'Present'),
    ('absent', 'Absent'),
    ('half_day', 'Half Day'),
    ('leave', 'On Leave'),
]


class Attendance(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='attendance_records')
    date = models.DateField()
    check_in = models.TimeField(null=True, blank=True)
    check_out = models.TimeField(null=True, blank=True)
    # A shift that ends after midnight. Stored explicitly rather than inferred
    # from check_out < check_in, because a night shift (22:00 -> 06:00) and a
    # typo (17:00 -> 09:00) are indistinguishable in the two time columns
    # alone, and the second is a data-entry error worth rejecting rather than
    # silently reading as a 31-hour day.
    crossed_midnight = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='present')
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['employee', 'date'], name='unique_attendance_per_day'),
        ]
        ordering = ['-date']

    @property
    def worked_minutes(self):
        """Minutes between check-in and check-out, or None if either is unset.

        None rather than 0 so a caller can tell "nobody clocked out" from
        "worked zero minutes", which are different payroll facts.
        """
        if not self.check_in or not self.check_out:
            return None
        start = datetime.combine(self.date, self.check_in)
        end = datetime.combine(self.date, self.check_out)
        if self.crossed_midnight:
            end += timedelta(days=1)
        return int((end - start).total_seconds() // 60)

    def __str__(self):
        return f"{self.employee.full_name} - {self.date} ({self.status})"