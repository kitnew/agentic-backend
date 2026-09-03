import { describe, expect, it } from "vitest";

import {
  getGetComponentV1ScopesPlatformComponentsKindGetUrl,
  getListCredentialsV1ManagedResourcesCredentialsGetUrl,
} from "../src/core/api/control-plane/generated/default/default";

describe("Control Plane browser client", () => {
  it("uses the same-origin proxy path", () => {
    expect(
      getGetComponentV1ScopesPlatformComponentsKindGetUrl(
        "runtime.llm.defaults",
      ),
    ).toBe("/control-plane/scopes/platform/components/runtime.llm.defaults");
    expect(getListCredentialsV1ManagedResourcesCredentialsGetUrl()).toBe(
      "/control-plane/managed-resources/credentials",
    );
  });

  it("does not contain a management credential", async () => {
    const source = await import(
      "../src/core/api/control-plane/generated/default/default?raw"
    );
    expect(source.default).not.toContain("CONTROL_PLANE_MANAGEMENT_TOKEN");
    expect(source.default).not.toMatch(/Authorization\s*:/);
  });
});
