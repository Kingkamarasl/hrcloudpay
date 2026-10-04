"""Bulk employee import.

The bug these pin: `import_csv` created unconditionally, so importing the same
file twice produced two employee records per row. The (company, employee_code)
constraint could not catch it because `employee_code` is allocated per row with
a random four-digit suffix and the serializer discards any client-supplied
value, so no two rows ever collided. `email` had no uniqueness of its own.

That is not cosmetic. Two Employee rows means two payslips, two attendance
histories, two of everything downstream - and an attendance import that
resolves by email cannot tell which one it meant.
"""
import csv
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import AuditLog, Company, Subscription, User
from employees.models import Department, Employee

IMPORT = '/api/employees/employees/import-csv/'

HEADERS = ['first_name', 'last_name', 'email', 'phone', 'job_title',
           'department', 'base_salary']


def upload(rows, headers=None, name='employees.csv'):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers or HEADERS)
    for row in rows:
        writer.writerow(row)
    return SimpleUploadedFile(
        name, buffer.getvalue().encode('utf-8'), content_type='text/csv')


ROWS = [
    ['Ada', 'One', 'ada@example.com', '0801', 'Engineer', 'Sales', '500000'],
    ['Ben', 'Two', 'ben@example.com', '0802', 'Analyst', 'Sales', '400000'],
]


class EmployeeImportTestCase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Acme', email='acme@example.com', is_active=True, plan='starter',
        )
        Subscription.objects.create(
            company=self.company, status='active',
        )
        Department.objects.create(company=self.company, name='Sales')
        self.hr = User.objects.create_user(
            username='hr', email='hr@example.com',
            password='StrongPassword123!', company=self.company, role='hr',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.hr)

    def do_import(self, upload_file=None):
        return self.client.post(
            IMPORT, {'file': upload_file or upload(ROWS)}, format='multipart')


class DuplicatePreventionTests(EmployeeImportTestCase):
    def test_importing_the_same_file_twice_does_not_duplicate(self):
        """The reported bug: the second run must not add rows."""
        first = self.do_import()
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(first.data['created'], 2)

        second = self.do_import()

        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(second.data['created'], 0)
        self.assertEqual(second.data['updated'], 2)
        self.assertEqual(Employee.objects.count(), 2)

    def test_a_second_run_updates_rather_than_adds(self):
        self.do_import()
        changed = [['Ada', 'One-Smith', 'ada@example.com', '0801', 'Principal',
                    'Sales', '900000']]

        response = self.do_import(upload(changed))

        self.assertEqual(response.data['created'], 0)
        self.assertEqual(response.data['updated'], 1)
        ada = Employee.objects.get(email='ada@example.com')
        self.assertEqual(ada.last_name, 'One-Smith')
        self.assertEqual(ada.base_salary, 900000)
        self.assertEqual(Employee.objects.count(), 2)

    def test_matching_is_case_insensitive_on_email(self):
        """A spreadsheet that re-cases an address is the same person."""
        self.do_import()
        recased = [['Ada', 'One', 'ADA@EXAMPLE.COM', '', '', '', '']]

        response = self.do_import(upload(recased))

        self.assertEqual(response.data['created'], 0)
        self.assertEqual(Employee.objects.count(), 2)

    def test_the_same_email_in_another_company_is_a_different_person(self):
        """Tenancy: two companies may each have an ada@example.com."""
        other = Company.objects.create(
            name='Globex', email='globex@example.com', is_active=True, plan='starter')
        Subscription.objects.create(company=other, status='active')
        Employee.objects.create(
            company=other, employee_code='OTH-1',
            first_name='Ada', last_name='Elsewhere', email='ada@example.com')

        response = self.do_import()

        self.assertEqual(response.data['created'], 2)
        self.assertEqual(Employee.objects.filter(company=other).count(), 1)

    def test_a_duplicate_inside_one_file_does_not_create_two(self):
        rows = [
            ['Ada', 'One', 'ada@example.com', '', '', '', ''],
            ['Ada', 'One', 'ada@example.com', '', '', '', ''],
        ]
        response = self.do_import(upload(rows))

        self.assertEqual(response.data['created'], 1)
        self.assertEqual(response.data['updated'], 1)
        self.assertEqual(Employee.objects.count(), 1)


class ImportValidationTests(EmployeeImportTestCase):
    def test_missing_required_fields_are_reported_per_row(self):
        rows = [['NoEmail', 'Person', '', '', '', '', '']]

        response = self.do_import(upload(rows))

        self.assertEqual(response.data['created'], 0)
        self.assertEqual(response.data['failed'], 1)
        self.assertIn('first_name', response.data['failures'][0]['error'])

    def test_a_good_row_still_imports_alongside_a_bad_one(self):
        rows = [
            ['Ada', 'One', 'ada@example.com', '', '', '', ''],
            ['', '', '', '', '', '', ''],
        ]
        response = self.do_import(upload(rows))

        self.assertEqual(response.data['created'], 1)
        self.assertEqual(response.data['failed'], 1)

    def test_an_unknown_department_is_reported_not_silently_dropped(self):
        rows = [['Ada', 'One', 'ada@example.com', '', '', 'Nonexistent', '']]

        response = self.do_import(upload(rows))

        self.assertEqual(response.data['created'], 0)
        self.assertIn('Nonexistent', response.data['failures'][0]['error'])

    def test_a_department_is_matched_by_name(self):
        """The old code passed the cell as a foreign key, so this never worked."""
        rows = [['Ada', 'One', 'ada@example.com', '', '', 'Sales', '']]

        response = self.do_import(upload(rows))

        self.assertEqual(response.data['created'], 1, response.data)
        ada = Employee.objects.get()
        self.assertEqual(ada.department, 'Sales')
        self.assertIsNotNone(ada.department_obj)

    def test_a_non_csv_file_is_refused(self):
        response = self.do_import(upload(ROWS, name='employees.xlsx'))
        self.assertEqual(response.status_code, 400)

    def test_a_missing_file_is_refused(self):
        response = self.client.post(IMPORT, {}, format='multipart')
        self.assertEqual(response.status_code, 400)

    def test_employees_cannot_import(self):
        worker = User.objects.create_user(
            username='w', email='w@example.com', password='StrongPassword123!',
            company=self.company, role='employee')
        self.client.force_authenticate(worker)

        self.assertEqual(self.do_import().status_code, 403)
        self.assertEqual(Employee.objects.count(), 0)


class ImportAuditTests(EmployeeImportTestCase):
    def test_an_import_is_audited(self):
        """The old import wrote no audit row at all - the only mutating path
        in the employees app that did not."""
        self.do_import()

        entry = AuditLog.objects.filter(target_type='employee').first()
        self.assertIsNotNone(entry, 'importing employees wrote no audit row')
        self.assertEqual(entry.metadata['created'], 2)

    def test_a_re_run_is_audited_too(self):
        self.do_import()
        self.do_import()

        entries = AuditLog.objects.filter(target_type='employee')
        self.assertEqual(entries.count(), 2)
        self.assertEqual(
            sorted(e.metadata['created'] for e in entries), [0, 2])

    def test_an_import_that_changed_nothing_writes_no_audit_row(self):
        upload(ROWS, name='bad.csv')  # wrong columns -> nothing applied
        self.client.post(IMPORT, {'file': upload(['', '', '', '', '', '', ''])},
                         format='multipart')

        self.assertEqual(
            AuditLog.objects.filter(target_type='employee').count(), 0)
