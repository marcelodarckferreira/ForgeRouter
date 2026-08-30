import assert from 'node:assert/strict';
import test from 'node:test';
import * as subscriptionPlanHelpers from '../src/subscriptionPlans.ts';

const { selectedSubscriptionPlanName } = subscriptionPlanHelpers;

const plans = [
  { name: 'openai-codex' },
  { name: 'google-antigravity' },
];

test('subscription plan select reflects the matching provider being edited', () => {
  assert.equal(
    selectedSubscriptionPlanName(plans, 'openai-codex'),
    'openai-codex',
  );
});

test('subscription plan select shows the placeholder for a custom provider', () => {
  assert.equal(selectedSubscriptionPlanName(plans, 'custom-provider'), '');
});

test('subscription authentication URL comes from the selected catalog plan', () => {
  const catalog = [
    { name: 'minimax', auth_url: 'https://platform.minimax.io/' },
    { name: 'custom-plan', auth_url: '' },
  ];

  assert.equal(
    subscriptionPlanHelpers.subscriptionPlanAuthUrl?.(catalog, 'minimax'),
    'https://platform.minimax.io/',
  );
  assert.equal(
    subscriptionPlanHelpers.subscriptionPlanAuthUrl?.(catalog, 'custom-plan'),
    '',
  );
});

test('subscription authentication URL rejects non-web protocols', () => {
  const catalog = [
    { name: 'unsafe-plan', auth_url: 'javascript:alert(1)' },
  ];

  assert.equal(
    subscriptionPlanHelpers.subscriptionPlanAuthUrl?.(catalog, 'unsafe-plan'),
    '',
  );
});

test('subscription metadata is resolved from the selected catalog entry', () => {
  const catalog = [
    { name: 'openai-codex', display_name: 'OpenAI Codex', auth_method: 'oauth', token_hint: 'uses Codex CLI login' },
  ];

  assert.deepEqual(
    subscriptionPlanHelpers.selectedSubscriptionPlan?.(catalog, 'openai-codex'),
    catalog[0],
  );
  assert.equal(
    subscriptionPlanHelpers.selectedSubscriptionPlan?.(catalog, 'custom-plan'),
    undefined,
  );
});
