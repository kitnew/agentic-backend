import { describe, expect, it } from "vitest";

import { createFeatureRegistry } from "../src/core/navigation/registry";
import { navigationUrl } from "../src/core/navigation/urls";

describe("feature registry", () => {
  const features = [
    {
      id: "zeta",
      scope: "tenant" as const,
      navigation: {
        label: "Zeta",
        to: "/tenants/$tenantId/zeta",
        group: "Config",
        order: 20,
      },
    },
    {
      id: "alpha",
      scope: "global" as const,
      navigation: { label: "Alpha", to: "/", group: "Platform", order: 10 },
    },
    {
      id: "beta",
      scope: "tenant" as const,
      navigation: {
        label: "Beta",
        to: "/tenants/$tenantId/beta",
        group: "Config",
        order: 10,
      },
    },
  ];

  it("validates IDs, groups deterministically, and distinguishes scope", () => {
    const registry = createFeatureRegistry(features);
    expect(registry.navigation.map(({ label }) => label)).toEqual([
      "Config",
      "Platform",
    ]);
    expect(registry.navigation[0]?.items.map(({ label }) => label)).toEqual([
      "Beta",
      "Zeta",
    ]);
    expect(registry.forScope("global").map(({ id }) => id)).toEqual(["alpha"]);
  });

  it("fails clearly for duplicate IDs", () => {
    expect(() =>
      createFeatureRegistry([
        { id: "same", scope: "global" },
        { id: "same", scope: "tenant" },
      ]),
    ).toThrow("Duplicate Admin feature id: same");
  });

  it("generates tenant navigation from feature metadata", () => {
    const item = createFeatureRegistry(features).navigation[0]?.items[0];
    expect(item && navigationUrl(item, "tenant-1")).toBe(
      "/tenants/tenant-1/beta",
    );
  });
});
