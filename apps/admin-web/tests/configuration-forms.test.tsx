import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { AppProviders } from "../src/app/providers";
import type { SystemConfigurationDesired } from "../src/core/api/control-plane";
import {
  emptyPlatformFormState,
  emptySystemFormState,
  emptyTenantFormState,
  PlatformConfigurationForm,
  platformDesiredFromForm,
  SystemConfigurationForm,
  systemDesiredFromForm,
  systemFormState,
  tenantDesiredFromForm,
  tenantFormState,
} from "../src/core/configuration/forms";

const completeSystemDesired = {
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
      strategy: "semantic_vad",
      eagerness: "medium",
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
      stt_commit: {
        strategy: "provider_vad",
        provider_vad: {
          threshold: 0.5,
          silence_threshold_seconds: 1,
          min_speech_ms: 100,
          min_silence_ms: 200,
        },
      },
      endpointing: { min_delay_seconds: 0.1, max_delay_seconds: 1 },
      interruption: {
        enabled: true,
        min_duration_seconds: 0.1,
        min_words: 1,
        false_interruption_timeout_seconds: 0.5,
        resume_after_false_interruption: true,
      },
      response_scheduling: {
        preemptive_generation: true,
        preemptive_tts: false,
      },
      tokenizer: { min_sentence_chars: 20 },
    },
  },
} as SystemConfigurationDesired;

function SystemFormHarness({
  errors = {},
}: {
  errors?: Record<string, string>;
}) {
  const [value, setValue] = useState(emptySystemFormState());
  return (
    <SystemConfigurationForm
      errors={errors}
      value={value}
      onChange={setValue}
    />
  );
}

function ExistingPlatformFormHarness() {
  const [value, setValue] = useState(() => {
    const form = emptyPlatformFormState();
    form.profiles.push({
      key: "hotel",
      name: "Hotel",
      description: "",
      status: "enabled",
      prompt: "Prompt",
      existing: true,
    });
    return form;
  });
  return <PlatformConfigurationForm value={value} onChange={setValue} />;
}

describe("configuration form mappings", () => {
  it("round-trips the complete system desired DTO", () => {
    expect(
      systemDesiredFromForm(systemFormState(completeSystemDesired)),
    ).toEqual(completeSystemDesired);
  });

  it("renders deployment UUIDs and switches conditional VAD fields", async () => {
    const user = userEvent.setup();
    render(
      <AppProviders>
        <SystemFormHarness />
      </AppProviders>,
    );
    await screen.findAllByRole("option", { name: "speech (stt)" });
    expect(screen.getAllByLabelText("Deployment")).toHaveLength(4);
    expect(
      screen
        .getAllByLabelText("Deployment")
        .every((element) => (element as HTMLSelectElement).value === ""),
    ).toBe(true);
    expect(screen.getByLabelText("Input transcription")).toHaveValue("");

    expect(
      systemDesiredFromForm({
        ...emptySystemFormState(),
        stt_defaults: { deployment_ref: "stt-uuid" },
      }).stt_defaults.deployment_ref,
    ).toBe("stt-uuid");
    const turnStrategy = screen.getByLabelText("Turn completion strategy");
    expect(screen.getAllByLabelText("Activation threshold")).toHaveLength(1);
    await user.selectOptions(turnStrategy, "server_vad");
    expect(screen.getAllByLabelText("Activation threshold")).toHaveLength(2);
    expect(screen.queryByLabelText("Eagerness")).not.toBeInTheDocument();
    await user.selectOptions(turnStrategy, "semantic_vad");
    expect(screen.getByLabelText("Eagerness")).toBeVisible();
    expect(
      screen.queryByLabelText("Silence duration (ms)"),
    ).not.toBeInTheDocument();

    const commitStrategy = screen.getByLabelText("Strategy");
    await user.selectOptions(commitStrategy, "provider_vad");
    expect(screen.getByLabelText("Threshold")).toBeVisible();
    await user.selectOptions(commitStrategy, "local_vad");
    expect(screen.queryByLabelText("Threshold")).not.toBeInTheDocument();
  });

  it("renders a direct validation issue beside its field", () => {
    render(
      <AppProviders>
        <SystemFormHarness
          errors={{ "llm_defaults.max_completion_tokens": "Must be positive" }}
        />
      </AppProviders>,
    );
    expect(screen.getByText("Must be positive")).toBeVisible();
  });

  it("keeps existing catalog keys read-only and adds removable local entries", async () => {
    const user = userEvent.setup();
    render(
      <AppProviders>
        <ExistingPlatformFormHarness />
      </AppProviders>,
    );
    expect(screen.getByLabelText("Key")).toHaveAttribute("readonly");
    await user.click(screen.getByRole("button", { name: "Add profile" }));
    expect(screen.getAllByLabelText("Key")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Remove" })).toBeVisible();
  });

  it("maps system blank numeric values to the documented null/default forms", () => {
    const value = systemDesiredFromForm(emptySystemFormState());

    expect(value.llm_defaults.temperature).toBeNull();
    expect(value.llm_defaults.reasoning_effort).toBeNull();
    expect(value.realtime_defaults.default_voice).toBe("marin");
    expect(value.realtime_defaults.interruption.enabled).toBe(true);
    expect(value.realtime_defaults.turn_completion).toEqual({ strategy: "" });
    expect(value.policies.cascade.stt_commit).toEqual({ strategy: "" });
  });

  it("maps the exact system cascade branches", () => {
    const form = emptySystemFormState();
    form.stt_defaults.deployment_ref = "stt-id";
    form.llm_defaults.deployment_ref = "llm-id";
    form.llm_defaults.max_completion_tokens = "100";
    form.tts_defaults.deployment_ref = "tts-id";
    form.tts_defaults.default_voice_id = "voice";
    form.realtime_defaults.deployment_ref = "realtime-id";
    form.realtime_defaults.input_transcription.deployment_ref =
      "transcription-id";
    form.policies.cascade.stt_commit.strategy = "provider_vad";
    form.policies.cascade.stt_commit.provider_vad.threshold = "0.5";
    form.policies.cascade.stt_commit.provider_vad.silence_threshold_seconds =
      "1";
    form.policies.cascade.stt_commit.provider_vad.min_speech_ms = "100";
    form.policies.cascade.stt_commit.provider_vad.min_silence_ms = "200";

    expect(systemDesiredFromForm(form)).toMatchObject({
      stt_defaults: { deployment_ref: "stt-id" },
      llm_defaults: {
        deployment_ref: "llm-id",
        max_completion_tokens: 100,
      },
      tts_defaults: { deployment_ref: "tts-id", default_voice_id: "voice" },
      realtime_defaults: {
        deployment_ref: "realtime-id",
        input_transcription: { deployment_ref: "transcription-id" },
      },
      policies: {
        cascade: {
          stt_commit: {
            strategy: "provider_vad",
            provider_vad: {
              threshold: 0.5,
              min_speech_ms: 100,
              min_silence_ms: 200,
            },
          },
        },
      },
    });
  });

  it("uses draft values and keeps platform profiles editable locally", () => {
    const form = emptyPlatformFormState();
    form.system_prompt = "system";
    form.profiles.push({
      key: "hotel",
      name: "Hotel",
      description: "Hotel profile",
      status: "enabled",
      prompt: "profile prompt",
      existing: false,
    });
    form.interaction_modes.push({
      key: "friendly",
      name: "",
      description: "",
      status: "enabled",
      prompt: "",
      existing: false,
    });

    expect(platformDesiredFromForm(form)).toEqual({
      system_prompt: { content: "system" },
      profiles: [
        {
          key: "hotel",
          name: "Hotel",
          description: "Hotel profile",
          status: "enabled",
          prompt: { content: "profile prompt" },
        },
      ],
      interaction_modes: [
        {
          key: "friendly",
          name: "",
          description: "",
          status: "enabled",
          prompt: { content: "" },
        },
      ],
    });
  });

  it("preserves tenant override omission versus an explicit empty keyterm set", () => {
    const form = emptyTenantFormState();
    expect(tenantDesiredFromForm(form).runtime_overrides).toEqual({});

    form.stt_keyterms_override = true;
    expect(tenantDesiredFromForm(form).runtime_overrides).toEqual({
      stt: { keyterms: [] },
    });
  });

  it("maps tenant business lines, actions, and draft values", () => {
    const desired = tenantDesiredFromForm({
      ...emptyTenantFormState(),
      identity: "assistant",
      display_name: "Assistant",
      greeting: "Hello",
      business_name: "Hotel",
      business_type: "hotel",
      phones: "+421 1\n\n+421 2",
      emails: "a@example.com\n b@example.com ",
      default_locale: "sk-SK",
      timezone: "Europe/Bratislava",
      tenant_prompt: "Tenant prompt",
      knowledge: "Knowledge",
      actions_definition: '{"actions":{}}',
      actions_availability: '{"actions":{}}',
      architecture_key: "cascade",
      profile_key: "hotel",
    });

    expect(desired.business_info).toEqual({
      business: { name: "Hotel", type: "hotel" },
      contact: {
        address: null,
        emails: ["a@example.com", "b@example.com"],
        phones: ["+421 1", "+421 2"],
        website: null,
      },
      localization: { default_locale: "sk-SK", timezone: "Europe/Bratislava" },
    });
    expect(desired.actions_definition).toEqual({ actions: {} });
    expect(tenantFormState(desired).conversation_scope).toBe("property_only");
  });
});
