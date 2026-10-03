"""The advertised price must be the price that gets charged.

The public pricing page stored its own copy of every number: `$15`, "Up to 10
employees, 3 team accounts". `PLAN_PRICES` and `PLAN_USER_LIMITS` charged a
different set, and nothing read the marketing copy back. So the two drifted
silently and the site advertised a plan it would then refuse to sell - which is
the failure mode that ends up in a screenshot on a pricing page.

The fix makes `PLAN_PRICES` the only place a price exists. The public API
overwrites the numbers in the stored pricing section from the billing tables on
the way out, so an admin can still write the prose but cannot write a price. What
is pinned here:

  * Every plan's advertised price equals `PLAN_PRICES`, including the new `scale`
    tier that no marketing copy mentioned at all.
  * The advertised employee and user counts equal the enforced limits, so the
    page cannot promise a company 10 employees while the API refuses the 11th.
  * **The stored copy is deliberately left alone.** The page must still render
    when billing has drifted from the stored copy, which is the whole point; this
    asserts the stored row is *not* rewritten, because an admin's next save
    should not silently revert a price they never changed.
  * Prose the admin owns survives. Blurbs and feature lists are not numbers and
    must not be overwritten by a billing change.
  * A plan whose price is 0 (Enterprise, sold by agreement) is advertised as
    "Custom" rather than "$0", which is what the checkout already refuses.
"""

from django.test import TestCase
from django.urls import reverse

from accounts.billing import PLAN_LABELS, PLAN_PRICES, PLAN_USER_LIMITS
from accounts.models import PLAN_EMPLOYEE_LIMITS
from accounts.platform_models import MarketingPage

PRICING = 'pricing'


def price_cell(plan_id):
    """Fetch one plan card as the public site would receive it."""
    response = _pricing_response()
    for section in response['content']['sections']:
        if section.get('type') != 'pricing':
            continue
        for card in section.get('plans', []):
            if card.get('plan') == plan_id:
                return card
    raise AssertionError(f'no card for {plan_id} in the pricing section')


def _pricing_response():
    from django.test import Client

    response = Client().get(reverse('public-marketing-page', args=[PRICING]))
    assert response.status_code == 200, response.status_code
    return response.json()


class AdvertisedPriceMatchesBillingTestCase(TestCase):
    def setUp(self):
        self.page = MarketingPage.objects.get(slug=PRICING)

    def stored_cards(self):
        for section in self.page.content['sections']:
            if section.get('type') == 'pricing':
                return {c['plan']: c for c in section['plans']}
        raise AssertionError('the seeded pricing page has no pricing section')

    def test_every_advertised_price_equals_the_charged_price(self):
        for plan_id, price in PLAN_PRICES.items():
            with self.subTest(plan=plan_id):
                # A 0 price means "not sold by checkout", which is advertised as
                # `Custom`; pinned separately in
                # `test_enterprise_is_advertised_as_custom_not_as_zero_dollars`.
                expected = 'Custom' if not price else f'${price}'
                self.assertEqual(price_cell(plan_id)['price'], expected)

    def test_the_new_scale_tier_is_advertised(self):
        """`scale` had no marketing card, so the page skipped a real plan.

        A plan you can buy but cannot read about is worse than a plan you cannot
        buy: the checkout accepts it, so the gap has to be closed here.
        """
        card = price_cell('scale')
        self.assertEqual(card['name'], PLAN_LABELS['scale'])

    def test_every_plan_appears_exactly_once(self):
        cards = self.stored_cards()
        self.assertEqual(
            sorted(cards), sorted(PLAN_PRICES),
            'the pricing section and PLAN_PRICES disagree on the set of plans',
        )

    def test_advertised_employee_counts_match_what_is_enforced(self):
        for plan_id, limit in PLAN_EMPLOYEE_LIMITS.items():
            with self.subTest(plan=plan_id):
                card = price_cell(plan_id)
                if limit is None:
                    self.assertIn('Unlimited employees', card['blurb'])
                else:
                    self.assertIn(f'{limit} employees', card['blurb'])

    def test_advertised_user_counts_match_what_is_enforced(self):
        for plan_id, limit in PLAN_USER_LIMITS.items():
            with self.subTest(plan=plan_id):
                card = price_cell(plan_id)
                if limit is None:
                    self.assertIn('unlimited team accounts', card['blurb'])
                else:
                    self.assertIn(f'{limit} team accounts', card['blurb'])

    def test_enterprise_is_advertised_as_custom_not_as_zero_dollars(self):
        """`PLAN_PRICES['enterprise']` is 0 because checkout refuses to sell it.

        Rendering that 0 as "$0" would advertise a free plan the checkout
        rejects with "requires a sales agreement".
        """
        self.assertEqual(price_cell('enterprise')['price'], 'Custom')

    def test_the_highlighted_plan_is_the_one_the_checkout_sells(self):
        """Highlight is a marketing choice, but not a free-floating one.

        Only the highlighted card renders the gold CTA. If the highlighted plan
        were Enterprise it would show "Talk to us" where every other card shows
        a self-serve button.
        """
        highlighted = [
            c['plan'] for c in self.stored_cards().values() if c.get('highlight')
        ]
        self.assertEqual(len(highlighted), 1, 'expected exactly one highlighted plan')
        self.assertNotEqual(highlighted[0], 'enterprise')


class StoredCopyIsNotRewrittenTests(AdvertisedPriceMatchesBillingTestCase):
    """An admin's save must not be overwritten by a billing change."""

    def test_serving_the_page_does_not_rewrite_the_stored_row(self):
        stored_before = self.stored_cards()
        _pricing_response()
        self.page.refresh_from_db()
        stored_after = {c['plan']: c for c in
                        self.page.content['sections'][1]['plans']}
        self.assertEqual(stored_before, stored_after)

    def test_a_stale_stored_price_is_replaced_in_the_response_only(self):
        """The real drift case: stored copy says $15, billing says $15.

        Changing the stored copy to a wrong number simulates the historical
        failure. The response must show the charged price, and the stored row
        must keep the admin's number so their next save is not silently undone.
        """
        cards = self.stored_cards()
        cards['professional']['price'] = '$1'
        cards['professional']['blurb'] = 'Up to 3 employees, 1 team account'
        section = next(
            s for s in self.page.content['sections'] if s.get('type') == 'pricing'
        )
        self.page.content['sections'][self.page.content['sections'].index(section)] = section
        self.page.save(update_fields=['content', 'updated_at'])

        card = price_cell('professional')
        self.assertEqual(card['price'], '$99')
        self.assertIn('150 employees', card['blurb'])
        self.assertIn('50 team accounts', card['blurb'])

        self.page.refresh_from_db()
        stored = {c['plan']: c for c in self.page.content['sections'][1]['plans']}
        self.assertEqual(stored['professional']['price'], '$1')

    def test_prose_the_admin_owns_is_not_overwritten(self):
        """Blurbs and features are marketing copy, not billing output.

        An admin's sentence is moved to `tagline` and kept; only the numbers in
        `blurb` are replaced. Without this, deriving the capacity line would
        quietly delete whatever the admin wrote there.
        """
        section = next(
            s for s in self.page.content['sections'] if s.get('type') == 'pricing'
        )
        cards = {c['plan']: c for c in section['plans']}
        cards['business']['features'] = ['Everything in Starter', 'Our own words']
        cards['business']['blurb'] = 'Talk to us about volume.'
        self.page.content['sections'][self.page.content['sections'].index(section)] = section
        self.page.save(update_fields=['content', 'updated_at'])

        card = price_cell('business')
        self.assertIn('Our own words', card['features'])
        self.assertEqual(card['tagline'], 'Talk to us about volume.')
        self.assertIn('50 employees', card['blurb'])

    def test_a_stale_capacity_sentence_is_replaced_not_shown_twice(self):
        """The pre-fix seed stored "Up to 10 employees, 3 team accounts".

        That sentence is stale numbers, not prose, so deriving the capacity line
        must replace it rather than preserve it as a tagline. Otherwise the page
        shows the admin's old claim *and* the enforced one, and the customer sees
        two different answers to "how many employees can I add?".
        """
        section = next(
            s for s in self.page.content['sections'] if s.get('type') == 'pricing'
        )
        cards = {c['plan']: c for c in section['plans']}
        cards['starter']['blurb'] = 'Up to 10 employees, 3 team accounts'
        self.page.content['sections'][self.page.content['sections'].index(section)] = section
        self.page.save(update_fields=['content', 'updated_at'])

        card = price_cell('starter')
        self.assertEqual(card['blurb'], 'Up to 30 employees, 5 team accounts')
        # The seed's own tagline survives untouched; the point is that the stale
        # *capacity* sentence was not promoted into it a second time.
        self.assertEqual(card['tagline'], 'Core HR and payroll for a small team')
        self.assertNotIn('10 employees', str(card))
        self.assertNotIn('3 team accounts', str(card))


class PriceChangesReachThePageTests(TestCase):
    """A price change must not need a second edit in the marketing copy."""

    def test_changing_a_price_changes_what_the_page_advertises(self):
        from accounts import billing

        original = dict(billing.PLAN_PRICES)
        try:
            billing.PLAN_PRICES['starter'] = 19
            self.assertEqual(price_cell('starter')['price'], '$19')
        finally:
            billing.PLAN_PRICES.clear()
            billing.PLAN_PRICES.update(original)
        self.assertEqual(price_cell('starter')['price'], '$15')

    def test_changing_a_limit_changes_what_the_page_advertises(self):
        from accounts import models

        original = dict(models.PLAN_EMPLOYEE_LIMITS)
        try:
            models.PLAN_EMPLOYEE_LIMITS['starter'] = 40
            card = price_cell('starter')
            self.assertIn('40 employees', card['blurb'])
        finally:
            models.PLAN_EMPLOYEE_LIMITS.clear()
            models.PLAN_EMPLOYEE_LIMITS.update(original)
