export function selectedSubscriptionPlan<T extends { name: string }>(
  plans: readonly T[],
  editingName: string,
): T | undefined {
  return plans.find((plan) => plan.name === editingName);
}

export function selectedSubscriptionPlanName(
  plans: readonly { name: string }[],
  editingName: string,
): string {
  return selectedSubscriptionPlan(plans, editingName) ? editingName : '';
}

export function subscriptionPlanAuthUrl(
  plans: readonly { name: string; auth_url?: string }[],
  editingName: string,
): string {
  const authUrl = selectedSubscriptionPlan(plans, editingName)?.auth_url ?? '';
  if (!authUrl) return '';
  try {
    const protocol = new URL(authUrl).protocol;
    return protocol === 'https:' || protocol === 'http:' ? authUrl : '';
  } catch {
    return '';
  }
}
