"""Where uploads go, and whether that place survives a redeploy.

S3 support is complete: `STORAGES` switches to `storages.backends.s3.S3Storage`
when `AWS_STORAGE_BUCKET_NAME` is set. The failure is not a missing feature but
a missing signal. With the bucket unset every upload lands in the container's
MEDIA_ROOT, every write succeeds, nothing errors, and the contracts and national
ID scans a tenant uploaded are gone on the next rebuild — with the console
reporting healthy right up until then.

These pin the check that makes that visible. A health endpoint that cannot say
"your uploads are not being stored anywhere durable" is not reporting the thing
most likely to destroy a customer's data.
"""
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User

HEALTH_URL = reverse('platform-system-health')


class StorageHealthTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='root', email='root@example.com',
            password='Str0ngPass-2026!', company=None,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def check(self, key='storage'):
        response = self.client.get(HEALTH_URL)
        self.assertEqual(response.status_code, 200, response.data)
        return next(c for c in response.data['checks'] if c['key'] == key)

    @override_settings(AWS_STORAGE_BUCKET_NAME='', DEBUG=False)
    def test_local_storage_in_production_is_critical(self):
        """Not a warning. The data is genuinely destroyed by the next rebuild,
        and a warning is the severity that gets ignored."""
        result = self.check()

        self.assertEqual(result['status'], 'critical')
        self.assertIn('deleted by the next rebuild', result['detail'])

    @override_settings(AWS_STORAGE_BUCKET_NAME='', DEBUG=False)
    def test_the_critical_detail_names_the_setting_to_set(self):
        """A health check that says something is wrong without saying what to do
        is a support ticket rather than a fix."""
        result = self.check()

        self.assertIn('AWS_STORAGE_BUCKET_NAME', result['detail'])

    @override_settings(AWS_STORAGE_BUCKET_NAME='', DEBUG=True)
    def test_local_storage_in_development_is_only_a_warning(self):
        """Otherwise the check cries wolf on every developer's machine and gets
        ignored exactly where it matters."""
        result = self.check()

        self.assertEqual(result['status'], 'warning')
        self.assertIn('development', result['detail'])

    @override_settings(AWS_STORAGE_BUCKET_NAME='', DEBUG=False)
    def test_it_reports_the_backend_actually_in_use(self):
        """Not the configured name - the resolved one. They differ when a setting
        is read at import time and overridden later, which is precisely when
        assuming is wrong."""
        result = self.check()

        self.assertIn('FileSystemStorage', result['backend'])
        self.assertIsNone(result['bucket'])

    @override_settings(
        AWS_STORAGE_BUCKET_NAME='hrcloudpay-uploads',
        DEBUG=False,
        STORAGES={
            'default': {'BACKEND': 'storages.backends.s3.S3Storage'},
            'staticfiles': {
                'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
            },
        },
    )
    def test_a_configured_bucket_is_healthy(self):
        result = self.check()

        self.assertEqual(result['status'], 'healthy')
        self.assertIn('hrcloudpay-uploads', result['detail'])

    @override_settings(AWS_STORAGE_BUCKET_NAME='', DEBUG=False)
    def test_the_check_appears_alongside_the_others(self):
        """A check nothing renders is the same as no check."""
        response = self.client.get(HEALTH_URL)
        keys = [c['key'] for c in response.data['checks']]

        self.assertIn('database', keys)
        self.assertIn('storage', keys)
        self.assertIn('audit', keys)

    @override_settings(AWS_STORAGE_BUCKET_NAME='', DEBUG=False)
    def test_the_check_does_not_break_the_endpoint(self):
        """Every existing check still runs; storage is additive."""
        response = self.client.get(HEALTH_URL)

        self.assertEqual(response.status_code, 200)
        for entry in response.data['checks']:
            self.assertIn(entry['status'], ('healthy', 'warning', 'critical'))


class StorageHealthAccessTests(TestCase):
    @override_settings(AWS_STORAGE_BUCKET_NAME='', DEBUG=False)
    def test_a_tenant_admin_cannot_read_it(self):
        from accounts.models import Company

        company = Company.objects.create(
            name='Acme', email='acme@example.com', is_active=True, plan='starter')
        worker = User.objects.create_user(
            username='owner', email='owner@example.com',
            password='Str0ngPass-2026!', company=company, role='owner',
        )
        client = APIClient()
        client.force_authenticate(worker)

        self.assertEqual(client.get(HEALTH_URL).status_code, 403)