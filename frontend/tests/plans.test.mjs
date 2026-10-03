// The plan ladder, tested with Node's built-in runner (`npm test`).
//
// No test framework was installed and none was added: node:test and node:assert
// ship with Node, so this runs offline with no new dependency and no lockfile
// churn. The logic under test is deliberately plain data with no JSX and no
// React, which is what makes that possible.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  AI_MINIMUM_PLAN,
  AI_PLANS,
  PLAN_LABELS,
  PLAN_ORDER,
  isDowngradeFrom,
  isKnownPlan,
  isUpgradeFrom,
  planLabel,
  planPosition,
  sortPlans,
} from '../src/constants/plans.js';

// What /auth/billing/plans/ returns, per backend/accounts/platform.py.
const PLANS = [
  { id: 'enterprise', name: 'Enterprise', monthly_price: '0', employee_limit: null, user_limit: null },
  { id: 'starter', name: 'Starter', monthly_price: '15', employee_limit: 30, user_limit: 5 },
  { id: 'professional', name: 'Professional', monthly_price: '99', employee_limit: 150, user_limit: 50 },
  { id: 'business', name: 'Business', monthly_price: '49', employee_limit: 50, user_limit: 15 },
  { id: 'scale', name: 'Scale', monthly_price: '249', employee_limit: 400, user_limit: 100 },
];

test('every plan the backend offers is on the ladder', () => {
  for (const plan of PLANS) {
    assert.ok(isKnownPlan(plan.id), `${plan.id} is missing from PLAN_ORDER`);
  }
});

test('the ladder is in ascending cost order', () => {
  const prices = ['starter', 'business', 'professional', 'scale']
    .map((id) => Number(PLANS.find((p) => p.id === id).monthly_price));
  assert.deepEqual(prices, [...prices].sort((a, b) => a - b));
  // Enterprise is unsold-by-checkout and therefore last.
  assert.equal(PLAN_ORDER[PLAN_ORDER.length - 1], 'enterprise');
});

test('sortPlans puts the cheapest plan first', () => {
  assert.equal(sortPlans(PLANS)[0].id, 'starter');
});

test('sortPlans puts Scale between Professional and Enterprise', () => {
  assert.deepEqual(sortPlans(PLANS).map((p) => p.id), [
    'starter', 'business', 'professional', 'scale', 'enterprise',
  ]);
});

test('an unknown plan sorts last, never first', () => {
  // The bug: `PLAN_ORDER.indexOf('scale')` was -1 before Scale was added, which
  // sorted it to the top of the grid *and* made it read as a downgrade.
  const withStranger = [...PLANS, { id: 'stranger', name: 'Stranger' }];
  const order = sortPlans(withStranger).map((p) => p.id);
  assert.equal(order[order.length - 1], 'stranger');
  assert.ok(order.indexOf('starter') < order.indexOf('stranger'));
});

test('sortPlans does not mutate its argument', () => {
  const input = [...PLANS];
  const before = input.map((p) => p.id);
  sortPlans(input);
  assert.deepEqual(input.map((p) => p.id), before);
});

test('a plan missing from the ladder is never treated as an upgrade', () => {
  // `-1 < current`, so a naive comparison calls an unknown plan an upgrade.
  assert.equal(planPosition('stranger'), -1);
  assert.equal(isUpgradeFrom('professional', 'stranger'), false);
  assert.equal(isDowngradeFrom('professional', 'stranger'), false);
  assert.equal(isUpgradeFrom('stranger', 'professional'), false);
  assert.equal(isDowngradeFrom('stranger', 'professional'), false);
});

test('moving up and down the ladder', () => {
  assert.equal(isUpgradeFrom('starter', 'professional'), true);
  assert.equal(isDowngradeFrom('starter', 'professional'), false);

  assert.equal(isUpgradeFrom('professional', 'scale'), true);
  assert.equal(isDowngradeFrom('professional', 'scale'), false);

  assert.equal(isDowngradeFrom('scale', 'starter'), true);
  assert.equal(isUpgradeFrom('scale', 'starter'), false);

  assert.equal(isUpgradeFrom('scale', 'enterprise'), true);
  assert.equal(isUpgradeFrom('enterprise', 'scale'), false);
});

test('a plan is never an upgrade or downgrade from itself', () => {
  for (const plan of PLAN_ORDER) {
    assert.equal(isUpgradeFrom(plan, plan), false, plan);
    assert.equal(isDowngradeFrom(plan, plan), false, plan);
  }
});

test('Professional and above carry AI; Starter and Business do not', () => {
  assert.deepEqual(AI_PLANS, ['professional', 'scale', 'enterprise']);
  assert.ok(AI_PLANS.includes(AI_MINIMUM_PLAN));
  for (const id of PLAN_ORDER) {
    const expected = id === 'professional' || id === 'scale' || id === 'enterprise';
    assert.equal(AI_PLANS.includes(id), expected, id);
  }
});

test('every plan has a display label', () => {
  for (const id of PLAN_ORDER) {
    assert.equal(planLabel(id), PLAN_LABELS[id]);
  }
});

test('planLabel falls back rather than rendering undefined', () => {
  assert.equal(planLabel('stranger'), 'stranger');
  assert.equal(planLabel(''), 'your plan');
});
