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
const platformState = {
  runtime_draft: null,
  system_prompt_draft: { id: "system", version: 1, value: "System" },
  profile_prompt_drafts: {},
  active_release: null,
  active_runtime: null,
  active_system_prompt: null,
  active_profile_prompts: {},
};

const componentState = (component: string, draft = false) => ({
  component,
  draft: draft
    ? {
        id: `${component}-draft`,
        component,
        payload: {},
        version: 1,
        comment: null,
        updated_at: "2026-01-01T00:00:00Z",
      }
    : null,
  active_revision: null,
});

describe("workspace overviews", () => {
  it("renders Platform secondary navigation and requests one aggregate publish", async () => {
    const user = userEvent.setup();
    const publish = vi.fn();
    server.use(
      http.get("/admin/v1/tenants", () => HttpResponse.json([tenant])),
      http.get("/admin/v1/platform/components/state", () =>
        HttpResponse.json(platformState),
      ),
      http.post("/admin/v1/platform/components/publish", () => {
        publish();
        return HttpResponse.json({ id: "release", release_number: 1 });
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
      http.get(
        `/admin/v1/tenants/${tenantId}/components/:component`,
        ({ params }) =>
          HttpResponse.json(
            componentState(
              params.component as string,
              params.component === "agent",
            ),
          ),
      ),
      http.post(`/admin/v1/tenants/${tenantId}/components/publish-all`, () => {
        publish();
        return HttpResponse.json({ id: "release", release_number: 1 });
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
