"""Uploaded files must survive a deploy, and must not be public when they don't.

Two separate defects are pinned here, because they are separate and one was
hiding the other:

* **Loss.** ``MEDIA_ROOT`` is a directory on the machine running Django. On a
  container platform it is part of the image's writable layer, so each deploy
  destroys every employee document, contract and knowledge source uploaded since
  the last one. These tests check the storage backend is chosen from the
  environment rather than assumed.

* **Exposure.** The old route for these files was Django's ``static()`` helper,
  registered only under ``DEBUG``. So in production nothing was reachable at
  all - company logos and employee photos 404, because the SPA is handed
  absolute ``/media/`` URLs - and the obvious repair, registering ``static()``
  unconditionally, would have served every identity, medical and disciplinary
  document in the system to anyone holding the URL. ``static()`` has no identity
  check, and these filenames sit under a date directory, which is obscurity
  rather than access control.

The access tests use real rows rather than a mocked permission call, because the
rules differ per *kind* of file: a company logo is visible to the whole company,
an import export only to an owner, and ``finance`` may run payroll without ever
seeing an employee's medical certificate.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image as PILImage

from accounts.models import Company, User
from employees.models import Employee, EmployeeDocument

BACKEND_DIR = Path(__file__).resolve().parent.parent

MEDIA_TMP = tempfile.mkdtemp(prefix='hrcloudpay-media-test-')
override_media = override_settings(MEDIA_ROOT=MEDIA_TMP)


def png_bytes(colour=(20, 120, 90), size=(40, 24)):
    buffer = io.BytesIO()
    PILImage.new('RGB', size, colour).save(buffer, format='PNG')
    return buffer.getvalue()


def settings_report(**environment):
    """Evaluate hrcloudpay.settings in a clean subprocess and report key values.

    Reloading the settings module inside the test process would mutate the
    module object that django.conf.settings still points at, leaking state into
    every later test in the run. A subprocess cannot, and it also proves the
    configuration works from a cold start, which is what a deploy actually does.
    """
    script = (
        'import os, sys, json;'
        'sys.path.insert(0, %r);'
        'os.environ["DJANGO_SETTINGS_MODULE"] = "hrcloudpay.settings";'
        'import django; django.setup();'
        'from django.conf import settings;'
        'print(json.dumps({'
        '"default": settings.STORAGES["default"]["BACKEND"],'
        '"staticfiles": settings.STORAGES["staticfiles"]["BACKEND"],'
        '}))' % str(BACKEND_DIR)
    )
    child = {**os.environ, **{k: v for k, v in environment.items()}}
    result = subprocess.run(
        [sys.executable, '-c', script],
        capture_output=True, text=True, cwd=str(BACKEND_DIR), env=child, timeout=180,
    )
    if result.returncode != 0:
        return {'error': result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'failed'}
    return json.loads(result.stdout.strip().splitlines()[-1])


@override_media
class MediaRouteOrderingTests(SimpleTestCase):
    """The media route has to win over the SPA catch-all.

    Django resolves urlpatterns in order, and the catch-all matches every path
    that is not admin or api - including ``/media/...``. If the media route is
    ever moved below it, an unauthorised request for an employee document
    returns ``index.html`` with a **200**, not a 404: the access check never
    runs, the browser is handed the SPA shell, and nothing anywhere reports an
    error. That is a silent security regression, which is why the ordering is
    asserted directly instead of being left to a code comment.
    """

    def test_a_media_url_resolves_to_the_guarded_view(self):
        from django.urls import resolve
        from hrcloudpay import views

        matched = resolve('/media/employee_documents/2026/01/fit.pdf')
        self.assertIs(matched.func, views.serve_media)

    def test_the_spa_shell_is_not_what_a_media_url_returns(self):
        """The failure mode is a 200 of index.html, not an error."""
        from django.urls import resolve
        from hrcloudpay import views

        self.assertIsNot(resolve('/media/anything.png').func, views.serve_frontend)

    def test_the_catch_all_still_serves_ordinary_spa_routes(self):
        """Guarding media must not come at the cost of the SPA itself."""
        from django.urls import resolve
        from hrcloudpay import views

        self.assertIs(resolve('/dashboard').func, views.serve_frontend)


@override_media
class MediaStorageSettingsTests(TestCase):
    """The storage backend has to follow the environment, not a constant."""

    def test_local_development_keeps_a_local_directory(self):
        from django.conf import settings
        self.assertEqual(
            settings.STORAGES['default']['BACKEND'],
            'django.core.files.storage.FileSystemStorage',
        )

    def test_setting_a_bucket_switches_uploads_to_object_storage(self):
        """Proves the S3 branch is reachable, not just present as dead text."""
        report = settings_report(
            AWS_STORAGE_BUCKET_NAME='hrcloudpay-media-test',
            AWS_S3_REGION_NAME='eu-west-1',
        )
        self.assertEqual(report.get('default'), 'storages.backends.s3.S3Storage')
        # Static files must NOT follow the bucket: the built frontend is not
        # user data and is served by WhiteNoise from local disk.
        self.assertEqual(
            report.get('staticfiles'),
            'django.contrib.staticfiles.storage.StaticFilesStorage',
        )

    def test_no_bucket_means_no_object_storage(self):
        report = settings_report(AWS_STORAGE_BUCKET_NAME='', AWS_S3_REGION_NAME='')
        self.assertEqual(
            report.get('default'), 'django.core.files.storage.FileSystemStorage'
        )

    def test_a_bucket_without_a_region_fails_loudly_at_startup(self):
        """Silently defaulting the region would fail on the first upload."""
        report = settings_report(
            AWS_STORAGE_BUCKET_NAME='hrcloudpay-media-test', AWS_S3_REGION_NAME=''
        )
        self.assertIn('AWS_S3_REGION_NAME must be set', report.get('error', ''))


@override_media
class MediaAccessTests(TestCase):
    """Per-kind role rules, enforced against real rows."""

    def setUp(self):
        self.company = Company.objects.create(name='Acme Ltd', email='acme@example.com')
        self.other = Company.objects.create(name='Other Ltd', email='other@example.com')

        def user(username, role, company, **extra):
            return User.objects.create_user(
                username=username, password='pw-not-used-in-these-tests-1234',
                email=f'{username}@example.com', role=role, company=company, **extra,
            )

        self.owner = user('owner', 'owner', self.company)
        self.hr = user('hr', 'hr', self.company)
        self.finance = user('finance', 'finance', self.company)
        self.staff_employee = user('worker', 'employee', self.company)
        self.other_owner = user('other-owner', 'owner', self.other)

        self.employee = Employee.objects.create(
            company=self.company, employee_code='E1', first_name='Ada',
            department='Engineering',
            profile_photo=SimpleUploadedFile('ada.png', png_bytes(), content_type='image/png'),
        )
        self.employee.user = self.staff_employee
        self.employee.save(update_fields=['user'])

        self.document = EmployeeDocument.objects.create(
            employee=self.employee, document_type='medical', title='Fit for work',
            document=SimpleUploadedFile('fit.pdf', b'%PDF-1.4 fake', content_type='application/pdf'),
        )
        self.document_name = self.document.document.name

    def url(self, name):
        return f'/media/{name}'

    def test_anonymous_is_refused(self):
        response = self.client.get(self.url(self.document_name))
        self.assertEqual(response.status_code, 401)

    def test_hr_may_read_a_medical_document(self):
        self.client.force_login(self.hr)
        response = self.client.get(self.url(self.document_name))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 fake')

    def test_the_employee_may_read_their_own_document(self):
        self.client.force_login(self.staff_employee)
        self.assertEqual(self.client.get(self.url(self.document_name)).status_code, 200)

    def test_finance_is_refused_an_employee_medical_document(self):
        """Finance holds payroll authority but no employee-record access."""
        self.client.force_login(self.finance)
        self.assertEqual(self.client.get(self.url(self.document_name)).status_code, 404)

    def test_another_tenant_is_refused(self):
        self.client.force_login(self.other_owner)
        self.assertEqual(self.client.get(self.url(self.document_name)).status_code, 404)

    def test_a_refusal_does_not_reveal_that_the_file_exists(self):
        """404 rather than 403, so the answer is indistinguishable."""
        self.client.force_login(self.finance)
        self.assertEqual(
            self.client.get(self.url(self.document_name)).status_code,
            self.client.get(self.url('employee_documents/nope.pdf')).status_code,
        )

    def test_a_company_logo_is_visible_to_the_whole_company(self):
        self.company.logo = SimpleUploadedFile('logo.png', png_bytes(), content_type='image/png')
        self.company.save(update_fields=['logo'])
        self.client.force_login(self.staff_employee)
        self.assertEqual(self.client.get(self.url(self.company.logo.name)).status_code, 200)

    def test_a_company_logo_is_not_visible_to_another_tenant(self):
        self.company.logo = SimpleUploadedFile('logo.png', png_bytes(), content_type='image/png')
        self.company.save(update_fields=['logo'])
        self.client.force_login(self.other_owner)
        self.assertEqual(self.client.get(self.url(self.company.logo.name)).status_code, 404)

    def test_a_name_under_a_known_prefix_with_no_row_is_refused(self):
        """A file left behind by a rollback must not become readable."""
        self.client.force_login(self.owner)
        response = self.client.get(self.url('employee_documents/orphan.pdf'))
        self.assertEqual(response.status_code, 404)

    def test_a_name_outside_every_known_prefix_is_refused(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url('../../etc/passwd')).status_code, 404)

    def test_traversal_is_refused(self):
        """The path is attacker-controlled and must not escape the namespace."""
        self.client.force_login(self.owner)
        for attempt in (
            'employee_documents/../../hrcloudpay/settings.py',
            'employee_documents/..%2f..%2fdb.sqlite3',
            '/etc/passwd',
        ):
            with self.subTest(attempt=attempt):
                self.assertEqual(self.client.get(self.url(attempt)).status_code, 404)

    def test_a_pdf_opens_in_the_browser(self):
        """Inline is deliberate: these are documents staff need to read.

        The real browser-execution risk from an uploaded file is HTML or SVG,
        which the next two tests cover. A PDF is rendered by the browser's own
        viewer, and forcing a download for every payslip and contract would be
        a worse product than the small residual risk.
        """
        self.client.force_login(self.hr)
        response = self.client.get(self.url(self.document_name))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('attachment', response.get('Content-Disposition', ''))
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

    def test_an_uploaded_html_file_is_forced_to_attach(self):
        """Stops a stored .html executing in the app's own origin."""
        hostile = EmployeeDocument.objects.create(
            employee=self.employee, document_type='other', title='Notes',
            document=SimpleUploadedFile(
                'notes.html', b'<script>fetch("/api/auth/whoami")</script>',
                content_type='text/html',
            ),
        )
        self.client.force_login(self.hr)
        response = self.client.get(self.url(hostile.document.name))
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

    def test_an_uploaded_svg_is_forced_to_attach(self):
        """SVG is a document that can carry script, so it is not shown inline."""
        hostile = EmployeeDocument.objects.create(
            employee=self.employee, document_type='other', title='Chart',
            document=SimpleUploadedFile(
                'chart.svg',
                b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
                content_type='image/svg+xml',
            ),
        )
        self.client.force_login(self.hr)
        response = self.client.get(self.url(hostile.document.name))
        self.assertIn('attachment', response['Content-Disposition'])

    def test_a_quote_in_an_uploaded_name_cannot_corrupt_the_header(self):
        """A stored name is echoed into a quoted Content-Disposition header.

        On the ordinary upload path this is already handled upstream: Django's
        ``Storage.generate_filename`` runs ``get_valid_name``, whose regex
        ``[^-\\w.]`` strips a double quote, so a file uploaded as ``quote".txt``
        is stored as ``quote.txt``. That was verified rather than assumed - an
        end-to-end test of it would pass for the wrong reason.

        The guard below is the remaining safety net for names that reach storage
        without passing through ``generate_filename``: rows written by a data
        import or a migration that assigns ``document.name`` directly, or a
        backend with different name validation. So it is tested as the unit it
        actually is.
        """
        from hrcloudpay.views import _safe_filename

        for hostile in ('quote".txt', 'a"b"c.txt', 'semi;colon.txt', 'back\\slash.txt'):
            with self.subTest(name=hostile):
                safe = _safe_filename(hostile)
                self.assertNotIn('"', safe)
                self.assertNotIn('\\', safe)
                self.assertNotIn(';', safe)

    def test_a_filename_keeps_the_characters_a_user_expects_to_see(self):
        """Over-sanitising would rename 'Ada O'Brien (2).txt' into mush."""
        from hrcloudpay.views import _safe_filename

        self.assertEqual(_safe_filename("Ada O'Brien (2).txt"), "Ada O'Brien (2).txt")

    def test_a_name_that_sanitises_to_nothing_still_yields_a_filename(self):
        """An empty disposition filename is worse than a generic one.

        A name made only of unsafe characters is not this case - it sanitises to
        underscores, which is a perfectly usable filename. This covers the name
        that sanitises to nothing at all, which is a whitespace-only name.
        """
        from hrcloudpay.views import _safe_filename

        self.assertEqual(_safe_filename('   '), 'download')
        self.assertEqual(_safe_filename(''), 'download')
        self.assertEqual(_safe_filename('"""'), '___')

    def test_private_documents_are_not_cached_in_a_browser_or_proxy(self):
        self.client.force_login(self.hr)
        response = self.client.get(self.url(self.document_name))
        self.assertIn('no-store', response['Cache-Control'])


class LogoRenderingTests(TestCase):
    """`pdf_utils` must not depend on a filesystem path.

    `FieldFile.path` raises NotImplementedError on object storage. The previous
    implementation caught that and returned None, so turning on S3 would have
    silently removed the company logo from every payslip, break form and report
    without a single error - a branding regression reported long after the
    change that caused it.
    """

    def test_a_logo_is_rendered_without_touching_path(self):
        from accounts.pdf_utils import company_logo_image

        class NoPathField:
            """Stands in for a FieldFile on a storage with no local path."""

            name = 'company_logos/2026/01/logo.png'

            @property
            def path(self):
                raise NotImplementedError('This backend has no path attribute.')

            def read(self):
                return png_bytes()

        company = Company.objects.create(name='Acme Ltd', email='logo-acme@example.com')
        flowable = company_logo_image(type('C', (), {'logo': NoPathField()})())
        self.assertIsNotNone(flowable, 'logo was dropped because .path was used')
        self.assertTrue(flowable.drawWidth > 0)

    def test_a_company_with_no_logo_renders_nothing(self):
        from accounts.pdf_utils import company_logo_image

        company = Company.objects.create(name='Bare Ltd', email='bare@example.com')
        self.assertIsNone(company_logo_image(company))

