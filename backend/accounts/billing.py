from datetime import timedelta
from django.utils import timezone
from .models import PLAN_CHOICES, PLAN_EMPLOYEE_LIMITS

# Display names taken straight from the model, so a tier cannot be added
# without a label existing for every message that names it.
PLAN_LABELS = dict(PLAN_CHOICES)

PLAN_USER_LIMITS = {'starter': 5, 'business': 15, 'professional': 50, 'scale': 100, 'enterprise': None}
PLAN_PRICES = {'starter': 15, 'business': 49, 'professional': 99, 'scale': 249, 'enterprise': 0}

# The lowest plan that carries AI, and every plan above it.
#
# AI is the one capability that cannot ride on a flat, headcount-based price.
# Everything else a plan gates - employee records, logins, payslip PDFs -
# costs the platform roughly in proportion to how many people are on the
# account. Token spend does not: a five-person company can push more documents
# through the assistant than a four-hundred-person one, because usage is driven
# by how much the finance team types, not by roster size. Gating it from
# Professional up keeps that cost off the two cheapest tiers.
AI_MINIMUM_PLAN = 'professional'
AI_PLANS = frozenset({'professional', 'scale', 'enterprise'})

AI_DENIAL_MESSAGE = (
    'The AI assistant is available on the Professional plan and above. '
    'Upgrade your plan to use the AI assistant, AI drafts and the company '
    'knowledge base.'
)


def ai_allowed(company):
    """Whether ``company``'s plan includes the AI assistant and knowledge base.

    A company-less user (platform staff) has no subscription to check, so this
    returns False. Platform-wide AI configuration is a separate, ungated
    surface: it is the operator's own console, not a tenant feature.
    """
    return bool(company) and company.plan in AI_PLANS


def ai_denial_message(user):
    """The sentence shown when a company is refused AI on plan grounds."""
    if not (user and getattr(user, 'company_id', None)):
        return AI_DENIAL_MESSAGE
    plan = user.company.plan
    return (
        f'The AI assistant is available on the '
        f'{PLAN_LABELS[AI_MINIMUM_PLAN]} plan and above. Your company is on '
        f'the {PLAN_LABELS.get(plan, plan)} plan. Upgrade to use the AI '
        f'assistant, AI drafts and the company knowledge base.'
    )


def ai_refusal_body(user):
    """Structured 403 body for a plan-gated AI request.

    DRF renders a denied permission as ``{"detail": ...}`` and nothing else,
    which is not enough for the SPA to offer the right plan. ``PermissionDenied``
    accepts a dict and passes it through as the response body, so the extra keys
    cost nothing at the view.
    """
    company = getattr(user, 'company', None)
    return {
        'detail': ai_denial_message(user),
        'code': 'plan_upgrade_required',
        'required_plan': ai_upgrade_target(company) or AI_MINIMUM_PLAN,
        'current_plan': getattr(company, 'plan', None),
        'upgrade_url': '/billing',
    }


def ai_upgrade_target(company):
    """The plan a blocked company should be moved to, for the error payload.

    A company already above the gate gets ``None``; it is not blocked and must
    not be told to upgrade.
    """
    if company is None or company.plan in AI_PLANS:
        return None
    return AI_MINIMUM_PLAN


def subscription_state(company):
    try:
        sub = company.subscription
    except Exception:
        return {'status': 'missing', 'allowed': False, 'reason': 'No subscription is configured.'}
    now = timezone.now()
    if sub.status == 'trial' and sub.trial_ends_at and now > sub.trial_ends_at:
        if sub.grace_ends_at and now <= sub.grace_ends_at:
            return {'status': 'grace', 'allowed': True, 'reason': 'Subscription trial ended; grace period is active.'}
        return {'status': 'expired', 'allowed': False, 'reason': 'Trial period has ended.'}
    if sub.status == 'past_due':
        if sub.grace_ends_at and now <= sub.grace_ends_at:
            return {'status': 'grace', 'allowed': True, 'reason': 'Payment is past due; grace period is active.'}
        return {'status': 'past_due', 'allowed': False, 'reason': 'Payment is past due and the grace period has ended.'}
    if sub.status == 'active' and sub.renews_at and now > sub.renews_at:
        if sub.grace_ends_at and now <= sub.grace_ends_at:
            return {'status': 'grace', 'allowed': True, 'reason': 'Renewal is overdue; grace period is active.'}
        return {'status': 'past_due', 'allowed': False, 'reason': 'Renewal is overdue.'}
    if sub.status == 'cancelled':
        if sub.grace_ends_at and now <= sub.grace_ends_at:
            return {'status': 'grace', 'allowed': True, 'reason': 'Subscription is cancelled but remains active during the grace period.'}
        return {'status': 'cancelled', 'allowed': False, 'reason': 'Subscription is cancelled.'}
    return {'status': sub.status, 'allowed': sub.status in ('trial', 'active'), 'reason': ''}


def start_trial(sub, days=14):
    now = timezone.now()
    sub.status = 'trial'
    sub.started_at = sub.started_at or now
    sub.trial_ends_at = now + timedelta(days=days)
    sub.grace_ends_at = None
    sub.save(update_fields=['status', 'started_at', 'trial_ends_at', 'grace_ends_at', 'updated_at'])


def employee_limit(company):
    return company.employee_limit


def user_limit(company):
    return PLAN_USER_LIMITS.get(company.plan)
