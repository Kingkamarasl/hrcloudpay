"""One employee per email address per company, enforced by the database.

Importing a file twice was originally free to create two employees per row, and
fixing only that endpoint left the same failure reachable by a plain
`POST /api/employees/employees/`. This constraint closes the other doors.

The (company, employee_code) index cannot do it: codes carry a random four-digit
suffix allocated per row, so a duplicate person lands on a fresh code and the
index never fires.

Two details are deliberate and tested below. The index is on Lower(email),
because the CSV import already treats `Ada@example.com` and `ada@example.com` as
one person - a case-sensitive index would let the database hold both and put it
at odds with the import. And blank addresses are excluded from the index, so two
employees who have not supplied one do not collide on having nothing.
"""
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import Company, Subscription, User
from employees.models import Employee


def make_company(name):
    company = Company.objects.create(
        name=name, email='%s@example.com' % name.lower(),
        is_active=True, plan='starter',
    )
    Subscription.objects.create(company=company, status='active')
    return company


def make_employee(company, email, code, first='Ada'):
    return Employee.objects.create(
        company=company,
        employee_code=code,
        first_name=first,
        last_name='One',
        email=email,
    )


class UniqueEmployeeEmailTests(TestCase):
    def setUp(self):
        self.company = make_company('acme')

    def assertRejected(self, **kwargs):
        with self.assertRaises(IntegrityError):
            # Savepoint, or the failed statement poisons the test transaction.
            with transaction.atomic():
                make_employee(self.company, **kwargs)

    def test_the_same_address_twice_is_refused(self):
        make_employee(self.company, email='ada@example.com', code='LT-0001')

        self.assertRejected(email='ada@example.com', code='LT-0002')

        self.assertEqual(Employee.objects.filter(company=self.company).count(), 1)

    def test_a_re_cased_address_is_refused(self):
        """The import matches with email__iexact, so this is the same person.

        A case-sensitive index would accept both rows and leave the database
        holding two employees that the import considers one.
        """
        make_employee(self.company, email='ada@example.com', code='LT-0001')

        self.assertRejected(email='ADA@Example.COM', code='LT-0002')

    def test_another_company_may_hold_the_same_address(self):
        other = make_company('globex')
        make_employee(self.company, email='ada@example.com', code='LT-0001')

        make_employee(other, email='ada@example.com', code='LT-0001')

        self.assertEqual(Employee.objects.filter(email='ada@example.com').count(), 2)

    def test_two_blank_addresses_do_not_collide(self):
        """No address supplied is not a collision on an address."""
        make_employee(self.company, email='', code='LT-0001')

        make_employee(self.company, email='', code='LT-0002')

        self.assertEqual(Employee.objects.filter(company=self.company).count(), 2)

    def test_a_different_address_is_unaffected(self):
        make_employee(self.company, email='ada@example.com', code='LT-0001')

        make_employee(self.company, email='ben@example.com', code='LT-0002')

        self.assertEqual(Employee.objects.filter(company=self.company).count(), 2)

    def test_the_code_index_still_stands(self):
        """The original constraint is not replaced, only joined."""
        make_employee(self.company, email='ada@example.com', code='LT-0001')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_employee(self.company, email='ben@example.com', code='LT-0001')

    def test_a_re_import_does_not_trip_the_database(self):
        """The endpoint updates rather than inserts, so no conflict arises.

        This is the whole point of the pair of changes: the import resolves the
        duplicate itself, and the constraint is the backstop for everything that
        does not go through the import.
        """
        user = User.objects.create_user(
            username='hr', email='hr@example.com', password='StrongPassword123!',
            company=self.company, role='hr',
        )
        self.assertEqual(user.company, self.company)

        from rest_framework.test import APIClient
        import csv
        import io as _io
        from django.core.files.uploadedfile import SimpleUploadedFile

        def build():
            # A fresh object each time: an uploaded file is a consumed stream, so
            # reusing one would post an empty body and prove nothing.
            buffer = _io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(['first_name', 'last_name', 'email'])
            writer.writerow(['Ada', 'One', 'ada@example.com'])
            return SimpleUploadedFile(
                'e.csv', buffer.getvalue().encode('utf-8'),
                content_type='text/csv')

        client = APIClient()
        client.force_authenticate(user)
        url = '/api/employees/employees/import-csv/'

        first = client.post(url, {'file': build()}, format='multipart')
        self.assertEqual(first.status_code, 201, first.data)
        second = client.post(url, {'file': build()}, format='multipart')

        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(second.data['created'], 0)
        self.assertEqual(Employee.objects.filter(company=self.company).count(), 1)


class DuplicateEmailIsAValidationErrorTests(TestCase):
    """The index has to reach the caller as a 400, not a 500.

    An IntegrityError escaping from the save becomes a 500 carrying a trace
    page. That is the wrong answer to "this address is already in use" - it
    tells the person nothing and hands them internals.
    """

    def setUp(self):
        from rest_framework.test import APIClient

        self.company = make_company('acme')
        self.user = User.objects.create_user(
            username='hr', email='hr@example.com', password='StrongPassword123!',
            company=self.company, role='hr',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = '/api/employees/employees/'
        self.existing = make_employee(
            self.company, email='ada@example.com', code='LT-0001')

    def payload(self, email, **extra):
        body = {
            'first_name': 'Ada', 'last_name': 'One', 'email': email,
            'employment_status': 'active', 'employment_category': 'long_time',
        }
        body.update(extra)
        return body

    def test_posting_a_duplicate_address_is_a_400(self):
        response = self.client.post(
            self.url, self.payload('ada@example.com'), format='json')

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('email', response.data)
        self.assertEqual(Employee.objects.filter(company=self.company).count(), 1)

    def test_the_message_names_the_employee_already_holding_it(self):
        response = self.client.post(
            self.url, self.payload('ada@example.com'), format='json')

        message = str(response.data['email'])
        self.assertIn('Ada One', message)
        self.assertIn('LT-0001', message)

    def test_a_re_cased_duplicate_is_also_a_400(self):
        """Matching only exactly would let this reach the index and 500."""
        response = self.client.post(
            self.url, self.payload('ADA@Example.COM'), format='json')

        self.assertEqual(response.status_code, 400, response.data)

    def test_editing_an_employee_without_changing_its_address_is_allowed(self):
        """Self-exclusion: keeping your own address is not a clash."""
        response = self.client.patch(
            '%s%s/' % (self.url, self.existing.id),
            {'job_title': 'Principal'}, format='json')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['job_title'], 'Principal')

    def test_editing_an_employee_to_another_persons_address_is_refused(self):
        make_employee(self.company, email='ben@example.com', code='LT-0002')

        response = self.client.patch(
            '%s%s/' % (self.url, self.existing.id),
            {'email': 'ben@example.com'}, format='json')

        self.assertEqual(response.status_code, 400, response.data)

    def test_another_company_may_hold_the_same_address(self):
        other = make_company('globex')
        self.user.company = other
        self.user.save(update_fields=['company'])

        response = self.client.post(
            self.url, self.payload('ada@example.com'), format='json')

        self.assertEqual(response.status_code, 201, response.data)
