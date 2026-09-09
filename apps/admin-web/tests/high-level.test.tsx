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

function fillRequiredSystemFields() {
  for (let pass = 0; pass < 3; pass += 1) {
    for (const control of Array.from(document.querySelectorAll("[required]"))) {
      if (control instanceof HTMLSelectElement) {
        const option = Array.from(control.options).find(
          ({ value }) => value !== "",
        );
        if (option)
          fireEvent.change(control, { target: { value: option.value } });
      } else if (control instanceof HTMLInputElement) {
        fireEvent.change(control, {
          target: {
            value: control.type === "number" ? control.min || "1" : "value",
          },
        });
      }
    }
  }
}

const systemConfiguration = {
  stt_defaults: { deployment_ref: "stt-id" },
  llm_defaults: {
    deployment_ref: "llm-id",
    max_completion_tokens: 100,
    temperature: null,
    reasoning_effort: null,
  },
  tts_defaults: { deployment_ref: "tts-id", default_voice_id: "voice" },
  realtime_defaults: {
    deployment_ref: "realtime-id",
    input_transcription: { deployment_ref: "stt-id" },
    default_voice: "marin",
    turn_completion: {
      strategy: "server_vad",
      activation_threshold: 0.5,
      silence_duration_ms: 200,
    },
    interruption: { enabled: true },
  },
  policies: {
    cascade: {
      speech_activity: {
        min_speech_seconds: 0.1,
        min_silence_seconds: 0.2,
        activation_threshold: 0.5,
      },
      stt_commit: { strategy: "local_vad" },
      endpointing: { min_delay_seconds: 0.1, max_delay_seconds: 1 },
      interruption: {
        enabled: true,
        min_duration_seconds: 0.1,
        min_words: 1,
        false_interruption_timeout_seconds: 0.5,
        resume_after_false_interruption: true,
      },
      response_scheduling: {
        preemptive_generation: false,
        preemptive_tts: false,
      },
      tokenizer: { min_sentence_chars: 20 },
    },
  },
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
      active: {
        identity: "active_agent",
        display_name: "Active",
        greeting: "Hello",
        conversation_scope: "property_only",
      },
      draft: {
        identity: "draft_agent",
        display_name: "Draft",
        greeting: "Hi",
        conversation_scope: "property_only",
      },
    },
    business_info: {
      active: {
        business: { name: "Active business", type: "hotel" },
        contact: { address: null, phones: [], emails: [], website: null },
        localization: { default_locale: "en-US", timezone: "UTC" },
      },
      draft: {
        business: { name: "Draft business", type: "hotel" },
        contact: { address: null, phones: [], emails: [], website: null },
        localization: { default_locale: "en-US", timezone: "UTC" },
      },
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
      agent_personality: {
        identity: "draft_agent",
        display_name: "Draft",
        greeting: "Hi",
        conversation_scope: "property_only",
      },
      business_info: {
        business: { name: "Draft business", type: "hotel" },
        contact: { address: null, phones: [], emails: [], website: null },
        localization: { default_locale: "en-US", timezone: "UTC" },
      },
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
  await screen.findAllByRole("option", { name: "speech (stt)" });
  fillRequiredSystemFields();
  await user.click(screen.getByRole("button", { name: "Plan" }));
  await screen.findByText("Plan valid");
  await user.click(screen.getByRole("button", { name: "Apply" }));

  await waitFor(() => expect(screen.getByText("Initialized")).toBeVisible());
  expect(planBody).toEqual(
    expect.objectContaining({
      stt_defaults: { deployment_ref: "stt-uuid" },
      llm_defaults: expect.objectContaining({ deployment_ref: "llm-uuid" }),
      tts_defaults: expect.objectContaining({ deployment_ref: "tts-uuid" }),
      realtime_defaults: expect.objectContaining({
        deployment_ref: "realtime-uuid",
        input_transcription: { deployment_ref: "stt-uuid" },
      }),
    }),
  );
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
  const editor = await screen.findByLabelText("Content");
  await user.clear(editor);
  await user.type(editor, "changed system prompt");
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
  const editor = await screen.findByLabelText("Default voice");
  await user.clear(editor);
  await user.type(editor, "edited voice");
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
  expect(editor).toHaveValue("edited voice");
  expect(screen.getByRole("button", { name: "Reload" })).toBeEnabled();
});
