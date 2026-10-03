"""Derive advertised prices from the tables that actually charge.

The public pricing page used to hold its own copy of every number - `$15`, "Up to
10 employees, 3 team accounts" - while `PLAN_PRICES` and `PLAN_USER_LIMITS`
charged a different set. Nothing read the marketing copy back, so the two drifted
silently: the site advertises a plan the checkout will refuse, or prices a plan
in the one currency a customer does not accept.

This module is the join between them. Prices and capacity lines are computed from
the billing tables on the way out of the API, so `PLAN_PRICES` is the only place a
price exists. Prose - the blurb's wording, the feature list, which card is
highlighted - stays the admin's, because those are judgements rather than facts
about the product.

The stored marketing row is deliberately not rewritten. If it were, an admin's
next save would silently revert a price change they never made, and the editor
would show numbers that differ from the ones on the live page for no visible
reason. Keeping the derivation at serve time means the stored copy can be stale
and still correct on the wire.
"""

from accounts.billing import PLAN_LABELS, PLAN_PRICES, PLAN_USER_LIMITS
from accounts.models import PLAN_EMPLOYEE_LIMITS

# Shown instead of a number for plans that are not self-serve. `PLAN_PRICES` uses
# 0 for Enterprise because the checkout refuses to sell it (it needs a sales
# agreement), so rendering that 0 honestly would advertise a free plan that
# cannot be bought.
CUSTOM_LABEL = 'Custom'


def price_label(plan):
    """`$249`, or `Custom` for a plan that is not sold by checkout."""
    if plan not in PLAN_PRICES:
        return CUSTOM_LABEL
    amount = PLAN_PRICES[plan]
    if not amount:
        return CUSTOM_LABEL
    return f'${amount}'


def capacity_line(plan):
    """The "Up to 30 employees, 5 team accounts" sentence, from the limits."""
    employees = PLAN_EMPLOYEE_LIMITS.get(plan)
    users = PLAN_USER_LIMITS.get(plan)
    head = 'Unlimited employees' if employees is None else f'Up to {employees} employees'
    accounts = 'unlimited team accounts' if users is None else f'{users} team accounts'
    return f'{head}, {accounts}'


def derived_card(card):
    """One pricing card with its numbers replaced by the billing tables.

    A card with no recognisable `plan` key is returned untouched: an admin may
    legitimately add a bespoke card ("Talk to us") that is not one of the five
    plans, and inventing a price for it would be worse than showing what they
    wrote.
    """
    if not isinstance(card, dict):
        return card
    plan = card.get('plan')
    if plan not in PLAN_PRICES:
        return card
    updated = dict(card)
    updated['price'] = price_label(plan)
    # Any `blurb` the admin wrote is prose, not numbers, so it is preserved as
    # `tagline` and the derived capacity line takes over `blurb`. A stored blurb
    # that is only a capacity sentence - which is what the old seed held - is
    # dropped rather than shown twice.
    stored_blurb = (updated.get('blurb') or '').strip()
    if stored_blurb and not _is_capacity_only(stored_blurb):
        updated['tagline'] = stored_blurb
    updated['blurb'] = capacity_line(plan)
    if not updated.get('name'):
        updated['name'] = PLAN_LABELS.get(plan, plan)
    return updated


def _is_capacity_only(text):
    """True when a blurb is only a capacity sentence, with no prose in it.

    The pre-fix seed stored exactly "Up to 10 employees, 3 team accounts". That
    has to be recognised as stale data and replaced, or the page would show both
    the old sentence and the derived one.
    """
    return (
        text.lower().startswith(('up to ', 'unlimited '))
        and 'employee' in text.lower()
        and 'team account' in text.lower()
    )


def derived_content(content):
    """A pricing section with every card's numbers derived.

    Non-pricing sections and any card shape not recognised are returned as they
    were, so this is safe to run over every public page.
    """
    if not isinstance(content, dict):
        return content
    sections = content.get('sections')
    if not isinstance(sections, list):
        return content
    result = dict(content)
    new_sections = []
    for section in sections:
        if not isinstance(section, dict) or section.get('type') != 'pricing':
            new_sections.append(section)
            continue
        updated = dict(section)
        plans = updated.get('plans')
        if isinstance(plans, list):
            updated['plans'] = [derived_card(c) for c in plans]
        new_sections.append(updated)
    result['sections'] = new_sections
    return result
