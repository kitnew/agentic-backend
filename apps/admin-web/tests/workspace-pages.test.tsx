import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { App } from "../src/app/app";
import { server } from "./setup";

const tenantId = "11111111-1111-4111-8111-111111111111";
const tenant = {
  id: tenantId,
  slug: "demo",
  display_name: "Demo tenant",
  business_type: "hotel",
  status: "active",
  active_config_revision_id: "published",
  active_prompt_set_revision_id: "prompt-set",
  active_voice_runtime_revision_id: "voice",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};
const prompt = (status: string) => ({
  id: `${status}-prompt`,
  text: "Prompt",
  status,
  version: 1,
  revision_number: 1,
  created_at: "2026-01-01T00:00:00Z",
  published_at: status === "draft" ? null : "2026-01-01T00:00:00Z",
});

describe("workspace overviews", () => {
  it("renders Platform secondary navigation and requests one aggregate publish", async () => {
    const user = userEvent.setup();
    const publish = vi.fn();
    server.use(
      http.get("/admin/v1/tenants", () => HttpResponse.json([tenant])),
      http.get("/admin/v1/platform/runtime", () =>
        HttpResponse.json({
          draft_revision: null,
          latest_published_revision: {
            id: "runtime",
            policy: {},
            status: "published",
            version: 1,
          },
        }),
      ),
      http.get("/admin/v1/platform/prompts/profiles", () =>
        HttpResponse.json(["hotel_assistant"]),
      ),
      http.get("/admin/v1/platform/prompts/system/default/revisions", () =>
        HttpResponse.json([prompt("draft"), prompt("published")]),
      ),
      http.get(
        "/admin/v1/platform/prompts/profiles/hotel_assistant/revisions",
        () => HttpResponse.json([prompt("published")]),
      ),
      http.post("/admin/v1/platform/publish-all", () => {
        publish();
        return HttpResponse.json({ published_sections: ["system_prompt"] });
      }),
    );
    window.history.pushState({}, "", "/");
    render(<App />);
    await user.click(await screen.findByRole("link", { name: "Platform" }));
    const navigation = await screen.findByRole("navigation", {
      name: "Platform navigation",
    });
    expect(
      within(navigation)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["Runtime", "Telephony", "System Prompt", "Profile Prompt"]);
    await user.click(
      await screen.findByRole("button", { name: "Publish All" }),
    );
    expect(publish).toHaveBeenCalledOnce();
  });

  it("requests one aggregate tenant publish for all saved sections", async () => {
    const user = userEvent.setup();
    const publish = vi.fn();
    server.use(
      http.get("/admin/v1/tenants", () => HttpResponse.json([tenant])),
      http.get(`/admin/v1/tenants/${tenantId}/config/revisions`, () =>
        HttpResponse.json([{ status: "draft" }]),
      ),
      http.get(`/admin/v1/tenants/${tenantId}/tenant-prompt/revisions`, () =>
        HttpResponse.json([]),
      ),
      http.get(`/admin/v1/tenants/${tenantId}/runtime`, () =>
        HttpResponse.json({
          draft_revision: null,
          latest_published_revision: null,
        }),
      ),
      http.get(`/admin/v1/tenants/${tenantId}/knowledge-base`, () =>
        HttpResponse.json({
          tenant_id: tenantId,
          draft_revision: null,
          latest_published_revision: null,
          published_documents: [],
        }),
      ),
      http.post(`/admin/v1/tenants/${tenantId}/publish-all`, () => {
        publish();
        return HttpResponse.json({ published_sections: ["agent"] });
      }),
    );
    window.history.pushState({}, "", "/");
    render(<App />);
    await user.click(screen.getByRole("link", { name: "Tenants" }));
    await user.click(await screen.findByRole("link", { name: /Demo tenant/ }));
    expect(await screen.findByText("1 unpublished section")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Publish All" }));
    expect(publish).toHaveBeenCalledOnce();
  });
});
