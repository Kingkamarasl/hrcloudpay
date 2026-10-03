"""
Platform-wide feature flags.

Site/platform admins toggle these in Platform Admin → Feature flags.
When a flag is missing from the DB, `default` from DEFAULT_FEATURES applies
(usually False for experimental modules so nothing breaks until configured).
"""
from __future__ import annotations

from django.conf import settings

# key -> (name, description, default_enabled)
DEFAULT_FEATURES = {
    'payroll_email_payslips': (
        'Email payslips',
        'Allow companies to email payslip PDFs to employees. Requires working email backend.',
        False,
    ),
    'payroll_bank_file': (
        'Bank transfer file export',
        'CSV bank file download per payroll run (account number + net pay).',
        True,
    ),
    'payroll_compare_runs': (
        'Compare payroll periods',
        'Side-by-side comparison of two payroll runs.',
        True,
    ),
    'payroll_overtime': (
        'Overtime rules & entries',
        'Labour-law style OT multipliers and entries included in payroll.',
        False,
    ),
    'payroll_salary_advances': (
        'Salary advances',
        'Grant advances and recover installments automatically on payroll runs.',
        False,
    ),
    'leave_accruals': (
        'Leave accruals',
        'Monthly leave accrual policies and balances.',
        False,
    ),
    'leave_encashment': (
        'Leave encashment',
        'Cash out leave balances when policy allows.',
        False,
    ),
    'integrations_oauth': (
        'OAuth integrations (Xero / QuickBooks / Microsoft)',
        'Connect external accounting suites. Requires platform OAuth client IDs in environment.',
        False,
    ),
    'integrations_file_import': (
        'CSV / Excel employee import',
        'Bulk import employees from file on Integrations page.',
        True,
    ),
    'workflows_automation': (
        'HR workflows & notifications',
        'Automated tasks and in-app workflow rules.',
        True,
    ),
}


# Why a feature is unavailable. These drive the wording shown to the user, so
# each one must describe what actually happened rather than defaulting to a
# single "an administrator disabled this" message - which is only true for
# REASON_DISABLED.
REASON_DISABLED = 'disabled'
REASON_ENVIRONMENT = 'environment'
REASON_ROLLOUT_ZERO = 'rollout_zero'
REASON_ROLLOUT_BUCKET = 'rollout_bucket'


def ensure_default_flags():
    """Create any missing FeatureFlag rows from DEFAULT_FEATURES (idempotent)."""
    from .platform_models import FeatureFlag
    created = []
    for key, (name, description, enabled) in DEFAULT_FEATURES.items():
        obj, was_created = FeatureFlag.objects.get_or_create(
            key=key,
            defaults={
                'name': name,
                'description': description,
                'enabled': enabled,
                'rollout_percent': 100,
                'environment': 'all',
            },
        )
        if was_created:
            created.append(key)
        else:
            # Keep name/description in sync with catalog; do not override enabled
            if obj.name != name or obj.description != description:
                obj.name = name
                obj.description = description
                obj.save(update_fields=['name', 'description', 'updated_at'])
    return created


def is_feature_enabled(key: str, company=None) -> bool:
    """
    Return True if the platform flag allows this feature.
    Missing flag → catalog default (usually False for experimental).
    environment 'test' only when DEBUG; 'live' only when not DEBUG.

    Call feature_status() when you also need to know *why* it is off - the five
    ways this can return False are not the same message to a user.
    """
    return feature_status(key, company=company)[0]


def feature_status(key: str, company=None):
    """
    Return (enabled, reason) for a feature flag.

    ``reason`` is '' when enabled, otherwise one of the REASON_* constants below.
    The distinction matters: "an administrator switched this off" and "your
    company is not in the staged cohort yet" are both 403s, but telling a
    tenant the second one implies a person judged them, when in fact the
    rollout may simply reach them on its own.

    REASON_DISABLED   - the flag is explicitly off.
    REASON_ENVIRONMENT- enabled only in the other environment (test vs live).
    REASON_ROLLOUT_ZERO - the staged rollout is set to 0%.
    REASON_ROLLOUT_BUCKET - the staged rollout has not reached this company yet.
    """
    from .platform_models import FeatureFlag

    try:
        flag = FeatureFlag.objects.filter(key=key).first()
    except Exception:
        # DB not migrated yet
        _name, _desc, default = DEFAULT_FEATURES.get(key, (key, '', False))
        return bool(default), '' if default else REASON_DISABLED

    if flag is None:
        _name, _desc, default = DEFAULT_FEATURES.get(key, (key, '', False))
        return bool(default), '' if default else REASON_DISABLED

    if not flag.enabled:
        return False, REASON_DISABLED

    env = flag.environment or 'all'
    debug = bool(getattr(settings, 'DEBUG', True))
    if env == 'test' and not debug:
        return False, REASON_ENVIRONMENT
    if env == 'live' and debug:
        return False, REASON_ENVIRONMENT

    # rollout_percent is a percentage of tenants that get the feature.
    if flag.rollout_percent is not None and flag.rollout_percent <= 0:
        return False, REASON_ROLLOUT_ZERO
    if flag.rollout_percent is not None and flag.rollout_percent < 100:
        if company is None:
            # No tenant to bucket. A partial rollout cannot be resolved, so treat
            # it as enabled rather than silently locking every caller out.
            pass
        else:
            bucket = (getattr(company, 'id', 0) or 0) % 100
            if bucket >= flag.rollout_percent:
                return False, REASON_ROLLOUT_BUCKET

    return True, ''


def require_feature(key: str, company=None):
    """DRF-friendly helper: returns (ok, response_or_none).

    Pass `company` so a flag with a partial `rollout_percent` is bucketed per
    tenant. Omitting it makes the flag behave as if rolled out to everyone,
    because is_feature_enabled() only applies the bucket when given a company.
    """
    from rest_framework.response import Response
    from rest_framework import status

    enabled, reason = feature_status(key, company=company)
    if enabled:
        return True, None
    name = DEFAULT_FEATURES.get(key, (key,))[0]
    return False, Response(
        {
            'detail': feature_unavailable_message(name, reason),
            'feature_key': key,
            'feature_name': name,
            'reason': reason,
            'code': 'feature_disabled',
        },
        status=status.HTTP_403_FORBIDDEN,
    )


def feature_unavailable_message(name: str, reason: str) -> str:
    """Explain an unavailable feature in terms of what actually happened.

    The previous single message ("currently disabled by the platform
    administrator. Contact support if you need it enabled.") was wrong twice
    over:

    * it claimed an administrator had switched the feature off in the three
      rollout/environment cases, where no one made that decision about this
      tenant - and in the partial-rollout case it implies a colleague judged
      them, when the feature may simply reach them as the rollout widens;
    * it told the user to contact support, but the only support endpoint
      (/auth/platform/support/) is IsAdminUser, so a company owner has no way to
      open a ticket, and no support inbox is configured for this deployment.

    So each reason now gets wording that is true, and no message invents a
    support channel that does not exist.
    """
    if reason == REASON_ROLLOUT_BUCKET:
        return (
            f'{name} is being rolled out gradually and is not yet available to '
            'your workspace. It may reach you automatically as the rollout '
            'widens — no action is needed from you.'
        )
    if reason == REASON_ROLLOUT_ZERO:
        return (
            f'{name} is currently paused. A staged rollout has been prepared '
            'but has not been started.'
        )
    if reason == REASON_ENVIRONMENT:
        return (
            f'{name} is not available in this environment. It can be enabled '
            'for your workspace by your platform administrator once it is '
            'released here.'
        )
    # REASON_DISABLED, and the safe default for an unrecognised reason.
    return (
        f'{name} is turned off for your workspace. Your platform administrator '
        'can switch it on if you need it.'
    )


def public_feature_map(company=None) -> dict:
    """Dict of key -> enabled for the current environment/company."""
    ensure_default_flags()
    return {key: is_feature_enabled(key, company=company) for key in DEFAULT_FEATURES}


def public_feature_status_map(company=None) -> dict:
    """Dict of key -> {'enabled': bool, 'reason': str, 'message': str}.

    The reason matters to the UI: "an administrator turned this off" and "your
    workspace is not in the staged cohort yet" are both `enabled: false`, but
    only one of them is a decision somebody made about this tenant. Without it
    the frontend has to guess, and it guesses wrong - it told every tenant the
    feature had been disabled by an administrator.

    The sentence itself is included so the wording has exactly one home. When
    the UI built its own copy it drifted from this module, which is how two
    different explanations of the same 403 ended up in the product.
    """
    ensure_default_flags()
    out = {}
    for key, (name, _desc, _default) in DEFAULT_FEATURES.items():
        enabled, reason = feature_status(key, company=company)
        out[key] = {
            'enabled': enabled,
            'reason': reason,
            'message': '' if enabled else feature_unavailable_message(name, reason),
        }
    return out
