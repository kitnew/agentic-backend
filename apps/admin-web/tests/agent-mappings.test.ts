import { describe, expect, it } from "vitest";

import {
  toAgentForm,
  toUpdateRequest,
} from "../src/features/agent/lib/mappings";

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
  capabilities: { enabled: true },
  contact: {
    address: "Main street",
    emails: ["hello@example.com"],
    phones: ["+421900000000"],
    website: "https://example.com",
  },
  handoff: {
    destinations: {
      reception: { description: "Reception", phone_number: "+421900000001" },
    },
  },
};

describe("agent form mappings", () => {
  it("maps structured contact without discarding telephony-owned legacy data", () => {
    const form = toAgentForm(config);
    const update = toUpdateRequest(config, {
      ...form,
      displayName: "Updated",
      emails: "one@example.com\ntwo@example.com",
    });
    expect(update.config).toMatchObject({
      agent: { display_name: "Updated" },
      business: config.business,
      contact: { emails: ["one@example.com", "two@example.com"] },
      handoff: {
        destinations: { reception: { phone_number: "+421900000001" } },
      },
    });
  });
});
