import { describe, expect, it } from "vitest";

import {
  enabledCapabilities,
  toAgentForm,
  toUpdateRequest,
} from "../src/features/agent/lib/mappings";
import { agentFormSchema } from "../src/features/agent/schemas/agent-form";

const config = {
  schema_version: 4 as const,
  agent: {
    display_name: "Amelia",
    greeting: "Hello",
    profile: "hotel_assistant",
  },
  business: { name: "Debug Hotel", type: "hotel" },
  conversation: { scope: "property_only" as const },
  localization: { default_locale: "sk-SK", timezone: "Europe/Bratislava" },
  capabilities: { enabled: true, disabled: false },
};

describe("agent form mappings", () => {
  it("maps editable fields without discarding the rest of the configuration", () => {
    const form = toAgentForm(config, "Be helpful.", {
      draft_revision: null,
      latest_published_revision: null,
    });
    const update = toUpdateRequest(config, {
      ...form,
      displayName: "Updated",
      voiceId: "voice",
    });
    expect(update.config).toMatchObject({
      agent: { display_name: "Updated" },
      business: config.business,
    });
    expect(enabledCapabilities(config)).toEqual(["enabled"]);
  });

  it("validates required fields and locale format", () => {
    expect(
      agentFormSchema.safeParse({
        displayName: "",
        greeting: "",
        profile: "",
        defaultLocale: "sk",
        tenantInstructions: "",
        voiceId: "",
      }).success,
    ).toBe(false);
    expect(
      agentFormSchema.safeParse({
        displayName: "Amelia",
        greeting: "Hello",
        profile: "hotel_assistant",
        defaultLocale: "sk-SK",
        tenantInstructions: "Be helpful.",
        voiceId: "",
      }).success,
    ).toBe(true);
  });
});
