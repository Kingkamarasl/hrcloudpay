"""Biometric attendance ingestion.

A biometric terminal has no user account and no browser. It authenticates with
an API key, reports a punch, and the server turns that into an attendance
record. These tests pin the contract on both sides of that exchange, because a
punch that is silently dropped or silently mis-attributed becomes a payroll
correction nobody can trace.
"""

from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import AuditLog, Company, User
from attendance.models import Attendance
from biometrics.models import BiometricDevice, BiometricEnrollment, BiometricPunch
from biometrics.services import device_health
from biometrics.throttling import (
    AnonymousPunchThrottle, BiometricDeviceThrottle)
from biometrics.views import MAX_PUNCH_BATCH
from employees.models import Employee
from payroll.models import PublicHoliday

INGEST = '/api/biometrics/punch/'
DEVICES = '/api/biometrics/devices/'


def _company(name='Northwind'):
    from datetime import timedelta

    from django.utils import timezone

    from accounts.models import Subscription

    company = Company.objects.create(
        name=name, email='o@%s.example' % name.lower(),
        is_active=True, plan='starter')
    Subscription.objects.create(
        company=company, status='active',
        started_at=timezone.now(),
        renews_at=timezone.now() + timedelta(days=30))
    return company


def _user(company, role='hr', username='hr1'):
    return User.objects.create_user(
        username=username, email='%s@%s.example' % (username, company.name.lower()),
        password='Str0ngPass-2026!', company=company, role=role)


def _employee(company, code='CA001'):
    return Employee.objects.create(
        company=company, first_name='Ada', last_name='Lovelace',
        email='ada@%s.example' % company.name.lower(),
        employee_code=code, employment_status='active')


def _device(company, device_id='ZK-001'):
    device, raw = BiometricDevice.create_with_key(
        company=company, name='Front door', device_id=device_id,
        device_type='fingerprint', location='Lobby')
    return device, raw


class DeviceRegistrationTests(TestCase):
    def setUp(self):
        self.company = _company()
        self.hr = _user(self.company, role='hr', username='hr1')
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def test_registering_returns_the_raw_key_once(self):
        response = self.client.post(DEVICES, {
            'name': 'Front door', 'device_id': 'ZK-001',
            'device_type': 'fingerprint', 'location': 'Lobby',
        }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn('api_key', response.data)
        raw = response.data['api_key']
        self.assertTrue(raw)
        device = BiometricDevice.objects.get(device_id='ZK-001')
        # Only the hash is stored. The raw key must not be recoverable from the
        # database, because a database leak would otherwise grant the ability to
        # inject attendance for an entire company.
        self.assertNotEqual(device.api_key_hash, raw)
        self.assertTrue(device.check_api_key(raw))
        self.assertFalse(device.check_api_key('wrong'))

    def test_the_list_endpoint_never_returns_the_key(self):
        _device(self.company)
        response = self.client.get(DEVICES)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertNotIn('api_key', response.data[0])
        self.assertNotIn('api_key_hash', response.data[0])

    def test_a_device_id_is_unique_per_company(self):
        _device(self.company)
        response = self.client.post(DEVICES, {
            'name': 'Second', 'device_id': 'ZK-001',
            'device_type': 'fingerprint',
        }, format='json')

        self.assertEqual(response.status_code, 400)

    def test_two_companies_may_use_the_same_device_id(self):
        other = _company('OtherCo')
        _device(self.company, 'ZK-001')
        _device(other, 'ZK-001')

        self.assertEqual(BiometricDevice.objects.filter(device_id='ZK-001').count(), 2)

    def test_an_employee_cannot_register_a_device(self):
        member = _user(self.company, role='employee', username='emp1')
        self.client.force_authenticate(member)

        response = self.client.post(DEVICES, {
            'name': 'Front door', 'device_id': 'ZK-002',
            'device_type': 'fingerprint',
        }, format='json')

        self.assertEqual(response.status_code, 403)


class PunchIngestTests(TestCase):
    def setUp(self):
        self.company = _company()
        self.device, self.raw_key = _device(self.company)
        self.employee = _employee(self.company)
        self.client = APIClient()

    def _punch(self, payload, key=None):
        headers = {}
        if key is not None:
            headers['HTTP_X_BIOMETRIC_DEVICE_KEY'] = key
        return self.client.post(INGEST, payload, format='json', **headers)

    def test_a_punch_requires_a_device_key(self):
        response = self._punch({
            'device_id': self.device.device_id,
            'employee': self.employee.employee_code,
            'punch_time': '2026-10-25T08:02:00+02:00',
            'punch_type': 'in',
        })

        self.assertEqual(response.status_code, 400)

    def test_an_unknown_device_is_rejected(self):
        response = self._punch({
            'device_id': 'NOPE', 'employee': self.employee.employee_code,
            'punch_time': '2026-10-25T08:02:00+02:00', 'punch_type': 'in',
        }, key=self.raw_key)

        self.assertEqual(response.status_code, 401)

    def test_a_wrong_key_is_rejected(self):
        response = self._punch({
            'device_id': self.device.device_id,
            'employee': self.employee.employee_code,
            'punch_time': '2026-10-25T08:02:00+02:00', 'punch_type': 'in',
        }, key='not-the-key')

        self.assertEqual(response.status_code, 401)

    def test_same_device_id_in_another_company_authenticates_by_its_own_key(self):
        other = _company('OtherCo')
        other_device, other_key = _device(other, self.device.device_id)
        other_employee = _employee(other, code='ZZ999')

        response = self._punch({
            'device_id': other_device.device_id,
            'employee': other_employee.employee_code,
            'punch_time': '2026-10-25T08:02:00+02:00', 'punch_type': 'in',
        }, key=other_key)

        self.assertEqual(response.status_code, 201, response.data)
        punch = BiometricPunch.objects.get()
        self.assertEqual(punch.device, other_device)
        self.assertEqual(punch.employee, other_employee)
        self.assertEqual(Attendance.objects.filter(employee=other_employee).count(), 1)

    def test_an_inactive_device_is_rejected(self):
        self.device.status = 'inactive'
        self.device.save(update_fields=['status'])

        response = self._punch({
            'device_id': self.device.device_id,
            'employee': self.employee.employee_code,
            'punch_time': '2026-10-25T08:02:00+02:00', 'punch_type': 'in',
        }, key=self.raw_key)

        self.assertEqual(response.status_code, 403)

    def test_a_clock_in_creates_an_attendance_record(self):
        response = self._punch({
            'device_id': self.device.device_id,
            'employee': self.employee.employee_code,
            'punch_time': '2026-10-25T08:02:00+02:00',
            'punch_type': 'in',
        }, key=self.raw_key)

        self.assertEqual(response.status_code, 201, response.data)
        record = Attendance.objects.get(employee=self.employee)
        self.assertEqual(str(record.check_in), '08:02:00')
        self.assertIsNone(record.check_out)
        self.assertEqual(record.status, 'present')
        self.assertEqual(record.notes, 'Clocked in (biometric)')

    def test_device_template_data_is_not_retained_in_the_punch_payload(self):
        response = self._punch({
            'device_id': self.device.device_id,
            'employee': self.employee.employee_code,
            'punch_time': '2026-10-25T08:02:00+02:00', 'punch_type': 'in',
            'fingerprint_template': 'sensitive-template-bytes',
            'vendor_metadata': {'face_embedding': 'sensitive-face-data'},
        }, key=self.raw_key)

        self.assertEqual(response.status_code, 201, response.data)
        punch = BiometricPunch.objects.get()
        self.assertEqual(set(punch.raw_payload), {
            'device_id', 'employee', 'punch_time', 'punch_type',
        })
        self.assertNotIn('fingerprint_template', punch.raw_payload)
        self.assertNotIn('vendor_metadata', punch.raw_payload)

    def test_active_enrollment_template_id_matches_the_employee(self):
        BiometricEnrollment.objects.create(
            employee=self.employee, device=self.device,
            method='fingerprint', template_id='terminal-user-42')

        response = self._punch({
            'device_id': self.device.device_id,
            'employee': 'terminal-user-42',
            'punch_time': '2026-10-25T08:02:00+02:00', 'punch_type': 'in',
        }, key=self.raw_key)

        self.assertEqual(response.status_code, 201, response.data)
        punch = BiometricPunch.objects.get()
        self.assertEqual(punch.employee, self.employee)
        self.assertEqual(Attendance.objects.get().employee, self.employee)

    def test_a_clock_out_closes_the_open_shift(self):
        self._punch({
            'device_id': self.device.device_id,
            'employee': self.employee.employee_code,
            'punch_time': '2026-10-25T08:00:00+02:00', 'punch_type': 'in',
        }, key=self.raw_key)
        response = self._punch({
            'device_id': self.device.device_id,
            'employee': self.employee.employee_code,
            'punch_time': '2026-10-25T17:30:00+02:00', 'punch_type': 'out',
        }, key=self.raw_key)

        self.assertEqual(response.status_code, 201, response.data)
        record = Attendance.objects.get(employee=self.employee)
        self.assertEqual(str(record.check_in), '08:00:00')
        self.assertEqual(str(record.check_out), '17:30:00')
        self.assertFalse(record.crossed_midnight)

    def test_a_midnight_shift_is_recorded_as_crossed(self):
        self._punch({
            'device_id': self.device.device_id,
            'employee': self.employee.employee_code,
            'punch_time': '2026-10-25T22:00:00+02:00', 'punch_type': 'in',
        }, key=self.raw_key)
        self._punch({
            'device_id': self.device.device_id,
            'employee': self.employee.employee_code,
            'punch_time': '2026-10-26T06:00:00+02:00', 'punch_type': 'out',
        }, key=self.raw_key)

        record = Attendance.objects.get(employee=self.employee)
        self.assertEqual(record.date.isoformat(), '2026-10-25')
        self.assertTrue(record.crossed_midnight)
        self.assertEqual(record.worked_minutes, 480)

    def test_unknown_punch_type_is_inferred_from_open_record_state(self):
        # First punch with no stated type becomes a clock-in.
        self._punch({
            'device_id': self.device.device_id,
            'employee': self.employee.employee_code,
            'punch_time': '2026-10-25T08:00:00+02:00',
        }, key=self.raw_key)
        # Second punch, also unstated, becomes a clock-out.
        self._punch({
            'device_id': self.device.device_id,
            'employee': self.employee.employee_code,
            'punch_time': '2026-10-25T17:00:00+02:00',
        }, key=self.raw_key)

        record = Attendance.objects.get(employee=self.employee)
        self.assertEqual(str(record.check_in), '08:00:00')
        self.assertEqual(str(record.check_out), '17:00:00')

    def test_a_second_clock_in_does_not_overwrite_the_first(self):
        """A forgotten clock-out must not be silently replaced by the next
        morning's arrival. That is the kind of quiet data loss that surfaces
        only at payroll."""
        self._punch({
            'device_id': self.device.device_id,
            'employee': self.employee.employee_code,
            'punch_time': '2026-10-25T08:00:00+02:00', 'punch_type': 'in',
        }, key=self.raw_key)
        response = self._punch({
            'device_id': self.device.device_id,
            'employee': self.employee.employee_code,
            'punch_time': '2026-10-25T09:00:00+02:00', 'punch_type': 'in',
        }, key=self.raw_key)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data['status'], 'ignored')
        record = Attendance.objects.get(employee=self.employee)
        self.assertEqual(str(record.check_in), '08:00:00')

    def test_a_clock_out_with_no_open_shift_is_not_fabricated(self):
        """Recording a clock-out with no clock-in would invent hours. It is
        kept as a failed punch for a person to reconcile instead."""
        response = self._punch({
            'device_id': self.device.device_id,
            'employee': self.employee.employee_code,
            'punch_time': '2026-10-25T17:00:00+02:00', 'punch_type': 'out',
        }, key=self.raw_key)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data['status'], 'failed')
        self.assertEqual(Attendance.objects.filter(employee=self.employee).count(), 0)
        punch = BiometricPunch.objects.get(device=self.device)
        self.assertEqual(punch.status, 'failed')
        self.assertTrue(punch.error)

    def test_an_unmatched_employee_is_recorded_not_dropped(self):
        response = self._punch({
            'device_id': self.device.device_id,
            'employee': 'NO-SUCH-CODE',
            'punch_time': '2026-10-25T08:00:00+02:00', 'punch_type': 'in',
        }, key=self.raw_key)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data['status'], 'ignored')
        self.assertEqual(Attendance.objects.count(), 0)
        punch = BiometricPunch.objects.get(device=self.device)
        self.assertIsNone(punch.employee)
        self.assertIn('matched', punch.error.lower())

    def test_punches_are_scoped_to_the_device_company(self):
        """A device key from company A must never record attendance for an
        employee of company B, even if the attacker knows their employee_code."""
        other = _company('OtherCo')
        other_emp = _employee(other, code='ZZ999')

        response = self._punch({
            'device_id': self.device.device_id,
            'employee': other_emp.employee_code,
            'punch_time': '2026-10-25T08:00:00+02:00', 'punch_type': 'in',
        }, key=self.raw_key)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(Attendance.objects.filter(employee=other_emp).count(), 0)

    def test_a_device_touches_last_seen_on_every_punch(self):
        before = self.device.last_seen_at
        self._punch({
            'device_id': self.device.device_id,
            'employee': self.employee.employee_code,
            'punch_time': '2026-10-25T08:00:00+02:00', 'punch_type': 'in',
        }, key=self.raw_key)

        self.device.refresh_from_db()
        self.assertIsNotNone(self.device.last_seen_at)
        if before is not None:
            self.assertGreaterEqual(self.device.last_seen_at, before)


class EnrollmentTests(TestCase):
    def setUp(self):
        self.company = _company()
        self.device, _ = _device(self.company)
        self.employee = _employee(self.company)
        self.hr = _user(self.company)
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def test_enrolling_an_employee_on_a_device(self):
        response = self.client.post('/api/biometrics/enrollments/', {
            'employee': self.employee.id, 'device': self.device.id,
            'method': 'fingerprint', 'template_id': 'tmpl-42',
        }, format='json')

        self.assertEqual(response.status_code, 201, response.data)
        enr = BiometricEnrollment.objects.get(employee=self.employee)
        self.assertEqual(enr.status, 'active')
        self.assertEqual(enr.template_id, 'tmpl-42')

    def test_an_employee_cannot_be_enrolled_twice_on_one_device(self):
        BiometricEnrollment.objects.create(
            employee=self.employee, device=self.device, method='fingerprint')
        response = self.client.post('/api/biometrics/enrollments/', {
            'employee': self.employee.id, 'device': self.device.id,
            'method': 'fingerprint',
        }, format='json')

        self.assertEqual(response.status_code, 400)

    def test_enrollment_cannot_cross_companies(self):
        other = _company('OtherCo')
        other_device, _ = _device(other, 'ZK-999')
        response = self.client.post('/api/biometrics/enrollments/', {
            'employee': self.employee.id, 'device': other_device.id,
            'method': 'fingerprint',
        }, format='json')

        self.assertEqual(response.status_code, 403)

    def test_an_employee_cannot_be_enrolled_on_another_companys_device(self):
        other = _company('OtherCo')
        other_employee = _employee(other, code='ZZ999')
        response = self.client.post('/api/biometrics/enrollments/', {
            'employee': other_employee.id, 'device': self.device.id,
            'method': 'fingerprint', 'template_id': 'foreign-template',
        }, format='json')

        self.assertEqual(response.status_code, 403)
        self.assertFalse(BiometricEnrollment.objects.exists())

    def test_revoking_an_enrollment(self):
        enr = BiometricEnrollment.objects.create(
            employee=self.employee, device=self.device, method='fingerprint')
        response = self.client.delete(
            '/api/biometrics/enrollments/%d/' % enr.id)

        self.assertEqual(response.status_code, 204)
        enr.refresh_from_db()
        self.assertEqual(enr.status, 'revoked')
        self.assertIsNotNone(enr.revoked_at)

    def test_an_employee_cannot_manage_enrollments(self):
        member = _user(self.company, role='employee', username='emp2')
        self.client.force_authenticate(member)

        response = self.client.get('/api/biometrics/enrollments/')

        self.assertEqual(response.status_code, 403)


class PunchLogTests(TestCase):
    def setUp(self):
        self.company = _company()
        self.device, self.raw_key = _device(self.company)
        self.employee = _employee(self.company)
        self.hr = _user(self.company)
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def test_the_punch_log_is_filterable(self):
        BiometricPunch.objects.create(
            device=self.device, employee=self.employee,
            punch_time=timezone.now(), punch_type='in', status='processed')
        BiometricPunch.objects.create(
            device=self.device, employee=self.employee,
            punch_time=timezone.now(), punch_type='out', status='failed',
            error='no open shift')

        response = self.client.get('/api/biometrics/punches/?status=failed')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['status'], 'failed')

    def test_punches_are_company_scoped(self):
        other = _company('OtherCo')
        other_device, _ = _device(other, 'ZK-999')
        BiometricPunch.objects.create(
            device=other_device, punch_time=timezone.now(),
            punch_type='in', status='processed')

        response = self.client.get('/api/biometrics/punches/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 0)


class DeviceLifecycleTests(TestCase):
    def setUp(self):
        self.company = _company()
        self.device, _ = _device(self.company)
        self.hr = _user(self.company)
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def test_a_device_can_be_retired(self):
        response = self.client.patch(
            '/api/biometrics/devices/%d/' % self.device.id,
            {'status': 'retired'}, format='json')

        self.assertEqual(response.status_code, 200, response.data)
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, 'retired')

    def test_a_retired_device_cannot_ingest_punches(self):
        self.device.status = 'retired'
        self.device.save(update_fields=['status'])
        raw = 'dummy'
        # Re-register to get a real key, since the device above has no known key.
        device, key = _device(self.company, 'ZK-RT')
        device.status = 'retired'
        device.save(update_fields=['status'])
        employee = _employee(self.company)

        response = APIClient().post(INGEST, {
            'device_id': device.device_id, 'employee': employee.employee_code,
            'punch_time': '2026-10-25T08:00:00+02:00', 'punch_type': 'in',
        }, format='json', HTTP_X_BIOMETRIC_DEVICE_KEY=key)

        self.assertEqual(response.status_code, 403)


class PunchRetryTests(TestCase):
    """A terminal that could not reach the server re-sends the punch later.

    An offline queue is the normal state of a terminal on a flaky link, so a
    re-delivery is routine traffic rather than an error. Treating each one as a
    new event would log a phantom "already clocked in" or an orphaned
    clock-out, and fill the reconciliation list with network failures that look
    like attendance problems.
    """

    def setUp(self):
        self.company = _company()
        self.device, self.raw_key = _device(self.company)
        self.employee = _employee(self.company)
        self.client = APIClient()

    def _punch(self, punch_time, punch_type):
        return self.client.post(INGEST, {
            'device_id': self.device.device_id,
            'employee': self.employee.employee_code,
            'punch_time': punch_time, 'punch_type': punch_type,
        }, format='json', HTTP_X_BIOMETRIC_DEVICE_KEY=self.raw_key)

    def test_a_resent_clock_in_is_recorded_once(self):
        first = self._punch('2026-10-25T08:02:00+02:00', 'in')
        second = self._punch('2026-10-25T08:02:00+02:00', 'in')

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertTrue(second.data['duplicate'])
        self.assertEqual(second.data['punch_id'], first.data['punch_id'])
        self.assertEqual(BiometricPunch.objects.count(), 1)
        self.assertEqual(Attendance.objects.count(), 1)

    def test_a_resent_clock_out_does_not_become_a_second_failure(self):
        self._punch('2026-10-25T08:00:00+02:00', 'in')
        first = self._punch('2026-10-25T17:00:00+02:00', 'out')
        second = self._punch('2026-10-25T17:00:00+02:00', 'out')

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(second.data['status'], 'processed')
        self.assertEqual(BiometricPunch.objects.count(), 2)
        record = Attendance.objects.get(employee=self.employee)
        self.assertEqual(str(record.check_out), '17:00:00')

    def test_a_retry_of_a_failed_punch_reports_the_same_failure(self):
        """Re-sending does not make the missing clock-in appear, so the device
        gets the original verdict instead of a second dead row."""
        first = self._punch('2026-10-25T17:00:00+02:00', 'out')
        second = self._punch('2026-10-25T17:00:00+02:00', 'out')

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(second.data['status'], 'failed')
        self.assertEqual(second.data['error'], first.data['error'])
        self.assertEqual(BiometricPunch.objects.count(), 1)

    def test_two_punches_seconds_apart_are_both_recorded(self):
        """The duplicate check must not swallow a genuinely separate event."""
        self._punch('2026-10-25T08:00:00+02:00', 'in')
        second = self._punch('2026-10-25T08:00:01+02:00', 'in')

        self.assertEqual(second.status_code, 202, second.data)
        self.assertFalse(second.data['duplicate'])
        self.assertEqual(BiometricPunch.objects.count(), 2)


class PunchLogQueryTests(TestCase):
    """The punch log is filtered from the UI, so a bad parameter is a 400.

    Each of these used to raise inside ``int()`` or in the ORM and reach the
    browser as a 500 - which reads as a broken server rather than a filter that
    needs correcting.
    """

    def setUp(self):
        self.company = _company()
        self.device, _ = _device(self.company)
        self.hr = _user(self.company)
        self.client = APIClient()
        self.client.force_authenticate(self.hr)
        BiometricPunch.objects.create(
            device=self.device, punch_time=timezone.now(),
            punch_type='in', status='processed')

    def _get(self, query):
        return self.client.get('/api/biometrics/punches/?' + query)

    def test_a_non_numeric_limit_is_rejected(self):
        self.assertEqual(self._get('limit=abc').status_code, 400)

    def test_a_zero_or_negative_limit_is_rejected(self):
        self.assertEqual(self._get('limit=0').status_code, 400)
        self.assertEqual(self._get('limit=-5').status_code, 400)

    def test_a_non_numeric_device_filter_is_rejected(self):
        self.assertEqual(self._get('device=front-door').status_code, 400)

    def test_a_non_numeric_employee_filter_is_rejected(self):
        self.assertEqual(self._get('employee=ada').status_code, 400)

    def test_an_oversized_limit_is_capped_rather_than_refused(self):
        response = self._get('limit=100000')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)


class PunchReconciliationTests(TestCase):
    """Acting on a punch the log deliberately kept instead of guessing."""

    def setUp(self):
        self.company = _company()
        self.device, self.raw_key = _device(self.company)
        self.employee = _employee(self.company)
        self.hr = _user(self.company)
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def _ingest(self, employee_identifier, punch_time, punch_type):
        return APIClient().post(INGEST, {
            'device_id': self.device.device_id,
            'employee': employee_identifier,
            'punch_time': punch_time, 'punch_type': punch_type,
        }, format='json', HTTP_X_BIOMETRIC_DEVICE_KEY=self.raw_key)

    def _unmatched_punch(self):
        self._ingest('NOT-ENROLLED', '2026-10-25T08:00:00+02:00', 'in')
        return BiometricPunch.objects.get()

    def _reconcile(self, punch, body=None):
        return self.client.post(
            '/api/biometrics/punches/%d/reconcile/' % punch.id,
            body or {}, format='json')

    def test_an_unmatched_punch_can_be_attached_to_an_employee(self):
        punch = self._unmatched_punch()

        response = self._reconcile(punch, {'employee': self.employee.id})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'processed')
        punch.refresh_from_db()
        self.assertEqual(punch.employee, self.employee)
        record = Attendance.objects.get(employee=self.employee)
        self.assertEqual(str(record.check_in), '08:00:00')

    def test_reprocessing_keeps_the_devices_wall_clock_and_day(self):
        """Reconciliation reads the punch back from the database to process it
        again, and that is where its offset used to be lost: 23:30 on the 25th
        at UTC-05:00 is 04:30 on the 26th in UTC, so a punch reprocessed as a
        UTC instant would record attendance for the wrong day - across a pay
        period boundary, at that."""
        self._ingest('NOT-ENROLLED', '2026-10-25T23:30:00-05:00', 'in')
        punch = BiometricPunch.objects.get()

        response = self._reconcile(punch, {'employee': self.employee.id})

        self.assertEqual(response.status_code, 200, response.data)
        record = Attendance.objects.get(employee=self.employee)
        self.assertEqual(record.date, date(2026, 10, 25))
        self.assertEqual(str(record.check_in), '23:30:00')

    def test_a_failed_clock_out_is_closed_once_the_shift_exists(self):
        """The clock-in was recorded by hand, or on another terminal, after the
        clock-out arrived - so the open shift now has something to close."""
        self._ingest(self.employee.employee_code,
                     '2026-10-25T17:00:00+02:00', 'out')
        punch = BiometricPunch.objects.get()
        self.assertEqual(punch.status, 'failed')
        Attendance.objects.create(
            employee=self.employee, date=date(2026, 10, 25),
            status='present', check_in=time(8, 0))

        response = self._reconcile(punch)

        self.assertEqual(response.status_code, 200, response.data)
        record = Attendance.objects.get(employee=self.employee)
        self.assertEqual(str(record.check_out), '17:00:00')
        punch.refresh_from_db()
        self.assertEqual(punch.status, 'processed')

    def test_an_unmatched_punch_needs_an_employee(self):
        punch = self._unmatched_punch()

        response = self._reconcile(punch)

        self.assertEqual(response.status_code, 400, response.data)
        punch.refresh_from_db()
        self.assertEqual(punch.status, 'ignored')
        self.assertEqual(Attendance.objects.count(), 0)

    def test_a_processed_punch_cannot_be_reconciled(self):
        """Reprocessing a punch that already produced an attendance record
        would rewrite hours someone may already have been paid for."""
        self._ingest(self.employee.employee_code,
                     '2026-10-25T08:00:00+02:00', 'in')
        punch = BiometricPunch.objects.get()
        self.assertEqual(punch.status, 'processed')

        response = self._reconcile(punch, {'employee': self.employee.id})

        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(Attendance.objects.count(), 1)

    def test_an_employee_from_another_company_cannot_be_assigned(self):
        other = _company('OtherCo')
        foreign = _employee(other, code='ZZ999')
        punch = self._unmatched_punch()

        response = self._reconcile(punch, {'employee': foreign.id})

        self.assertEqual(response.status_code, 400, response.data)
        punch.refresh_from_db()
        self.assertIsNone(punch.employee)
        self.assertEqual(Attendance.objects.count(), 0)

    def test_a_punch_from_another_company_is_not_reachable(self):
        other = _company('OtherCo')
        other_device, _ = _device(other, 'ZK-999')
        foreign = BiometricPunch.objects.create(
            device=other_device, punch_time=timezone.now(),
            punch_type='in', status='failed', error='no open shift')

        response = self._reconcile(foreign, {'employee': self.employee.id})

        self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, 'failed')

    def test_a_non_numeric_employee_is_rejected_not_a_server_error(self):
        punch = self._unmatched_punch()

        response = self._reconcile(punch, {'employee': 'ada'})

        self.assertEqual(response.status_code, 400, response.data)

    def test_an_employee_cannot_reconcile(self):
        member = _user(self.company, role='employee', username='emp9')
        self.client.force_authenticate(member)
        punch = self._unmatched_punch()

        response = self._reconcile(punch, {'employee': self.employee.id})

        self.assertEqual(response.status_code, 403)

    def test_the_reconciliation_is_written_to_the_audit_log(self):
        punch = self._unmatched_punch()

        self._reconcile(punch, {'employee': self.employee.id})

        entry = AuditLog.objects.filter(
            action='biometric.punch_reconciled').first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.actor, self.hr)
        self.assertEqual(entry.target_id, str(punch.id))


class DeviceHealthTests(TestCase):
    """A terminal that stops reporting has to be visible.

    Nothing else in the system notices: attendance for everyone who clocks on it
    simply stops existing, and that looks exactly like a quiet day. The rule is
    a silence window plus a working-day gate - see
    biometrics.services.device_health - so an ordinary weekend is not an alarm.
    """

    def setUp(self):
        self.company = _company()
        self.device, _ = _device(self.company)
        # Wednesday 28 October 2026, 10:00.
        self.now = timezone.make_aware(datetime(2026, 10, 28, 10, 0))

    def _seen_at(self, when, now=None):
        self.device.last_seen_at = when
        self.device.save(update_fields=['last_seen_at'])
        return device_health(self.device, now=now or self.now)

    def test_a_device_that_reported_within_the_window_is_ok(self):
        health = self._seen_at(self.now - timedelta(hours=2))

        self.assertEqual(health['status'], 'ok')
        self.assertEqual(health['silence_hours'], 2.0)

    def test_a_device_quiet_across_a_working_day_is_silent(self):
        # Tuesday 08:00 to Wednesday 10:00 is 26 hours, and Tuesday was a day
        # people were expected to clock in.
        health = self._seen_at(self.now - timedelta(hours=26))

        self.assertEqual(health['status'], 'silent')
        self.assertEqual(health['silence_hours'], 26.0)
        self.assertIn('No punch', health['detail'])

    def test_a_quiet_weekend_is_not_an_alarm(self):
        """Friday evening to Sunday morning is silence nobody should be told
        about, and an alarm every Saturday is how a real one gets ignored."""
        sunday = timezone.make_aware(datetime(2026, 11, 1, 10, 0))
        health = self._seen_at(timezone.make_aware(
            datetime(2026, 10, 30, 17, 0)), now=sunday)

        self.assertEqual(health['status'], 'ok')
        self.assertIn('no working day', health['detail'])

    def test_the_monday_after_a_quiet_weekend_is_flagged(self):
        monday = timezone.make_aware(datetime(2026, 11, 2, 9, 0))
        health = self._seen_at(timezone.make_aware(
            datetime(2026, 10, 30, 17, 0)), now=monday)

        self.assertEqual(health['status'], 'silent')

    def test_a_public_holiday_is_not_a_working_day(self):
        # The gap is Tuesday 08:00 to Wednesday 10:00, so Wednesday is the day
        # an expectation would have come from - declare that one a holiday.
        PublicHoliday.objects.create(
            company=self.company, date=date(2026, 10, 28), name='Founders day')

        health = self._seen_at(self.now - timedelta(hours=26))

        self.assertEqual(health['status'], 'ok')
        self.assertIn('no working day', health['detail'])

    def test_silence_inside_a_single_day_is_still_measured(self):
        """The working-day gate must not excuse a gap inside one working day."""
        with override_settings(BIOMETRIC_SILENCE_HOURS=1):
            health = self._seen_at(self.now - timedelta(hours=4))

        self.assertEqual(health['status'], 'silent')

    def test_a_device_that_has_never_reported_is_flagged(self):
        health = device_health(self.device, now=self.now)

        self.assertEqual(health['status'], 'never_seen')
        self.assertIsNone(health['silence_hours'])

    def test_a_retired_device_is_not_monitored(self):
        self.device.status = 'retired'
        self.device.save(update_fields=['status'])

        health = self._seen_at(self.now - timedelta(days=10))

        self.assertEqual(health['status'], 'not_monitored')

    def test_a_punch_clears_the_flag_without_operator_action(self):
        # touch() stamps the real clock, so this case reads the real one too.
        self.device.last_seen_at = timezone.now() - timedelta(days=3)
        self.device.save(update_fields=['last_seen_at'])
        self.assertEqual(device_health(self.device)['status'], 'silent')

        self.device.touch()

        self.assertEqual(device_health(self.device)['status'], 'ok')

    def test_the_device_list_reports_health(self):
        self.device.last_seen_at = timezone.now() - timedelta(days=10)
        self.device.save(update_fields=['last_seen_at'])
        client = APIClient()
        client.force_authenticate(_user(self.company))

        response = client.get(DEVICES)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data[0]['health']['status'], 'silent')
        self.assertIn('detail', response.data[0]['health'])


class PunchThrottleTests(TestCase):
    """Punches are metered per terminal, not per address.

    The ingest endpoint cannot authenticate a user, so by default it would fall
    under DRF's anonymous per-IP budget: a building's terminals sharing one NAT
    would be squeezed by the browsers beside them. See biometrics/throttling.py.
    """

    def setUp(self):
        # Throttle counters live in the cache, which is process-wide.
        cache.clear()
        self.company = _company()
        self.device, self.raw_key = _device(self.company)
        self.employee = _employee(self.company)

    def _punch(self, device, key, punch_time):
        return APIClient().post(INGEST, {
            'device_id': device.device_id,
            'employee': self.employee.employee_code,
            'punch_time': punch_time, 'punch_type': 'in',
        }, format='json', HTTP_X_BIOMETRIC_DEVICE_KEY=key)

    def test_each_terminal_spends_its_own_budget(self):
        second, second_key = _device(self.company, 'ZK-002')

        # The rate is read from the scope's setting when a throttle instance is
        # built, so a test budget is supplied where it is read.
        with mock.patch.object(BiometricDeviceThrottle, 'get_rate',
                               return_value='2/hour'):
            first = self._punch(self.device, self.raw_key,
                               '2026-10-27T08:00:00+00:00')
            other = self._punch(second, second_key,
                               '2026-10-27T08:00:01+00:00')
            second_for_first = self._punch(self.device, self.raw_key,
                                          '2026-10-27T08:00:02+00:00')
            over = self._punch(self.device, self.raw_key,
                              '2026-10-27T08:00:03+00:00')

        self.assertEqual(first.status_code, 201, first.data)
        # A second terminal on the same address is unaffected by the first. It
        # is answered 202 because the employee is already clocked in - what
        # matters here is that it was not throttled.
        self.assertEqual(other.status_code, 202, other.data)
        self.assertEqual(second_for_first.status_code, 202,
                         second_for_first.data)
        self.assertEqual(over.status_code, 429, over.data)

    def test_a_request_with_no_device_identity_keeps_the_anonymous_budget(self):
        with mock.patch.object(AnonymousPunchThrottle, 'get_rate',
                               return_value='2/hour'):
            first = self._punch(self.device, '', '2026-10-27T08:00:00+00:00')
            second = self._punch(self.device, '', '2026-10-27T08:00:01+00:00')
            third = self._punch(self.device, '', '2026-10-27T08:00:02+00:00')

        # No key at all is a 400 - but the anonymous budget is what runs out.
        self.assertEqual(first.status_code, 400)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(third.status_code, 429)

    def test_a_wrong_key_is_throttled_as_that_claimed_device(self):
        """A device identity is claimed, then rejected. It is still counted, so
        guessing keys cannot be done at the anonymous rate."""
        with mock.patch.object(BiometricDeviceThrottle, 'get_rate',
                               return_value='2/hour'):
            first = self._punch(self.device, 'wrong-key',
                               '2026-10-27T08:00:00+00:00')
            second = self._punch(self.device, 'wrong-key',
                                '2026-10-27T08:00:01+00:00')
            third = self._punch(self.device, 'wrong-key',
                               '2026-10-27T08:00:02+00:00')

        self.assertEqual(first.status_code, 401)
        self.assertEqual(second.status_code, 401)
        self.assertEqual(third.status_code, 429)


class BatchIngestTests(TestCase):
    """A terminal that was offline flushes its queue in pages.

    One request per punch means a day of backlog is a day of round trips, and a
    per-request cap with no batching turns an outage into a refused queue.
    """

    def setUp(self):
        self.company = _company()
        self.device, self.raw_key = _device(self.company)
        self.employee = _employee(self.company)

    def _item(self, punch_time, punch_type='in', employee=None):
        return {'employee': employee or self.employee.employee_code,
                'punch_time': punch_time, 'punch_type': punch_type}

    def _batch(self, items, key=None):
        return APIClient().post(INGEST, {
            'device_id': self.device.device_id, 'punches': items,
        }, format='json',
            HTTP_X_BIOMETRIC_DEVICE_KEY=self.raw_key if key is None else key)

    def test_a_queue_flush_records_every_punch(self):
        response = self._batch([
            self._item('2026-10-27T08:00:00+00:00'),
            self._item('2026-10-27T17:00:00+00:00', 'out'),
            self._item('2026-10-28T08:00:00+00:00'),
        ])

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['received'], 3)
        self.assertEqual(response.data['recorded'], 3)
        self.assertEqual(response.data['duplicates'], 0)
        self.assertEqual(len(response.data['results']), 3)
        self.assertEqual(Attendance.objects.count(), 2)

    def test_a_resent_batch_is_answered_as_duplicates(self):
        items = [self._item('2026-10-27T08:00:00+00:00')]
        self._batch(items)

        response = self._batch(items)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['duplicates'], 1)
        self.assertEqual(response.data['recorded'], 0)
        self.assertTrue(response.data['results'][0]['duplicate'])
        self.assertEqual(BiometricPunch.objects.count(), 1)

    def test_one_unreadable_punch_does_not_discard_the_others(self):
        response = self._batch([
            self._item('2026-10-27T08:00:00+00:00'),
            self._item('not-a-timestamp'),
            self._item('2026-10-27T17:00:00+00:00', 'out'),
        ])

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['recorded'], 2)
        self.assertEqual(response.data['rejected'], 1)
        self.assertEqual(response.data['results'][1]['status'], 'rejected')
        self.assertIn('ISO-8601', response.data['results'][1]['error'])
        self.assertEqual(BiometricPunch.objects.count(), 2)

    def test_a_batch_of_only_unreadable_punches_fails_loudly(self):
        """A broken payload is not a quiet queue: answering 200 would leave the
        terminal retrying a request that can never succeed."""
        response = self._batch([self._item('nope'), self._item('2026-13-45')])

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('could be read', response.data['detail'])
        self.assertEqual(
            [r['status'] for r in response.data['results']],
            ['rejected', 'rejected'])

    def test_an_unmatched_punch_is_kept_for_reconciliation(self):
        response = self._batch([
            self._item('2026-10-27T08:00:00+00:00', employee='NOT-ENROLLED')])

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['needs_reconciliation'], 1)
        self.assertEqual(response.data['results'][0]['status'], 'ignored')
        self.assertEqual(Attendance.objects.count(), 0)

    def test_a_batch_cannot_reach_another_companys_employee(self):
        other = _company('OtherCo')
        other_employee = _employee(other, code='ZZ999')

        response = self._batch([self._item(
            '2026-10-27T08:00:00+00:00', employee=other_employee.employee_code)])

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Attendance.objects.filter(
            employee=other_employee).count(), 0)
        self.assertEqual(response.data['needs_reconciliation'], 1)

    def test_each_punch_keeps_its_own_device_offset(self):
        self._batch([self._item('2026-10-25T23:30:00-05:00')])

        self.assertEqual(
            BiometricPunch.objects.get().utc_offset_minutes, -300)

    def test_a_batch_is_capped_and_asks_for_pages(self):
        items = [self._item('2026-10-27T08:00:00+00:00')
                 for _ in range(MAX_PUNCH_BATCH + 1)]

        response = self._batch(items)

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('pages', response.data['detail'])
        self.assertEqual(BiometricPunch.objects.count(), 0)

    def test_an_empty_batch_is_rejected(self):
        response = self._batch([])

        self.assertEqual(response.status_code, 400, response.data)

    def test_punches_must_be_a_list(self):
        response = APIClient().post(INGEST, {
            'device_id': self.device.device_id,
            'punches': {'employee': self.employee.employee_code},
        }, format='json', HTTP_X_BIOMETRIC_DEVICE_KEY=self.raw_key)

        self.assertEqual(response.status_code, 400, response.data)

    def test_a_batch_still_requires_the_device_key(self):
        response = self._batch(
            [self._item('2026-10-27T08:00:00+00:00')], key='')

        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(BiometricPunch.objects.count(), 0)
