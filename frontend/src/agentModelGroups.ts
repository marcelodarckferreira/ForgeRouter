type Model = { id: string; enabled: boolean };
type Provider = {
  enabled?: boolean;
  access_type?: 'subscription' | 'api_key' | 'local';
  cost_type?: 'free' | 'paid';
  models: Model[];
};

export type CostClass = 'free' | 'paid' | 'local';

export function modelIdsForCostClass(
  registry: Provider[],
  healthByModel: Record<string, string>,
  target: CostClass,
): string[] {
  return registry.flatMap((provider) => {
    if (provider.enabled === false) return [];
    const costClass: CostClass = provider.access_type === 'local'
      ? 'local'
      : provider.cost_type === 'paid'
        ? 'paid'
        : 'free';
    if (costClass !== target) return [];
    return provider.models
      .filter((model) => model.enabled && healthByModel[model.id] === 'healthy')
      .map((model) => model.id);
  });
}

export function nextAgentModelsForToggle(currentModels: string[], groupModels: string[]): string[] {
  const current = new Set(currentModels);
  const anyOn = groupModels.some((id) => current.has(id));
  return anyOn
    ? currentModels.filter((id) => !groupModels.includes(id))
    : [...new Set([...currentModels, ...groupModels])];
}
