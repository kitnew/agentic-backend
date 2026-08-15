import type { ComponentType } from "react";

export type FeatureScope = "global" | "tenant";

export type AdminFeatureRoute = {
  id: string;
  path: string;
  component: ComponentType;
};

export type AdminFeature = {
  id: string;
  scope: FeatureScope;
  navigation?: {
    label: string;
    to: string;
    group?: string;
    order?: number;
  };
  permissions?: string[];
};

export type FeatureModule = { feature: AdminFeature };
export type FeatureRoutesModule = { routes: AdminFeatureRoute[] };
