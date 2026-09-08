import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { AppProviders } from "../src/app/providers";
import { managementMutationOptions } from "../src/core/api/client";
import type {
  PlatformConfiguration,
  SystemConfiguration,
  TenantConfiguration,
} from "../src/core/api/control-plane";
import { normalizeApiError } from "../src/core/api/errors";
import {
  PlatformConfigurationEditor,
  platformDesired,
  SystemConfigurationEditor,
  systemDesired,
  TenantConfigurationEditor,
  tenantDesired,
} from "../src/core/configuration/high-level";
import { server } from "./setup";

const systemConfiguration = {
  stt_defaults: {},
  llm_defaults: {},
  tts_defaults: {},
  realtime_defaults: {},
  policies: {},
} as SystemConfiguration;

const platformConfiguration = {
  system_prompt: {
    active: { content: "active system" },
    draft: { content: "draft system" },
  },
  profiles: [
    {
      key: "hotel",
      name: "Hotel",
      description: "Hotel profile",
      status: "enabled",
      prompt: {
        active: { content: "active profile" },
        draft: { content: "draft profile" },
      },
    },
  ],
  interaction_modes: [
    {
      key: "friendly",
      name: "Friendly",
      description: "Friendly mode",
      status: "disabled",
      prompt: { active: { content: "active mode" } },
    },
  ],
  status: { has_drafts: true, publishable: true },
} as PlatformConfiguration;

const tenantConfiguration = {
  tenant_id: "tenant-1",
  versioned: {
    tenant_prompt: {
      active: { content: "active tenant" },
      draft: { content: "draft tenant" },
    },
    knowledge: { active: { content: "active knowledge" } },
    agent_personality: {
      active: { display_name: "Active" },
      draft: { display_name: "Draft" },
    },
    business_info: {
      active: { business: { name: "Active business" } },
      draft: { business: { name: "Draft business" } },
    },
    actions_definition: {
      active: { actions: { old: {} } },
      draft: { actions: { new: {} } },
    },
  },
  live: {
    architecture: { architecture_key: "cascade" },
    profile_reference: { profile_key: "hotel" },
    runtime_overrides: { tts: { voice_id: "voice-1" } },
    actions_availability: { actions: { new: true } },
  },
  status: { has_drafts: true, publishable: true },
} as unknown as TenantConfiguration;

const errorResponse = (code: string, message: string) => ({
  code,
  message,
  issues: [{ code: "invalid_value", path: "llm_defaults", message }],
  request_id: "request-1",
});

describe("high-level configuration transport and mappings", () => {
  it("normalizes target ErrorResponse fields and issues", () => {
    expect(
      normalizeApiError({
        status: 422,
        data: {
          code: "configuration_invalid",
          message: "Configuration is invalid",
          issues: [
            {
              path: "profile_reference",
              code: "unknown_profile",
              message: "Unknown profile",
            },
          ],
          request_id: "request-42",
        },
      }),
    ).toEqual({
      status: 422,
      code: "configuration_invalid",
      message: "Configuration is invalid",
      issues: [
        {
          path: "profile_reference",
          code: "unknown_profile",
          message: "Unknown profile",
        },
      ],
      requestId: "request-42",
    });
  });

  it("uses an initial precondition or the exact current ETag", () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue(
      "00000000-0000-0000-0000-000000000001",
    );
    expect(managementMutationOptions(null, true)).toEqual({
      headers: {
        "Idempotency-Key": "00000000-0000-0000-0000-000000000001",
        "If-None-Match": "*",
      },
    });
    expect(managementMutationOptions('"etag-1"')).toEqual({
      headers: {
        "Idempotency-Key": "00000000-0000-0000-0000-000000000001",
        "If-Match": '"etag-1"',
      },
    });
    vi.restoreAllMocks();
  });

  it("maps system semantic values without transport metadata", () => {
    expect(systemDesired(systemConfiguration)).toEqual(systemConfiguration);
  });

  it("maps platform drafts over active prompts and keeps catalog metadata", () => {
    expect(platformDesired(platformConfiguration)).toEqual({
      system_prompt: { content: "draft system" },
      profiles: [
        {
          key: "hotel",
          name: "Hotel",
          description: "Hotel profile",
          status: "enabled",
          prompt: { content: "draft profile" },
        },
      ],
      interaction_modes: [
        {
          key: "friendly",
          name: "Friendly",
          description: "Friendly mode",
          status: "disabled",
          prompt: { content: "active mode" },
        },
      ],
    });
  });

  it("maps tenant drafts over active values and keeps live semantics", () => {
    expect(tenantDesired(tenantConfiguration)).toEqual({
      tenant_prompt: { content: "draft tenant" },
      knowledge: { content: "active knowledge" },
      agent_personality: { display_name: "Draft" },
      business_info: { business: { name: "Draft business" } },
      actions_definition: { actions: { new: {} } },
      architecture: { architecture_key: "cascade" },
      profile_reference: { profile_key: "hotel" },
      runtime_overrides: { tts: { voice_id: "voice-1" } },
      actions_availability: { actions: { new: true } },
    });
  });
});

describe.each([
  [
    "System",
    () => <SystemConfigurationEditor />,
    "/management/v1/system/configuration",
  ],
  [
    "Platform",
    () => <PlatformConfigurationEditor />,
    "/management/v1/platform/configuration",
  ],
  [
    "Tenant",
    () => <TenantConfigurationEditor tenantId="tenant-1" />,
    "/management/v1/tenants/tenant-1/configuration",
  ],
] as const)("%s configuration editor", (name, editor, path) => {
  it("renders an uninitialized state with plan and apply available", async () => {
    server.use(
      http.get(path, () =>
        HttpResponse.json(
          errorResponse("configuration_not_initialized", "Not initialized"),
          {
            status: 404,
          },
        ),
      ),
    );

    render(<AppProviders>{editor()}</AppProviders>);

    expect(await screen.findByText("Not initialized")).toBeVisible();
    expect(screen.getByRole("button", { name: "Plan" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Apply" })).toBeEnabled();
    if (name !== "System")
      expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
    expect(
      screen.queryByText(`${name} configuration could not be loaded`),
    ).not.toBeInTheDocument();
  });
});

it("plans before initialization and applies with If-None-Match, then refetches", async () => {
  const user = userEvent.setup();
  let initialized = false;
  let getCount = 0;
  let applyHeaders: Headers | undefined;
  let planBody: unknown;

  server.use(
    http.get("/management/v1/system/configuration", () => {
      getCount += 1;
      return initialized
        ? HttpResponse.json(systemConfiguration, {
            headers: { ETag: '"etag-2"' },
          })
        : HttpResponse.json(
            errorResponse("configuration_not_initialized", "Not initialized"),
            { status: 404 },
          );
    }),
    http.post(
      "/management/v1/system/configuration/plan",
      async ({ request }) => {
        planBody = await request.json();
        return HttpResponse.json({
          valid: true,
          changes: [],
          warnings: [],
          errors: [],
        });
      },
    ),
    http.put("/management/v1/system/configuration", ({ request }) => {
      applyHeaders = request.headers;
      initialized = true;
      return HttpResponse.json(
        { configuration: systemConfiguration, updated: [], unchanged: [] },
        { headers: { ETag: '"etag-2"' } },
      );
    }),
  );

  render(
    <AppProviders>
      <SystemConfigurationEditor />
    </AppProviders>,
  );
  await screen.findByText("Not initialized");
  await user.click(screen.getByRole("button", { name: "Plan" }));
  await screen.findByText(/valid:/);
  await user.click(screen.getByRole("button", { name: "Apply" }));

  await waitFor(() => expect(screen.getByText("Initialized")).toBeVisible());
  expect(planBody).toEqual({});
  expect(applyHeaders?.get("if-none-match")).toBe("*");
  expect(applyHeaders?.get("if-match")).toBeNull();
  expect(applyHeaders?.get("idempotency-key")).toBeTruthy();
  expect(getCount).toBe(2);
});

it("applies an initialized platform with its ETag and does not send If-None-Match", async () => {
  const user = userEvent.setup();
  let applyHeaders: Headers | undefined;
  let getCount = 0;
  server.use(
    http.get("/management/v1/platform/configuration", () => {
      getCount += 1;
      return HttpResponse.json(platformConfiguration, {
        headers: { ETag: '"platform-etag"' },
      });
    }),
    http.put("/management/v1/platform/configuration", ({ request }) => {
      applyHeaders = request.headers;
      return HttpResponse.json({
        configuration: platformConfiguration,
        catalogs_updated: [],
        drafts_saved: [],
        unchanged: [],
      });
    }),
  );

  render(
    <AppProviders>
      <PlatformConfigurationEditor />
    </AppProviders>,
  );
  const editor = await screen.findByRole("textbox");
  await user.clear(editor);
  fireEvent.change(editor, { target: { value: "{}" } });
  await user.click(screen.getByRole("button", { name: "Apply" }));

  await waitFor(() => expect(getCount).toBe(2));
  expect(applyHeaders?.get("if-match")).toBe('"platform-etag"');
  expect(applyHeaders?.get("if-none-match")).toBeNull();
  expect(applyHeaders?.get("idempotency-key")).toBeTruthy();
});

it("publishes a tenant once with the current ETag and refetches", async () => {
  const user = userEvent.setup();
  let publishHeaders: Headers | undefined;
  let publishCount = 0;
  let getCount = 0;
  server.use(
    http.get("/management/v1/tenants/tenant-1/configuration", () => {
      getCount += 1;
      return HttpResponse.json(tenantConfiguration, {
        headers: { ETag: '"tenant-etag"' },
      });
    }),
    http.post(
      "/management/v1/tenants/tenant-1/configuration/publish",
      ({ request }) => {
        publishCount += 1;
        publishHeaders = request.headers;
        return HttpResponse.json({
          configuration: tenantConfiguration,
          published_components: [],
          unchanged_components: [],
        });
      },
    ),
  );

  render(
    <AppProviders>
      <TenantConfigurationEditor tenantId="tenant-1" />
    </AppProviders>,
  );
  await screen.findByRole("button", { name: "Publish" });
  await user.click(screen.getByRole("button", { name: "Publish" }));

  await waitFor(() => expect(getCount).toBe(2));
  expect(publishCount).toBe(1);
  expect(publishHeaders?.get("if-match")).toBe('"tenant-etag"');
  expect(publishHeaders?.get("idempotency-key")).toBeTruthy();
});

it("publishes a platform once with the current ETag", async () => {
  const user = userEvent.setup();
  let publishHeaders: Headers | undefined;
  let publishCount = 0;
  server.use(
    http.get("/management/v1/platform/configuration", () =>
      HttpResponse.json(platformConfiguration, {
        headers: { ETag: '"platform-etag"' },
      }),
    ),
    http.post(
      "/management/v1/platform/configuration/publish",
      ({ request }) => {
        publishCount += 1;
        publishHeaders = request.headers;
        return HttpResponse.json({
          configuration: platformConfiguration,
          published_components: [],
          unchanged_components: [],
        });
      },
    ),
  );

  render(
    <AppProviders>
      <PlatformConfigurationEditor />
    </AppProviders>,
  );
  const publish = await screen.findByRole("button", { name: "Publish" });
  await user.click(publish);

  await waitFor(() => expect(publishCount).toBe(1));
  expect(publishHeaders?.get("if-match")).toBe('"platform-etag"');
  expect(publishHeaders?.get("idempotency-key")).toBeTruthy();
});

it("renders structured stale-state errors and preserves editor contents", async () => {
  const user = userEvent.setup();
  server.use(
    http.get("/management/v1/system/configuration", () =>
      HttpResponse.json(systemConfiguration, {
        headers: { ETag: '"stale-etag"' },
      }),
    ),
    http.put("/management/v1/system/configuration", () =>
      HttpResponse.json(
        errorResponse("stale_etag", "The configuration changed on the server."),
        { status: 412 },
      ),
    ),
  );

  render(
    <AppProviders>
      <SystemConfigurationEditor />
    </AppProviders>,
  );
  const editor = await screen.findByRole("textbox");
  await user.clear(editor);
  fireEvent.change(editor, { target: { value: '{"user_edit":true}' } });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Apply" })).toBeEnabled(),
  );
  await user.click(screen.getByRole("button", { name: "Apply" }));

  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Apply" })).toBeEnabled(),
  );
  await waitFor(() =>
    expect(document.body.textContent).toContain(
      "System Configuration change failed",
    ),
  );
  expect(
    await screen.findByText("The configuration changed on the server."),
  ).toBeVisible();
  expect(screen.getByText(/stale_etag/)).toBeVisible();
  expect(screen.getByText(/llm_defaults/)).toBeVisible();
  expect(screen.getByText(/request-1/)).toBeVisible();
  expect(editor).toHaveValue('{"user_edit":true}');
  expect(screen.getByRole("button", { name: "Reload" })).toBeEnabled();
});
