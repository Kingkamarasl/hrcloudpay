"""Biometric attendance ingestion.

A biometric device - fingerprint reader, face terminal, or iris scanner - is the
source of truth for "this person was at this place at this time". HRCloudPay
does not store biometric templates; the template lives on the device, and the
server only records that an employee is enrolled on it and the punches it
produces. That keeps the most sensitive data off the database and off any backup.

The ingestion path is deliberately device-agnostic. Biometric hardware speaks
dozens of proprietary protocols, and shipping a driver for each would mean
maintaining firmware-adjacent code we cannot test. Instead, every device that
can POST JSON (or that an operator can convert from CSV) talks to the same
endpoint with the same shape, and a device registry records which ones are
trusted. A buyer with a ZKTeco terminal and a buyer with a Hikvision terminal
use the same integration.
"""


import hashlib
import secrets as _secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import Company
from employees.models import Employee


def _hash_key(raw):
    """One-way hash of a device API key, for comparison at request time.

    The key is shown to the operator once, at registration, and stored hashed -
    the same discipline as a password, because a leaked key grants the ability to
    inject attendance records for an entire company.
    """
    if not raw:
        return ''
    return hashlib.sha256(raw.encode()).hexdigest()


DEVICE_TYPES = [
    ('fingerprint', 'Fingerprint'),
    ('face', 'Face recognition'),
    ('iris', 'Iris'),
    ('palm', 'Palm'),
    ('card', 'Card / RFID'),
    ('other', 'Other'),
]

DEVICE_STATUSES = [
    ('active', 'Active'),
    ('inactive', 'Inactive'),
    ('retired', 'Retired'),
]

PUNCH_TYPES = [
    ('in', 'Clock in'),
    ('out', 'Clock out'),
    ('unknown', 'Unknown'),
]

PUNCH_STATUSES = [
    ('pending', 'Pending'),
    ('processed', 'Processed'),
    ('ignored', 'Ignored'),
    ('failed', 'Failed'),
]

ENROLLMENT_STATUSES = [
    ('active', 'Active'),
    ('revoked', 'Revoked'),
]

# Which identifiers a terminal is allowed to identify someone by. Every policy
# starts with the enrolment that ties a person to that terminal - it is the only
# identifier the device cannot lie about. What follows is the operator's choice,
# made per device because the same fleet can mix both kinds of terminal.
#
# 'pk' is the dangerous one and is never the default: a terminal whose local
# user IDs are small integers (1..50 is the norm) would be read as HRCloudPay's
# primary keys, which are assigned in creation order, so employee 7 on the
# terminal becomes the seventh employee HRCloudPay happens to know - a
# confidently wrong match on every punch of every shift. It exists because some
# terminals really are fed our IDs, and it must be asked for.
MATCH_POLICIES = [
    ('enrolment', 'Enrolment template ID only'),
    ('code', 'Enrolment template ID, then employee code'),
    ('pk', 'Enrolment template ID, then employee code, then HRCloudPay ID'),
]

# The rule that actually decided who a punch belongs to, recorded on the punch
# itself. Without it there is no way to answer "why did the system think this
# was Ada?" later - and that question is only ever asked after something has
# already gone wrong at payroll.
MATCHED_BY_CHOICES = [
    ('enrolment', 'Enrolment template ID'),
    ('employee_code', 'Employee code'),
    ('pk', 'HRCloudPay employee ID'),
    ('manual', 'Chosen by a person'),
]


class BiometricDevice(models.Model):
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='biometric_devices')
    name = models.CharField(max_length=120)
    device_id = models.CharField(
        max_length=80,
        help_text='The identifier the device reports as, e.g. its serial number.',
    )
    device_type = models.CharField(
        max_length=20, choices=DEVICE_TYPES, default='fingerprint')
    location = models.CharField(max_length=160, blank=True)
    status = models.CharField(
        max_length=20, choices=DEVICE_STATUSES, default='active')
    # Which identifiers this terminal is allowed to identify someone by.
    # Read at ingest time; see MATCH_POLICIES for why the dangerous option is
    # per-device and opt-in rather than a global setting.
    match_policy = models.CharField(
        max_length=20, choices=MATCH_POLICIES, default='code',
        help_text='Which identifiers this terminal may match punches by.',
    )
    # Hashed API key used to authenticate punches from this device.
    api_key_hash = models.CharField(max_length=64, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'device_id'],
                name='unique_biometric_device_per_company'),
        ]
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.device_id})'

    @staticmethod
    def generate_api_key():
        """Return (raw, hashed). The raw value is shown once and never stored."""
        raw = _secrets.token_urlsafe(32)
        return raw, _hash_key(raw)

    @classmethod
    def create_with_key(cls, **kwargs):
        """Create a device and return (instance, raw_api_key).

        The raw key is returned to the caller and never persisted; only its
        hash is stored. Callers must hand the raw value to the operator before
        discarding it.
        """
        raw, hashed = cls.generate_api_key()
        kwargs['api_key_hash'] = hashed
        instance = cls.objects.create(**kwargs)
        return instance, raw

    def check_api_key(self, raw):
        if not self.api_key_hash or not raw:
            return False
        return _hash_key(raw) == self.api_key_hash

    @classmethod
    def authenticate(cls, device_id, raw):
        """Resolve a device by its tenant-local ID and its API-key hash.

        Device IDs are only unique within a company, so looking up by ID alone
        can select another tenant's device when serial numbers collide.
        """
        if not device_id or not raw:
            return None
        return cls.objects.filter(
            device_id=device_id, api_key_hash=_hash_key(raw),
        ).first()

    def touch(self):
        self.last_seen_at = timezone.now()
        self.save(update_fields=['last_seen_at'])


class BiometricEnrollment(models.Model):
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name='biometric_enrollments')
    device = models.ForeignKey(
        BiometricDevice, on_delete=models.CASCADE,
        related_name='enrollments')
    method = models.CharField(max_length=20, choices=DEVICE_TYPES)
    # The device-side reference for the stored template. HRCloudPay does not
    # store the template itself - see the module docstring.
    template_id = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=20, choices=ENROLLMENT_STATUSES, default='active')
    enrolled_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['employee', 'device'],
                name='unique_biometric_enrollment_per_employee_device'),
        ]
        ordering = ['-enrolled_at']

    def __str__(self):
        return f'{self.employee.full_name} on {self.device.name}'

    def revoke(self):
        self.status = 'revoked'
        self.revoked_at = timezone.now()
        self.save(update_fields=['status', 'revoked_at'])


class BiometricPunch(models.Model):
    device = models.ForeignKey(
        BiometricDevice, on_delete=models.CASCADE, related_name='punches')
    employee = models.ForeignKey(
        Employee, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='biometric_punches')
    # The rule that decided the employee above (see MATCHED_BY_CHOICES), or
    # blank when nothing matched. Written once at ingest and again when a person
    # reconciles the punch by hand, because "who decided this was Ada" is a
    # question asked only after something has already gone wrong.
    matched_by = models.CharField(
        max_length=20, choices=MATCHED_BY_CHOICES, blank=True, default='')
    punch_time = models.DateTimeField()
    # Minutes east of UTC that the reporting device's clock was set to. The
    # database stores punch_time as an instant and drops the offset, so without
    # this a punch read back from the database (reconciliation reads punches
    # back) would yield the server's wall clock instead of the device's.
    # Nullable: punches received before this column existed have no offset left
    # to recover, and a device that reported a naive timestamp used the server's
    # own zone, which is recorded here as-is.
    utc_offset_minutes = models.IntegerField(null=True, blank=True)
    punch_type = models.CharField(
        max_length=10, choices=PUNCH_TYPES, default='unknown')
    # Allowlisted attendance fields from the device payload, kept for
    # reconciliation when a punch cannot be matched to an employee or shift.
    raw_payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20, choices=PUNCH_STATUSES, default='pending')
    error = models.CharField(max_length=255, blank=True)
    attendance_record = models.ForeignKey(
        'attendance.Attendance', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='biometric_punches')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-punch_time']

    def __str__(self):
        who = self.employee.full_name if self.employee else 'unmatched'
        return f'{who} {self.punch_type} at {self.punch_time}'
