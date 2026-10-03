"""AI must cost money, so it must be gated on the plan.

Before this, every AI endpoint checked role and company membership and nothing
else. `PLAN_PRICES` charges a flat amount per company per month, but model tokens
are billed per token, so the cheapest plan could spend unbounded money on the
platform's account: a Starter tenant could upload unlimited documents to the
provider and generate unlimited drafts for $15/month. The endpoints that cost
the most - `knowledge/upload`, which sends a file to an embedding provider, and
`drafts/`, which runs a generation - were exactly the ones with no ceiling.

What is pinned here:

  * Every one of the ten AI endpoints refuses a company on a plan below
    Professional, and none of them leaks a response body first. All ten are
    listed explicitly rather than discovered, because "the endpoints that exist"
    is exactly the thing that changed and the thing a reviewer needs to see.
  * The refusal names the company's own plan and carries the machine-readable
    fields the SPA uses to render an upgrade prompt, so a blocked customer gets
    an offer rather than a bare 403.
  * Professional, Scale and Enterprise are let through. A gate that cannot be
    shown to admit the paying tiers is not evidence of anything.
  * **The role check still wins.** Permissions are evaluated in order and the
    first failure wins, so an `employee` on Starter is refused by the role check
    before the plan check runs. Telling that user to upgrade would be wrong
    twice: they could upgrade forever and still never get the feature.
  * An inactive company and an unauthenticated caller are still refused for
    their own reasons, with their own messages, not the plan one.
  * The AI draft role gate was not loosened: Professional's `employee` still
    cannot read a draft.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.billing import AI_MINIMUM_PLAN, AI_PLANS, PLAN_LABELS
from accounts.models import Company
from accounts.permissions import CanManageAIDrafts, IsAIPlanAvailable
from accounts.platform_models import Subscription

User = get_user_model()

# (url name, args, method, needs a role the plan gate also allows)
# A GET/DELETE is used wherever the view defines one, so these tests reach the
# permission layer rather than tripping a 405 first.
ENDPOINTS = [
    ('ai-conversations', (), 'get'),
    ('ai-conversation-detail', (1,), 'get'),
    ('ai-drafts-list', (), 'get'),
    ('ai-draft-detail', (1,), 'get'),
    ('ai-knowledge', (), 'get'),
    ('ai-knowledge-search', (), 'post'),
    ('ai-knowledge-detail', (1,), 'get'),
    ('ai-knowledge-reindex', (), 'post'),
    ('ai-knowledge-upload', (), 'post'),
    ('ai-draft-create', (), 'post'),
]

# Plans below the gate: a company on one of these must be refused.
BLOCKED_PLANS = [p for p in PLAN_LABELS if p not in AI_PLANS]
# Plans that pay for AI: a company on one of these must be admitted.
ALLOWED_PLANS = [p for p in PLAN_LABELS if p in AI_PLANS]


def make_company(name, plan, is_active=True):
    """A company that clears `IsCompanyActive`, which checks two things.

    Not just `is_active`: `IsCompanyActive` also calls `subscription_state`,
    which refuses a company with no `Subscription` row at all. A fixture that
    set only the flag produced a refusal from the *third* permission in the
    list, so every test here would have been measuring the wrong gate.
    """
    company = Company.objects.create(
        name=name,
        email=f'{name}@example.com',
        plan=plan,
        is_active=is_active,
    )
    Subscription.objects.create(
        company=company,
        status='active',
        current_period_start=timezone.now(),
        renews_at=timezone.now() + timedelta(days=30),
    )
    return company


def make_user(company, username, role='hr'):
    return User.objects.create_user(
        username=username,
        password='StrongPassword123!',
        email=f'{username}@example.com',
        role=role,
        company=company,
        is_active=True,
    )


class AiPlanGateTestCase(TestCase):
    """Shared fixtures: one live company and one `hr` login per plan."""

    def setUp(self):
        self.companies = {}
        self.users = {}
        for plan in PLAN_LABELS:
            company = make_company(f'Co {plan}', plan)
            user = make_user(company, f'hr-{plan}')
            self.companies[plan] = company
            self.users[plan] = user

    def call(self, plan, url_name, args, method):
        """Make a request as the `hr` login belonging to `plan`."""
        self.client.force_login(self.users[plan])
        url = reverse(url_name, args=args)
        return getattr(self.client, method)(url)


class EveryEndpointIsGatedTests(AiPlanGateTestCase):
    """The leak was in the endpoints nobody listed, so all ten are named."""

    def test_a_starter_company_is_refused_at_every_ai_endpoint(self):
        for url_name, args, method in ENDPOINTS:
            for plan in BLOCKED_PLANS:
                with self.subTest(endpoint=url_name, plan=plan):
                    response = self.call(plan, url_name, args, method)
                    self.assertEqual(
                        response.status_code, 403,
                        f'{url_name} let a {plan} company through',
                    )
                    body = response.json()
                    self.assertEqual(body.get('code'), 'plan_upgrade_required')
                    self.assertEqual(body.get('current_plan'), plan)
                    self.assertEqual(
                        body.get('required_plan'), AI_MINIMUM_PLAN,
                    )

    def test_every_endpoint_listed_here_is_one_that_was_gated(self):
        # Guards the guard: if a new AI endpoint is added it will not appear in
        # ENDPOINTS automatically, so assert the list still matches reality.
        import ai.urls

        routed = {p.name for p in ai.urls.urlpatterns}
        self.assertEqual(
            sorted(routed), sorted(name for name, _, _ in ENDPOINTS),
            'ai/urls.py and ENDPOINTS disagree; a new AI endpoint is untested',
        )

    def test_a_company_on_a_paying_plan_is_admitted(self):
        """A gate that cannot be shown to admit paying plans proves nothing.

        The assertions are on the status *not* being the plan refusal, not on a
        2xx: these views need provider credentials, a body, or a real object id,
        and a 503 or 404 still proves the plan gate let the request through.
        """
        for url_name, args, method in ENDPOINTS:
            for plan in ALLOWED_PLANS:
                with self.subTest(endpoint=url_name, plan=plan):
                    response = self.call(plan, url_name, args, method)
                    body = response.json() if response.content else {}
                    if isinstance(body, dict) and body.get('code') == 'plan_upgrade_required':
                        self.fail(
                            f'{url_name} refused a {plan} company: {body}',
                        )
                    self.assertNotEqual(response.status_code, 403)


class RefusalPayloadTests(AiPlanGateTestCase):
    """The body has to be usable, not just present."""

    def get_body(self, plan='starter'):
        response = self.call(plan, 'ai-conversations', (), 'get')
        self.assertEqual(response.status_code, 403)
        return response.json()

    def test_the_message_names_the_plan_the_company_is_on(self):
        body = self.get_body('starter')
        self.assertIn(PLAN_LABELS['starter'], body['detail'])
        self.assertIn(PLAN_LABELS[AI_MINIMUM_PLAN], body['detail'])

    def test_the_message_does_not_claim_the_company_is_on_the_upgrade_plan(self):
        """The sentence is built from the company's plan, not the gate.

        A refusal that tells a Business customer "your company is on the
        Professional plan" is worse than no message at all: it names a plan
        they are not on. Matched on the whole "Your company is on the X plan"
        clause, because "available on the Professional plan and above" is a
        correct part of the sentence and must not trip this.
        """
        body = self.get_body('business')
        self.assertIn('Your company is on the Business plan', body['detail'])
        self.assertNotIn('Your company is on the Professional plan', body['detail'])

    def test_the_body_carries_where_to_go_next(self):
        body = self.get_body()
        self.assertEqual(body['upgrade_url'], '/billing')

    def test_a_custom_price_enterprise_card_is_not_offered_an_upgrade(self):
        """Nothing above the gate is ever told to upgrade.

        `ai_refusal_body` is reachable for a company that passes the gate if a
        future view forgets to list the permission, so pin that the helper
        reports no upgrade target rather than a plan for an allowed company.
        """
        from accounts.billing import ai_upgrade_target

        self.assertIsNone(ai_upgrade_target(self.companies['professional']))
        self.assertIsNone(ai_upgrade_target(self.companies['scale']))
        self.assertIsNone(ai_upgrade_target(self.companies['enterprise']))
        self.assertEqual(
            ai_upgrade_target(self.companies['starter']), AI_MINIMUM_PLAN,
        )


class RoleStillWinsOverPlanTests(AiPlanGateTestCase):
    """A user who could never have the feature must not be told to buy it."""

    def test_a_starter_employee_is_told_the_role_reason_not_the_plan_one(self):
        user = make_user(self.companies['starter'], 'starter-employee', role='employee')
        self.client.force_login(user)
        response = self.client.get(reverse('ai-drafts-list'))
        self.assertEqual(response.status_code, 403)
        body = response.json()
        self.assertNotEqual(body.get('code'), 'plan_upgrade_required')
        self.assertEqual(body.get('detail'), CanManageAIDrafts.message)

    def test_a_professional_employee_still_cannot_read_a_draft(self):
        """Raising the plan must not have loosened the role gate.

        The draft list returns each draft's full `content` and `context`, which
        name identifiable employees. This is the assertion that would fail if
        someone "simplified" the permission list while adding the plan gate.
        """
        user = make_user(self.companies['professional'], 'pro-employee', role='employee')
        self.client.force_login(user)
        response = self.client.get(reverse('ai-drafts-list'))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['detail'], CanManageAIDrafts.message)


class OtherRefusalsAreUnchangedTests(AiPlanGateTestCase):
    """Adding a permission must not swallow the existing refusals."""

    def test_an_unauthenticated_caller_is_still_refused(self):
        response = self.client.get(reverse('ai-conversations'))
        self.assertEqual(response.status_code, 403)

    def test_an_inactive_company_still_gets_the_activation_message(self):
        company = make_company('Co dormant', 'professional', is_active=False)
        user = make_user(company, 'hr-dormant')
        self.client.force_login(user)
        response = self.client.get(reverse('ai-conversations'))
        self.assertEqual(response.status_code, 403)
        body = response.json()
        self.assertNotEqual(body.get('code'), 'plan_upgrade_required')
        self.assertIn('not yet activated', body['detail'])

    def test_a_platform_admin_with_no_company_is_still_refused(self):
        """Platform staff have no subscription, so `IsCompanyMember` refuses.

        They configure the platform-wide AI provider from a different endpoint,
        which is not gated; this only pins that this mixin does not turn their
        403 into an upgrade prompt.
        """
        from accounts.permissions import AIPlanGateMixin

        admin = User.objects.create_user(
            username='platformadmin', password='StrongPassword123!',
            email='platform@example.com', role='owner',
            is_staff=True, is_superuser=True,
        )
        self.client.force_login(admin)
        response = self.client.get(reverse('ai-conversations'))
        self.assertEqual(response.status_code, 403)
        self.assertNotEqual(
            (response.json() if response.content else {}).get('code'),
            'plan_upgrade_required',
        )
        self.assertTrue(issubclass(
            __import__('ai.views', fromlist=['AIConversationsView']).AIConversationsView,
            AIPlanGateMixin,
        ))


class GatePlacementTests(TestCase):
    """Structural checks on the permission lists themselves.

    Ordering is the whole mechanism: DRF stops at the first failure, so putting
    `IsAIPlanAvailable` before a role check changes which message a user sees.
    A test that only exercised the HTTP surface would not catch someone
    reordering the list and breaking that.
    """

    def test_the_plan_gate_is_last_on_every_ai_view(self):
        import ai.knowledge_views
        import ai.views

        gated = 0
        for module in (ai.views, ai.knowledge_views):
            for name in dir(module):
                view = getattr(module, name)
                if not isinstance(view, type):
                    continue
                perms = getattr(view, 'permission_classes', None)
                if not perms or not any(
                    getattr(p, '__name__', '') == 'IsAIPlanAvailable' for p in perms
                ):
                    continue
                gated += 1
                self.assertEqual(
                    perms[-1].__name__, 'IsAIPlanAvailable',
                    f'{name} does not end with the plan gate: '
                    f'{[p.__name__ for p in perms]}',
                )
        self.assertEqual(gated, len(ENDPOINTS), 'a gated view was not found')

    def test_the_gate_passes_when_there_is_no_company_to_check(self):
        """The permission must defer to the permissions listed before it.

        Answering "who are you" here would replace `IsCompanyMember`'s message
        with the plan one, which is how a deactivated-company user would start
        being told to upgrade.
        """
        from rest_framework.test import APIRequestFactory

        # `is_authenticated` is a read-only property that follows `is_active`,
        # so an unsaved user with the flag set is the cheapest faithful stand-in
        # for a signed-in user that belongs to no company.
        request = APIRequestFactory().get('/')
        request.user = User(username='nobody', is_active=True)
        request.user.company_id = None
        request.user.company = None
        self.assertTrue(IsAIPlanAvailable().has_permission(request, None))
