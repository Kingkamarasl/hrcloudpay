"""Platform admins must be able to create and delete marketing pages.

Today the content system can only edit a page that already exists: the list
view defines `get` and nothing else, and the detail view defines `patch`. So
"add a page" is impossible - the only way to get a new slug into the database is
a shell or a migration, which is not a management capability.

Two things are pinned here beyond the obvious create/delete:

  * **Validation on write.** `patch` used to accept any dict as page content. It
    now runs the schema, so an unknown section type is refused instead of being
    stored and breaking a public page on the next visitor's load.
  * **The root page is protected.** Deleting `home` would silently strip the
    marketing layer off the homepage. It is refused with a message rather than
    allowed and regretted.

Every write asserts an audit record, because a platform admin changing what the
public site says is exactly the kind of action that has to be attributable.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.platform_models import AuditLog, MarketingPage

User = get_user_model()

LIST = 'platform-marketing-pages'
DETAIL = 'platform-marketing-page-detail'
PUBLIC = 'public-marketing-page'

# These tests need a page slug that does *not* already exist, so that "create"
# means create. They originally used `platform`, which worked only while the
# seed migration created just `home` and `security`. Migration 0018 seeds all
# seven public routes, so `platform` now exists in every test database and
# every create assertion here was silently a duplicate-slug rejection instead.
#
# `new-landing-page` is deliberately unlike a real route: if it ever collides
# with a seeded page the failure points at this line, not at a mystery 400.
SLUG = 'new-landing-page'
NAME = 'New landing page'


class MarketingPageApiTestCase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='platformadmin',
            password='StrongPassword123!',
            email='platform@example.com',
            role='owner',
            is_staff=True,
            is_superuser=True,
        )
        self.tenant_admin = User.objects.create_user(
            username='tenantboss',
            password='StrongPassword123!',
            email='tenant@example.com',
            role='owner',
            is_staff=False,
            is_superuser=False,
        )
        # APIClient, not Django's Client: it parses a JSON request body and
        # supports force_authenticate, both of which these tests need.
        self.client = APIClient()
        self.list_url = reverse(LIST)
        self.detail_url = reverse(DETAIL, args=[SLUG])
        # Every test in the base class acts as the platform admin unless it
        # deliberately re-authenticates as somebody else.
        self.client.force_authenticate(self.admin)

    def detail(self, slug):
        return reverse(DETAIL, args=[slug])


class CreatePageTests(MarketingPageApiTestCase):
    def test_an_admin_can_create_a_page(self):
        response = self.client.post(
            self.list_url,
            {'slug': SLUG, 'name': NAME},
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['slug'], SLUG)
        self.assertTrue(MarketingPage.objects.filter(slug=SLUG).exists())

    def test_a_new_page_starts_with_a_hero(self):
        """An empty page would render as a blank landing page."""
        self.client.post(self.list_url, {'slug': SLUG, 'name': NAME},
                         format='json')
        page = MarketingPage.objects.get(slug=SLUG)
        self.assertEqual(page.content['sections'][0]['type'], 'hero')

    def test_creating_a_page_is_audited(self):
        self.client.post(self.list_url, {'slug': SLUG, 'name': NAME},
                         format='json')
        self.assertTrue(
            AuditLog.objects.filter(
                action='create', target_type='marketing_page', target_id=SLUG
            ).exists(),
            'creating a public page left no audit record',
        )

    def test_a_bad_slug_is_refused_with_a_readable_message(self):
        for slug in ('Platform', 'has space', '-leading', 'under_score', '', 'x' * 100):
            with self.subTest(slug=slug):
                response = self.client.post(
                    self.list_url, {'slug': slug, 'name': 'Bad'}, format='json')
                self.assertEqual(response.status_code, 400)
                self.assertIn('slug', response.data)
                self.assertFalse(MarketingPage.objects.filter(slug=slug).exists())

    def test_a_duplicate_slug_is_refused(self):
        MarketingPage.objects.create(slug=SLUG, name=NAME)
        response = self.client.post(
            self.list_url, {'slug': SLUG, 'name': 'Again'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('slug', response.data)
        self.assertEqual(MarketingPage.objects.filter(slug=SLUG).count(), 1)

    def test_a_missing_name_is_refused(self):
        response = self.client.post(self.list_url, {'slug': SLUG},
                                    format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('name', response.data)

    def test_content_can_be_supplied_at_creation_and_is_validated(self):
        response = self.client.post(
            self.list_url,
            {
                'slug': SLUG,
                'name': NAME,
                'content': {'sections': [{'type': 'hero', 'title': 'One system.'}]},
            },
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.data)
        page = MarketingPage.objects.get(slug=SLUG)
        self.assertEqual(page.content['sections'][0]['title'], 'One system.')

    def test_invalid_content_is_refused_at_creation(self):
        response = self.client.post(
            self.list_url,
            {'slug': SLUG, 'name': NAME,
             'content': {'sections': [{'type': 'marquee'}]}},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('content', response.data)
        self.assertFalse(MarketingPage.objects.filter(slug=SLUG).exists())

    def test_a_dangerous_link_is_refused_at_creation(self):
        response = self.client.post(
            self.list_url,
            {'slug': SLUG, 'name': NAME,
             'content': {'sections': [
                 {'type': 'cta', 'actions': [{'label': 'Go',
                                              'href': 'javascript:alert(1)'}]}]}},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(MarketingPage.objects.filter(slug=SLUG).exists())

    def test_a_non_admin_cannot_create_a_page(self):
        """This rewrites what every visitor sees on the public site."""
        self.client.force_authenticate(self.tenant_admin)
        response = self.client.post(self.list_url,
                                    {'slug': 'sneaky', 'name': 'Sneaky'}, format='json')
        self.assertIn(response.status_code, (401, 403))
        self.assertFalse(MarketingPage.objects.filter(slug='sneaky').exists())

    def test_an_anonymous_visitor_cannot_create_a_page(self):
        self.client.logout()
        response = self.client.post(self.list_url,
                                    {'slug': 'sneaky', 'name': 'Sneaky'}, format='json')
        self.assertIn(response.status_code, (401, 403))
        self.assertFalse(MarketingPage.objects.filter(slug='sneaky').exists())


class UpdatePageTests(MarketingPageApiTestCase):
    def setUp(self):
        super().setUp()
        self.page = MarketingPage.objects.create(slug=SLUG, name=NAME)

    def test_patch_now_refuses_an_unknown_section_type(self):
        """It used to store any dict, which broke the public renderer."""
        response = self.client.patch(
            self.detail_url, {'content': {'sections': [{'type': 'marquee'}]}},
            format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.page.refresh_from_db()
        self.assertEqual(self.page.draft_content, None)

    def test_patch_refuses_a_dangerous_link(self):
        response = self.client.patch(
            self.detail_url,
            {'content': {'sections': [
                {'type': 'hero', 'primary_cta': 'Go',
                 'primary_href': 'javascript:alert(1)'}]}},
            format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.page.refresh_from_db()
        self.assertIsNone(self.page.draft_content)

    def test_a_valid_draft_is_saved_and_promoted_on_publish(self):
        save = self.client.patch(
            self.detail_url,
            {'action': 'save_draft',
             'content': {'sections': [{'type': 'hero', 'title': 'Draft title'}]},
             'name': NAME},
            format='json')
        self.assertEqual(save.status_code, 200, save.data)
        self.assertTrue(save.data['has_draft'])
        # The draft must not be visible publicly before publishing.
        public = self.client.get(reverse(PUBLIC, args=[SLUG]))
        self.assertNotIn('Draft title', str(public.data))

        publish = self.client.patch(self.detail_url, {'action': 'publish'},
                                    format='json')
        self.assertEqual(publish.status_code, 200, publish.data)
        self.assertEqual(publish.data['content']['sections'][0]['title'],
                         'Draft title')
        self.assertFalse(publish.data['has_draft'])

        public = self.client.get(reverse(PUBLIC, args=[SLUG]))
        self.assertIn('Draft title', str(public.data))

    def test_publishing_records_who_did_it(self):
        self.client.patch(
            self.detail_url,
            {'action': 'save_draft',
             'content': {'sections': [{'type': 'hero', 'title': 'T'}]}},
            format='json')
        response = self.client.patch(self.detail_url, {'action': 'publish'},
                                     format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['updated_by'], 'platformadmin')

    def test_a_non_admin_cannot_edit_a_page(self):
        self.client.force_authenticate(self.tenant_admin)
        response = self.client.patch(
            self.detail_url,
            {'content': {'sections': [{'type': 'hero', 'title': 'Hijacked'}]}},
            format='json')
        self.assertIn(response.status_code, (401, 403))


class DeletePageTests(MarketingPageApiTestCase):
    def setUp(self):
        super().setUp()
        self.page = MarketingPage.objects.create(slug=SLUG, name=NAME)

    def test_an_admin_can_delete_a_page(self):
        response = self.client.delete(self.detail(SLUG))
        self.assertIn(response.status_code, (200, 204))
        self.assertFalse(MarketingPage.objects.filter(slug=SLUG).exists())

    def test_deleting_a_page_is_audited(self):
        self.client.delete(self.detail(SLUG))
        self.assertTrue(
            AuditLog.objects.filter(
                action='delete', target_type='marketing_page', target_id=SLUG
            ).exists(),
            'deleting a public page left no audit record',
        )

    def test_the_root_page_cannot_be_deleted(self):
        """Deleting `home` would strip the marketing layer off the homepage."""
        # A data migration already seeds `home`, so this is not a fresh create.
        MarketingPage.objects.get_or_create(
            slug='home', defaults={'name': 'Homepage'})
        response = self.client.delete(self.detail('home'))
        self.assertEqual(response.status_code, 400)
        self.assertTrue(MarketingPage.objects.filter(slug='home').exists())

    def test_deleting_an_unknown_page_is_a_404(self):
        response = self.client.delete(self.detail('does-not-exist'))
        self.assertEqual(response.status_code, 404)

    def test_a_non_admin_cannot_delete_a_page(self):
        self.client.force_authenticate(self.tenant_admin)
        response = self.client.delete(self.detail(SLUG))
        self.assertIn(response.status_code, (401, 403))
        self.assertTrue(MarketingPage.objects.filter(slug=SLUG).exists())


class PublicPageTests(MarketingPageApiTestCase):
    def test_an_unpublished_page_is_not_publicly_readable(self):
        MarketingPage.objects.create(slug='secret', name='Secret',
                                     is_published=False)
        response = self.client.get(reverse(PUBLIC, args=['secret']))
        self.assertEqual(response.status_code, 404)

    def test_the_public_endpoint_never_returns_draft_content(self):
        """A draft in the public payload would leak unreleased copy."""
        MarketingPage.objects.create(
            slug=SLUG, name=NAME,
            content={'sections': [{'type': 'hero', 'title': 'Live'}]},
            draft_content={'sections': [{'type': 'hero', 'title': 'Unreleased'}]},
            draft_name='Unreleased name',
        )
        payload = str(self.client.get(reverse(PUBLIC, args=[SLUG])).data)
        self.assertIn('Live', payload)
        self.assertNotIn('Unreleased', payload)