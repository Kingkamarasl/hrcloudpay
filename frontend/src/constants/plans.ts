// The plan ladder, in one place.
//
// The backend is the source of truth for prices and limits (`PLAN_PRICES`,
// `PLAN_EMPLOYEE_LIMITS`, `PLAN_USER_LIMITS` in accounts/billing.py and
// accounts/models.py) and serves them from `/auth/billing/plans/`. What the SPA
// still needs for itself is the *order* of the ladder, and which plans carry AI.
//
// The order was the bug this module exists to fix. `Billing.jsx` sorted plans
// with `PLAN_ORDER.indexOf(plan.id)` and that array had four entries. A plan
// missing from it gets -1, which put it at the top of the grid and made it look
// like a downgrade - so adding the Scale tier to the backend silently made it
// render first with its button disabled and captioned "Downgrade in portal".
// Nothing failed; a paying customer simply could not buy the plan above them.
//
// `planPosition` and `sortPlans` live here rather than inline so that is a
// one-line fix, and so it can be tested without a DOM.

// Ascending cost. `enterprise` is last because it is not self-serve; the backend
// rejects its checkout with "requires a sales agreement".
export const PLAN_ORDER = ['starter', 'business', 'professional', 'scale', 'enterprise'] as const;

export const PLAN_LABELS: Record<string, string> = {
  starter: 'Starter',
  business: 'Business',
  professional: 'Professional',
  scale: 'Scale',
  enterprise: 'Enterprise',
};

// Mirrors accounts.billing.AI_PLANS. AI is priced separately from headcount -
// model tokens are billed per token, so it cannot ride on a flat monthly fee -
// and is therefore held back to the tiers that can absorb it.
export const AI_PLANS = ['professional', 'scale', 'enterprise'] as const;
export const AI_MINIMUM_PLAN = 'professional';

export type PlanId = typeof PLAN_ORDER[number];

export function isKnownPlan(planId: string): boolean {
  return PLAN_ORDER.includes(planId as PlanId);
}

export function planLabel(planId: string): string {
  return PLAN_LABELS[planId] || planId || 'your plan';
}

/**
 * Where a plan sits on the ladder, or -1 when it is not on it.
 *
 * -1 must never be treated as "the cheapest". Every caller that compares two
 * positions has to handle it, which `isUpgradeFrom` does.
 */
export function planPosition(planId: string): number {
  return PLAN_ORDER.indexOf(planId as PlanId);
}

/** True when `targetId` is a strictly higher tier than `currentId`. */
export function isUpgradeFrom(currentId: string, targetId: string): boolean {
  const current = planPosition(currentId);
  const target = planPosition(targetId);
  if (current === -1 || target === -1) return false;
  return target > current;
}

/** True when `targetId` is a strictly lower tier than `currentId`. */
export function isDowngradeFrom(currentId: string, targetId: string): boolean {
  const current = planPosition(currentId);
  const target = planPosition(targetId);
  if (current === -1 || target === -1) return false;
  return target < current;
}

/**
 * Order plans cheapest first, for display.
 *
 * A plan missing from `PLAN_ORDER` is placed *after* every known plan rather
 * than before them. Sorting it to the front is what made Scale unusable, and a
 * future plan that someone forgets to add here would be the same bug again.
 */
export function sortPlans(plans: Array<{ id: string }>): Array<{ id: string }> {
  return [...plans].sort((a, b) => {
    const left = planPosition(a.id);
    const right = planPosition(b.id);
    if (left === -1 && right === -1) return 0;
    if (left === -1) return 1;
    if (right === -1) return -1;
    return left - right;
  });
}