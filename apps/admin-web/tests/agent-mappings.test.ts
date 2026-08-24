import { describe, expect, it } from "vitest";

import {
  toAgentForm,
  toAgentPayload,
} from "../src/features/agent/lib/mappings";

const config = {
  agent: {
    display_name: "Amelia",
    greeting: "Hello",
    profile: "hotel_assistant",
  },
  business: { name: "Debug Hotel", type: "hotel" },
  conversation: { scope: "property_only" as const },
  localization: { default_locale: "sk-SK", timezone: "Europe/Bratislava" },
  contact: {
    address: "Main street",
    emails: ["hello@example.com"],
    phones: ["+421900000000"],
    website: "https://example.com",
  },
  handoff: {
    destinations: {
      reception: {
        description: "Reception",
        phone_number: "+421900000001",
      },
    },
  },
};

describe("agent form mappings", () => {
  it("maps structured contact without crossing component ownership", () => {
    const form = toAgentForm(config);
    const update = toAgentPayload(config, {
      ...form,
      displayName: "Updated",
      emails: "one@example.com\ntwo@example.com",
    });
    expect(update).toMatchObject({
      agent: { display_name: "Updated" },
      business: config.business,
      conversation: config.conversation,
      localization: config.localization,
      handoff: config.handoff,
      contact: { emails: ["one@example.com", "two@example.com"] },
    });
  });

  it("maps and edits localization and multiple handoff destinations", () => {
    const form = toAgentForm(config);
    expect(form.defaultLocale).toBe("sk-SK");
    expect(form.timezone).toBe("Europe/Bratislava");
    expect(form.handoffDestinations).toEqual([
      {
        id: "reception",
        key: "reception",
        description: "Reception",
        phoneNumber: "+421900000001",
      },
    ]);
    const update = toAgentPayload(config, {
      ...form,
      defaultLocale: "en-US",
      timezone: "UTC",
      handoffDestinations: [
        ...form.handoffDestinations,
        {
          id: "manager",
          key: "manager",
          description: "Manager",
          phoneNumber: "+421900000002",
        },
      ],
    });
    expect(update.localization).toEqual({
      default_locale: "en-US",
      timezone: "UTC",
    });
    expect(update.handoff?.destinations).toEqual({
      reception: {
        description: "Reception",
        phone_number: "+421900000001",
      },
      manager: {
        description: "Manager",
        phone_number: "+421900000002",
      },
    });
  });

  it("maps empty optional contact and handoff values without dirty-side effects", () => {
    const form = toAgentForm({
      ...config,
      contact: undefined,
      handoff: undefined,
    });
    expect(form.address).toBe("");
    expect(form.emails).toBe("");
    expect(form.handoffDestinations).toEqual([]);
  });
});
