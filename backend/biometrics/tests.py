"""Biometric attendance ingestion.

A biometric terminal has no user account and no browser. It authenticates with
an API key, reports a punch, and the server turns that into an attendance
record. These tests pin the contract on both sides of that exchange, because a
punch that is silently dropped or silently mis-attributed becomes a payroll
correction nobody can trace.
"""

from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Company, User
from attendance.models import Attendance
from biometrics.models import BiometricDevice, BiometricEnrollment, BiometricPunch
from employees.models import Employee

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