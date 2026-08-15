import type { AdminFeature, FeatureScope } from "./types";

const featureId = /^[a-z][a-z0-9-]*$/;

export type NavigationItem = Required<AdminFeature>["navigation"] & {
  featureId: string;
  scope: FeatureScope;
  permissions: string[];
};

export type NavigationGroup = { label: string; items: NavigationItem[] };

export type FeatureRegistry = {
  features: AdminFeature[];
  navigation: NavigationGroup[];
  forScope(scope: FeatureScope): AdminFeature[];
};

function byOrder<T extends { order?: number; label: string }>(
  left: T,
  right: T,
) {
  return (
    (left.order ?? 0) - (right.order ?? 0) ||
    left.label.localeCompare(right.label)
  );
}

export function createFeatureRegistry(
  features: AdminFeature[],
): FeatureRegistry {
  const ids = new Set<string>();
  for (const feature of features) {
    if (!featureId.test(feature.id))
      throw new Error(`Invalid Admin feature id: ${feature.id}`);
    if (ids.has(feature.id))
      throw new Error(`Duplicate Admin feature id: ${feature.id}`);
    ids.add(feature.id);
  }
  const sorted = [...features].sort((left, right) =>
    left.id.localeCompare(right.id),
  );
  const groups = new Map<string, NavigationItem[]>();
  for (const feature of sorted) {
    if (!feature.navigation) continue;
    const group = feature.navigation.group ?? "Platform";
    const item: NavigationItem = {
      ...feature.navigation,
      featureId: feature.id,
      scope: feature.scope,
      permissions: feature.permissions ?? [],
    };
    groups.set(group, [...(groups.get(group) ?? []), item]);
  }
  return {
    features: sorted,
    navigation: [...groups.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([label, items]) => ({ label, items: items.sort(byOrder) })),
    forScope: (scope) => sorted.filter((feature) => feature.scope === scope),
  };
}
