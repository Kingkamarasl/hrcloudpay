"""Editing a plan from the platform admin.

The Plans tab has been inert since it was written, and it took three
independent faults stacked on top of each other:

  1. The edit form held its draft in the PARENT, via an `onEdit` callback. The
     parent's `planEdit` state was assigned and passed down and never read, so
     the inputs stayed bound to the object from the last GET - controlled inputs
     whose value could not change. Typing did nothing.
  2. Save posted that same original object rather than the edit, so even a
     working keystroke would have saved nothing.
  3. The endpoint read `request.data['plan']`, while its own GET serialised the
     model's `plan` column as `id`. Posting back the object the endpoint had just
     returned failed with 400 "plan is required" - so the tab could not have
     saved anything even with the first two fixed.

Fault 3 is the one worth guarding here: it is a contract mismatch between a GET
and a PUT on the same endpoint, which no amount of clicking reveals. The tests
below round-trip the real GET response back through the PUT.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Company, User
from accounts.platform_models import BillingPlan

ENDPOINT = '/api/auth/platform/billing-plans/'


class BillingPlanAdminTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Northwind Logistics', email='owner@northwind.example',
            is_active=True, plan='starter',
        )
        self.root = User.objects.create_superuser(
            username='root', email='root@example.com',
            password='Str0ngPass-2026!', company=None,
        )
        self.staff = User.objects.create_user(
            username='staffer', email='staffer@northwind.example',
            password='Str0ngPass-2026!', company=self.company, is_staff=True,
            role='employee',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.root)
        # A data migration seeds the five plans, so this adjusts the row that is
        # already there rather than creating a second 'starter' - which the
        # unique constraint on `plan` correctly refuses.
        self.plan, _ = BillingPlan.objects.update_or_create(
            plan='starter',
            defaults=dict(
                name='Starter', monthly_price='49.00', annual_price='490.00',
                employee_limit=10, user_limit=3, ai_enabled=False,
                highlight=False, active=True, order=1,
            ),
        )

    def get(self):
        return self.client.get(ENDPOINT)

    # --- the GET/PUT contract -------------------------------------------------

    def test_get_keys_each_plan_by_id(self):
        """`id` is the shape the rest of the API already uses.

        BillingPlansView, the public endpoint, also serialises as `id`. The PUT
        reading only `plan` was the outlier, and it is why the round trip broke.
        """
        body = self.get().json()
        self.assertIn('starter', [p['id'] for p in body])
        self.assertNotIn('plan', body[0],
                         'the GET must not also ship a second key for the same row')

    def test_posting_back_the_get_response_is_accepted(self):
        """The exact failure: GET then PUT, unchanged.

        Previously this returned 400 "plan is required", because the payload
        carried `id` and the view read `plan`.
        """
        payload = dict(self.get().json()[0])
        response = self.client.put(ENDPOINT, payload, format='json')

        self.assertEqual(response.status_code, 200, response.data)

    def test_put_accepts_the_plan_key_too(self):
        response = self.client.put(
            ENDPOINT, {'plan': 'starter', 'name': 'Starter Plus'}, format='json')

        self.assertEqual(response.status_code, 200, response.data)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.name, 'Starter Plus')

    def test_put_with_neither_key_is_rejected(self):
        response = self.client.put(ENDPOINT, {'name': 'x'}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(BillingPlan.objects.get(plan='starter').name, 'Starter')

    def test_put_on_an_unknown_plan_is_404(self):
        response = self.client.put(
            ENDPOINT, {'id': 'platinum', 'name': 'x'}, format='json')

        self.assertEqual(response.status_code, 404)

    # --- the edits actually land ----------------------------------------------

    def test_price_and_limits_persist(self):
        response = self.client.put(ENDPOINT, {
            'id': 'starter', 'monthly_price': '79.00', 'annual_price': '790.00',
            'employee_limit': 25, 'user_limit': 8,
        }, format='json')

        self.assertEqual(response.status_code, 200, response.data)
        self.plan.refresh_from_db()
        self.assertEqual(str(self.plan.monthly_price), '79.00')
        self.assertEqual(self.plan.employee_limit, 25)
        self.assertEqual(self.plan.user_limit, 8)

    def test_unlimited_employee_limit_is_accepted(self):
        """A blank limit is how the UI spells "Unlimited", and it must persist
        as NULL rather than 0. A 0 here would block every employee from being
        added to a company on that plan."""
        self.client.put(ENDPOINT,
                        {'id': 'starter', 'employee_limit': None}, format='json')

        self.plan.refresh_from_db()
        self.assertIsNone(self.plan.employee_limit)

    def test_flags_persist(self):
        self.client.put(ENDPOINT, {
            'id': 'starter', 'ai_enabled': True, 'highlight': True, 'order': 7,
        }, format='json')

        self.plan.refresh_from_db()
        self.assertTrue(self.plan.ai_enabled)
        self.assertTrue(self.plan.highlight)
        self.assertEqual(self.plan.order, 7)

    def test_response_echoes_the_saved_values(self):
        """The UI updates from this payload, so a stale echo would leave the
        card showing the old price until the next reload."""
        response = self.client.put(
            ENDPOINT, {'id': 'starter', 'monthly_price': '64.00'}, format='json')

        self.assertEqual(response.json()['plan']['monthly_price'], '64.00')

    # --- permissions ----------------------------------------------------------

    def test_a_non_staff_user_cannot_read_or_write_plans(self):
        """These are the prices every subscriber pays."""
        member = User.objects.create_user(
            username='member', email='member@northwind.example',
            password='Str0ngPass-2026!', company=self.company, role='employee',
        )
        self.client.force_authenticate(member)

        self.assertEqual(self.client.get(ENDPOINT).status_code, 403)
        self.assertEqual(
            self.client.put(ENDPOINT, {'id': 'starter', 'name': 'free'},
                            format='json').status_code, 403)

    def test_anonymous_cannot_read_plans(self):
        # 401 or 403 depending on whether the project runs SessionAuthentication
        # first; what matters is that it is refused, not which refusal.
        self.assertIn(APIClient().get(ENDPOINT).status_code, (401, 403))


class PlanEditFormTests(TestCase):
    """The form half of the bug - no backend change would have made it work."""

    def setUp(self):
        import pathlib
        self.source = (
            pathlib.Path(__file__).resolve().parents[2]
            / 'frontend' / 'src' / 'pages' / 'PlatformAdmin.jsx'
        ).read_text(encoding='utf-8')
        # Scope the checks to the Plans component. PlatformAdmin.jsx also
        # contains the Users tab, which legitimately has an `onEdit` prop for
        # opening the user editor; asserting over the whole file made this test
        # fail when that unrelated feature landed.
        start = self.source.index('function Plans(')
        end = self.source.index('export default function PlatformAdmin')
        self.plans_source = self.source[start:end]

    def test_the_draft_is_held_where_the_inputs_read_it(self):
        """`onEdit` pushed the edit to a parent that never read it, leaving the
        inputs bound to the loaded object and therefore untypable."""
        # Line comments first: the component's own header explains why onEdit
        # was wrong, and that explanation must not trip its own check.
        rendered = '\n'.join(l for l in self.plans_source.splitlines()
                             if not l.strip().startswith('//'))
        self.assertNotIn('onEdit', rendered)
        self.assertNotIn('planEdit', rendered)
        self.assertIn('setDraft({...p})', rendered)

    def test_save_posts_the_draft_not_the_loaded_plan(self):
        self.assertIn('onSave({...d,plan:d.id})', self.plans_source)