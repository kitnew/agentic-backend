import { describe, expect, it } from "vitest";

import {
  getGetComponentManagementV1PlatformComponentsKindGetUrl,
  getGetConfigurationManagementV1PlatformConfigurationGetUrl,
  getGetConfigurationManagementV1TenantsTenantIdConfigurationGetUrl,
  getGetSystemConfigurationManagementV1SystemConfigurationGetUrl,
  getListCredentialsManagementV1CredentialsGetUrl,
} from "../src/core/api/control-plane/generated/default/default";

describe("Control Plane browser client", () => {
  it("uses the same-origin proxy path", () => {
    expect(
      getGetComponentManagementV1PlatformComponentsKindGetUrl("SystemPrompt"),
    ).toBe("/management/v1/platform/components/SystemPrompt");
    expect(getListCredentialsManagementV1CredentialsGetUrl()).toBe(
      "/management/v1/credentials",
    );
    expect(
      getGetSystemConfigurationManagementV1SystemConfigurationGetUrl(),
    ).toBe("/management/v1/system/configuration");
    expect(getGetConfigurationManagementV1PlatformConfigurationGetUrl()).toBe(
      "/management/v1/platform/configuration",
    );
    expect(
      getGetConfigurationManagementV1TenantsTenantIdConfigurationGetUrl("t1"),
    ).toBe("/management/v1/tenants/t1/configuration");
  });

  it("does not contain a management credential", async () => {
    const source = await import(
      "../src/core/api/control-plane/generated/default/default?raw"
    );
    expect(source.default).not.toContain("CONTROL_PLANE_MANAGEMENT_TOKEN");
    expect(source.default).not.toMatch(/Authorization\s*:/);
  });
});
