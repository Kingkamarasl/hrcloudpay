"""
Regression tests for the security-app bug-fix pass.

The headline defect here was silent and total: `backend/security/migrations/` was
missing its `__init__.py`, so Django's migration loader never saw
`security.0001_initial` and `manage.py migrate` created NONE of the app's 19
tables. The whole test suite stayed green because Django's test runner defaults
to ``run_syncdb=True``, which builds tables straight from the models for any app
it believes has no migrations - so the tests exercised a schema that no real
database ever gets. On the dev database the first symptom was the public login
page returning HTTP 500, because ``SecureLoginView`` reads the MFA device
unguarded and `security_mfadevice` did not exist.
"""
from django.apps import apps
from django.db import DatabaseError, connection
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Company, User
from security.models import MFADevice

LOGIN_URL = '/api/auth/security/login/'
PASSWORD = 'StrongPassword123!'


def drop_table(name):
    with connection.cursor() as cursor:
        cursor.execute(f'DROP TABLE IF EXISTS "{name}"')


def recreate_table(model):
    with connection.schema_editor() as editor:
        editor.create_model(model)


# --------------------------------------------------------------------------
# Root cause: the migration package was not a package, so `migrate` silently
# skipped the entire app.
# --------------------------------------------------------------------------
class SecurityMigrationDiscoveryTests(TestCase):
    def test_security_migrations_package_is_importable(self):
        """A migrations dir without __init__.py is a namespace package.

        Django imports it successfully and then silently discovers zero
        migrations, so nothing errors and nothing is created.
        """
        import security.migrations
        self.assertTrue(
            hasattr(security.migrations, '__file__') and security.migrations.__file__,
            'security/migrations/__init__.py is missing - Django will not discover '
            'security.0001_initial and `migrate` will create none of its tables',
        )

    def test_initial_migration_is_discoverable(self):
        loader = MigrationLoader(connection)
        self.assertIn(
            ('security', '0001_initial'), loader.disk_migrations,
            'security.0001_initial is not being loaded; `migrate` cannot apply it',
        )

    def test_every_installed_app_has_a_real_migrations_package(self):
        """Guards the whole class of bug, not just this one app."""
        import importlib
        broken = []
        for label in ('accounts', 'employees', 'payroll', 'attendance', 'leave',
                      'integrations', 'workflows', 'regional', 'ai', 'security'):
            app_config = apps.get_app_config(label)
            try:
                module = importlib.import_module(f'{app_config.name}.migrations')
            except ModuleNotFoundError:
                continue
            if not getattr(module, '__file__', None):
                broken.append(label)
        self.assertEqual(
            broken, [],
            f'these apps have a migrations/ dir with no __init__.py, so Django '
            f'discovers no migrations for them: {broken}',
        )

    def test_security_tables_exist_in_the_database(self):
        """The live schema must actually have the app's tables."""
        # connection.introspection.table_names() rather than a literal query.
        # This read `sqlite_master`, which exists only in SQLite, so on the
        # Postgres that Docker and CI both run it died with UndefinedTable
        # before checking anything. The test guarding "the migration actually
        # created the tables" had never once verified that on a real database.
        present = set(connection.introspection.table_names())
        missing = [
            m._meta.db_table for m in apps.get_app_config('security').get_models()
            if m._meta.db_table not in present
        ]
        self.assertEqual(missing, [], f'security tables missing from the database: {missing}')


# --------------------------------------------------------------------------
# Symptom: the public login page returned 500 on a database where the security
# migration had never been applied.
#
# These drop and rebuild a real table, so they need TransactionTestCase:
# SQLite refuses to run the schema editor inside TestCase's wrapping atomic
# block.
# --------------------------------------------------------------------------
class LoginWithoutSecuritySchemaTests(TransactionTestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='No Schema Co', email='noschema@example.com', is_active=True,
        )
        self.user = User.objects.create_user(
            username='noschema', email='noschema@example.com',
            password=PASSWORD, company=self.company, role='owner',
        )
        self.client = APIClient()
        self.credentials = {'username': 'noschema', 'password': PASSWORD}

    def tearDown(self):
        """A leaked DROP must fail here, not three tests later.

        These tests drop a real table out of the shared test database. The
        `finally` blocks rebuild it, but nothing verified that they ran: when
        the body raised something unexpected the rebuild was skipped and
        `security_mfadevice` stayed missing for every test that followed,
        surfacing as `relation ... does not exist` in unrelated tests in other
        apps. Asserting it here turns that silent cross-test contamination
        into an obvious failure at the point it happens.
        """
        self.assertIn(
            MFADevice._meta.db_table,
            set(connection.introspection.table_names()),
            f'{MFADevice._meta.db_table} was dropped for a test and never '
            'restored. Every test after this one is now running against a '
            'schema no real deployment has, so their results mean nothing.',
        )

    def test_login_does_not_500_when_the_mfa_table_is_missing(self):
        """This is the exact failure the user hit: sign-in was impossible."""
        drop_table('security_mfadevice')
        try:
            with override_settings(DEBUG=True):
                response = self.client.post(LOGIN_URL, self.credentials, format='json')
            self.assertEqual(
                response.status_code, 200,
                'login must not hard-fail when the security migration is unapplied',
            )
            self.assertEqual(response.data['user']['username'], 'noschema')
        finally:
            recreate_table(MFADevice)

    def test_login_still_fails_closed_in_production(self):
        """The DEBUG tolerance must not weaken production authentication."""
        drop_table('security_mfadevice')
        try:
            with override_settings(DEBUG=False):
                # DatabaseError, not OperationalError: the two backends report a
                # missing table with different exception types. SQLite raises
                # OperationalError ("no such table"), Postgres raises
                # ProgrammingError ("relation ... does not exist"). Both are
                # DatabaseError subclasses, so this asserts the actual
                # requirement - the request fails rather than quietly
                # authenticating - on either backend. Pinning the subclass to
                # SQLite's meant this passed locally and failed in CI.
                with self.assertRaises(DatabaseError):
                    self.client.post(LOGIN_URL, self.credentials, format='json')
        finally:
            recreate_table(MFADevice)

    def test_login_still_issues_a_real_session_cookie(self):
        response = self.client.post(LOGIN_URL, self.credentials, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('hrcloudpay_session', response.cookies)
        self.assertTrue(response.cookies['hrcloudpay_session'].value)

    def test_mfa_challenge_is_still_issued_when_the_device_exists(self):
        """The guard must not have disabled MFA itself."""
        MFADevice.objects.create(user=self.user, secret_encrypted='x', enabled=True)
        response = self.client.post(LOGIN_URL, self.credentials, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['mfa_required'])
        self.assertIn('hrcloudpay_mfa_challenge', response.cookies)

    def test_login_rejects_a_disabled_account(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        response = self.client.post(LOGIN_URL, self.credentials, format='json')
        self.assertIn(response.status_code, (401, 403))
