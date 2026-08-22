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
      contact: { emails: ["one@example.com", "two@example.com"] },
    });
  });
});
