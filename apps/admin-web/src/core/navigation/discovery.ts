import { createFeatureRegistry } from "./registry";
import type { FeatureModule } from "./types";

const modules = import.meta.glob("../../features/**/feature.ts", {
  eager: true,
  import: "default",
}) as Record<string, FeatureModule>;

export const featureRegistry = createFeatureRegistry(
  Object.values(modules).map(({ feature }) => feature),
);
