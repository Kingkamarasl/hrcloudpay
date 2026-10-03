"""Tests for the site's favicon and iOS home-screen icon.

The security-relevant property under test is not "can a file be uploaded" but
"what exactly reaches the browser". These two routes are unauthenticated by
necessity - a browser asks for a favicon before the visitor has a session - and
that is only safe because of two specific defences, both asserted here:

1. the bytes served are re-encoded by this module rather than streamed from
   storage, so a polyglot file cannot survive and EXIF/ICC never reaches a
   visitor; and
2. SVG is refused, because it is a document format that can carry <script> and
   it would execute in the app's own origin for every visitor.
"""
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Company, User
from accounts.platform_models import SiteBranding
from hrcloudpay.site_icons import (
    APPLE_TOUCH_ICON_SIZE, FAVICON_MAX_EDGE, MAX_UPLOAD_BYTES, SiteIconError,
    normalise_site_icon,
)


def png_bytes(size, colour=(11, 92, 63, 255)):
    from PIL import Image

    image = Image.new('RGBA', size, colour)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def upload(name='icon.png', size=(64, 64), image_format='PNG', content_type='image/png'):
    from PIL import Image

    image = Image.new('RGBA', size, (11, 92, 63, 255))
    if image_format == 'JPEG':
        # JPEG has no alpha channel, so this would raise on save.
        image = image.convert('RGB')
    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


def store_icon(field='favicon', name='icon.png', size=(64, 64)):
    """Put an icon on the singleton the way a request would.

    Uses FieldFile.save() explicitly rather than assigning to the attribute.
    An uncommitted file assigned directly is easy to get subtly wrong, and the
    resulting 204 would look like a bug in the serving route rather than in the
    test's own setup.
    """
    from django.core.files.base import ContentFile

    branding = SiteBranding.get_solo()
    getattr(branding, field).save(
        name, ContentFile(upload(size=size).read()), save=False
    )
    branding.save()
    return branding


class NormaliseSiteIconTests(TestCase):
    """Unit tests for the re-encoding, which is where the safety lives."""

    def test_rejects_svg_because_it_can_carry_script(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'

        with self.assertRaises(SiteIconError) as caught:
            normalise_site_icon(svg)

        self.assertIn('SVG', str(caught.exception))
        self.assertIn('script', str(caught.exception).lower())

    def test_rejects_a_file_that_is_not_an_image(self):
        with self.assertRaises(SiteIconError) as caught:
            normalise_site_icon(b'<html><body>not an image</body></html>')

        self.assertIn('not a recognised image', str(caught.exception))

    def test_rejects_an_empty_file(self):
        with self.assertRaises(SiteIconError):
            normalise_site_icon(b'')

    def test_rejects_a_file_over_the_size_cap(self):
        with self.assertRaises(SiteIconError) as caught:
            normalise_site_icon(b'\x89PNG\r\n\x1a\n' + b'0' * (MAX_UPLOAD_BYTES + 1))

        self.assertIn('limit', str(caught.exception).lower())

    def test_a_large_favicon_is_scaled_down(self):
        out = normalise_site_icon(png_bytes((1200, 900)))

        from PIL import Image
        with Image.open(io.BytesIO(out)) as image:
            self.assertEqual(image.format, 'PNG')
            self.assertLessEqual(image.width, FAVICON_MAX_EDGE)
            self.assertLessEqual(image.height, FAVICON_MAX_EDGE)

    def test_apple_touch_icon_is_always_exactly_180_square(self):
        from PIL import Image
        with Image.open(io.BytesIO(normalise_site_icon(
                png_bytes((64, 64)), apple_touch=True))) as image:
            self.assertEqual(image.size, (APPLE_TOUCH_ICON_SIZE, APPLE_TOUCH_ICON_SIZE))

    def test_a_wide_apple_touch_icon_is_padded_not_stretched(self):
        """A 4:1 letterhead logo must not be squashed to a square. iOS applies
        its own rounded mask, so padding is the only honest option."""
        from PIL import Image
        with Image.open(io.BytesIO(normalise_site_icon(
                png_bytes((400, 100)), apple_touch=True))) as image:
            self.assertEqual(image.size, (180, 180))
            # If it had been stretched, the whole canvas would be opaque green.
            # Padding leaves transparent bands top and bottom.
            self.assertEqual(image.getpixel((90, 2))[3], 0)

    def test_transparency_is_preserved(self):
        """Flattening RGBA to RGB turns a transparent PNG black in some
        viewers, so the alpha channel has to survive."""
        from PIL import Image
        transparent = Image.new('RGBA', (32, 32), (255, 0, 0, 0))
        buffer = io.BytesIO()
        transparent.save(buffer, format='PNG')

        out = normalise_site_icon(buffer.getvalue())
        with Image.open(io.BytesIO(out)) as image:
            self.assertEqual(image.mode, 'RGBA')
            self.assertEqual(image.getpixel((16, 16))[3], 0)

    def test_output_is_a_png_even_when_the_input_was_jpeg(self):
        out = normalise_site_icon(
            upload(size=(48, 48), image_format='JPEG', content_type='image/jpeg').read()
        )

        from PIL import Image
        with Image.open(io.BytesIO(out)) as image:
            self.assertEqual(image.format, 'PNG')

    def test_normalising_twice_is_stable(self):
        """The stored file is already normalised, and normalising again happens
        on every serve. If it were not idempotent, the served bytes would drift
        each request until the icon degraded."""
        once = normalise_site_icon(png_bytes((300, 200)), apple_touch=True)
        twice = normalise_site_icon(once, apple_touch=True)

        self.assertEqual(once, twice)


class SiteIconRoutesTests(TestCase):
    def setUp(self):
        self.url = reverse('site-favicon')
        self.apple_url = reverse('site-apple-touch-icon')

    def test_returns_204_rather_than_404_when_no_icon_is_uploaded(self):
        """A missing icon is the normal state before the first upload. A 404 on
        every page load is log noise; 204 says 'nothing here' quietly."""
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 204)

    def test_is_reachable_without_authenticating(self):
        """The whole reason this route exists. If it ever starts requiring a
        session the icon silently stops loading for the entire public audience,
        and no test in this file would otherwise catch it."""
        self.assertNotIn('_auth_user_id', self.client.session)

        store_icon()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')

    def test_serves_the_uploaded_icon_as_png(self):
        store_icon()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertTrue(response['ETag'])

    def test_served_bytes_are_re_encoded_not_the_stored_file(self):
        """The whole defence against a polyglot is that the bytes served are the
        bytes this module produced, rather than whatever happens to be on disk.

        Asserted directly by storing a valid PNG with a script payload appended
        after the image data. Pillow reads the image and ignores the tail, so a
        route that streamed the stored file would hand the payload to every
        visitor. PNG decoders stop at IEND, so appending is enough to build the
        file and the payload must not survive a round trip through normalise.
        """
        from django.core.files.base import ContentFile

        payload = b'<script>alert(document.cookie)</script>'
        original = png_bytes((32, 32))
        branding = SiteBranding.get_solo()
        branding.favicon.save('poly.png', ContentFile(original + payload), save=False)
        branding.save()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(payload, response.content)
        self.assertEqual(response.content, normalise_site_icon(original))

    def test_a_polyglot_stored_on_disk_cannot_reach_a_visitor(self):
        """As above but for a JPEG, whose container also tolerates trailing
        bytes. Separate from the PNG case so neither format can regress alone."""
        from django.core.files.base import ContentFile

        payload = b'/*</script><script>alert(1)</script>*/'
        original = upload(size=(32, 32), image_format='JPEG',
                          content_type='image/jpeg').read()
        branding = SiteBranding.get_solo()
        branding.favicon.save('poly.jpg', ContentFile(original + payload), save=False)
        branding.save()

        response = self.client.get(self.url)

        self.assertNotIn(b'<script>', response.content)
        self.assertNotIn(b'</script>', response.content)

    def test_revalidates_rather_than_caching_hard(self):
        store_icon()

        response = self.client.get(self.url)

        self.assertEqual(response['Cache-Control'], 'no-cache')

    def test_an_unchanged_icon_revalidates_to_304(self):
        store_icon()

        first = self.client.get(self.url)
        second = self.client.get(self.url, HTTP_IF_NONE_MATCH=first['ETag'])

        self.assertEqual(second.status_code, 304)
        self.assertEqual(second.content, b'')

    def test_changing_the_icon_invalidates_the_etag(self):
        store_icon()
        first = self.client.get(self.url)

        store_icon(name='other.png', size=(96, 96))
        second = self.client.get(self.url, HTTP_IF_NONE_MATCH=first['ETag'])

        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(second['ETag'], first['ETag'])

    def test_a_file_named_in_the_database_but_absent_from_storage_serves_204(self):
        """A real state after a partial restore: the row names an object the
        bucket does not have. It must degrade to 'no icon', not to a 500."""
        SiteBranding.objects.create(favicon='site_icons/vanished.png')

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 204)

    def test_a_stored_file_that_is_no_longer_a_valid_image_serves_204(self):
        branding = SiteBranding.get_solo()
        branding.favicon = 'site_icons/not-an-image.png'
        branding.save()
        # Write junk over the stored object, bypassing the upload validation.
        from django.core.files.storage import default_storage
        default_storage.save('site_icons/not-an-image.png',
                             io.BytesIO(b'this is not an image'))

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 204)

    def test_the_routes_sit_above_the_spa_catch_all(self):
        """Otherwise the catch-all returns index.html with a 200 and the browser
        receives HTML where it asked for a PNG."""
        from django.urls import resolve

        match = resolve('/site-icon/favicon.png')

        self.assertEqual(match.func.__name__, 'serve_favicon')
        self.assertEqual(resolve('/site-icon/apple-touch-icon.png').func.__name__,
                         'serve_apple_touch_icon')


class SiteBrandingAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='platformadmin', password='StrongPassword123!',
            email='platform@example.com', role='owner',
            is_staff=True, is_superuser=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.url = reverse('platform-site-branding')

    def test_requires_a_platform_admin(self):
        self.client.force_authenticate(
            User.objects.create_user(username='tenant', password='StrongPassword123!',
                                     email='t@example.com', role='owner')
        )
        self.assertEqual(self.client.get(self.url).status_code, 403)

        # 403 rather than 401: no authenticator in this stack supplies a
        # WWW-Authenticate header, so DRF answers 403 for anonymous access.
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_reports_the_current_state(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['has_favicon'])
        self.assertFalse(response.data['has_apple_touch_icon'])
        self.assertTrue(response.data['favicon_url'].endswith('/site-icon/favicon.png'))

    def test_upload_becomes_served_immediately(self):
        response = self.client.post(self.url, {'favicon': upload()}, format='multipart')

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['has_favicon'])
        self.assertEqual(self.client.get(reverse('site-favicon')).status_code, 200)

    def test_uploading_an_svg_is_refused(self):
        svg = SimpleUploadedFile(
            'icon.svg', b'<svg xmlns="http://www.w3.org/2000/svg"><script>x()</script></svg>',
            content_type='image/svg+xml',
        )

        response = self.client.post(self.url, {'favicon': svg}, format='multipart')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['field'], 'favicon')
        self.assertFalse(self.client.get(self.url).data['has_favicon'])

    def test_a_bad_second_file_leaves_the_first_upload_intact(self):
        self.client.post(self.url, {'favicon': upload()}, format='multipart')

        response = self.client.post(
            self.url,
            {
                'favicon': upload(),
                'apple_touch_icon': SimpleUploadedFile(
                    'bad.png', b'not an image', content_type='image/png',
                ),
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            self.client.get(self.url).data['has_favicon'], True,
            'a rejected second file must not leave the first one half-applied',
        )

    def test_posting_no_file_is_refused(self):
        response = self.client.post(self.url, {}, format='multipart')

        self.assertEqual(response.status_code, 400)
        self.assertIn('No file', response.data['detail'])

    def test_replacing_an_icon_deletes_the_previous_object(self):
        """Otherwise every re-upload leaves an orphan in the bucket, invisible
        until somebody reads a storage bill."""
        from django.core.files.storage import default_storage

        self.client.post(self.url, {'favicon': upload(name='first.png')}, format='multipart')
        first_name = SiteBranding.objects.get().favicon.name
        self.assertTrue(default_storage.exists(first_name))

        self.client.post(self.url, {'favicon': upload(name='second.png')}, format='multipart')

        self.assertFalse(
            default_storage.exists(first_name),
            'the superseded icon should not be left behind in storage',
        )

    def test_upload_records_who_changed_it(self):
        self.client.post(self.url, {'favicon': upload()}, format='multipart')

        self.assertEqual(SiteBranding.objects.get().updated_by, self.admin)

    def test_delete_clears_one_icon(self):
        self.client.post(
            self.url,
            {'favicon': upload(), 'apple_touch_icon': upload(name='apple.png')},
            format='multipart',
        )

        response = self.client.delete(self.url, {'field': 'favicon'})

        self.assertEqual(response.status_code, 200)
        state = response.data
        self.assertFalse(state['has_favicon'])
        self.assertTrue(state['has_apple_touch_icon'])

    def test_deleting_something_that_is_not_there_is_refused(self):
        response = self.client.delete(self.url, {'field': 'favicon'})

        self.assertEqual(response.status_code, 400)

    def test_delete_rejects_an_unknown_field(self):
        response = self.client.delete(self.url, {'field': 'logo'})

        self.assertEqual(response.status_code, 400)

    def test_upload_and_removal_are_audited(self):
        from accounts.platform_models import AuditLog

        self.client.post(self.url, {'favicon': upload()}, format='multipart')
        self.client.delete(self.url, {'field': 'favicon'})

        self.assertTrue(AuditLog.objects.filter(action='update', actor=self.admin).exists())
        self.assertTrue(AuditLog.objects.filter(action='delete', actor=self.admin).exists())