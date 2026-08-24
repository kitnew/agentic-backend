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
  active_release_id: "published",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};
const platformState = {
  runtime_draft: null,
  system_prompt_draft: { id: "system", version: 1, value: "System" },
  profile_prompt_drafts: {},
  active_release: {
    id: "release",
    release_number: 1,
    runtime_revision_id: "runtime",
    system_prompt_revision_id: "system",
  },
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
      http.get("/admin/v1/platform/telephony", () =>
        HttpResponse.json({
          provider: "configuration_required",
          inbound: "pending",
          outbound: "pending",
          dispatch: "pending",
          overall: "degraded",
          last_error: "SIP provider connection is not configured",
          last_reconciled_at: null,
          diagnostics: {},
        }),
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
    ).toEqual([
      "Overview",
      "Runtime",
      "System Prompt",
      "Profiles",
      "Telephony",
    ]);
    await user.click(
      await screen.findByRole("button", { name: "Publish Platform" }),
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
      http.post(
        `/admin/v1/tenants/${tenantId}/components/publish-all`,
        async ({ request }) => {
          expect(await request.json()).toEqual({
            drafts: [
              { component: "agent", draft_id: "agent-draft", version: 1 },
            ],
          });
          publish();
          return HttpResponse.json({ id: "release", release_number: 1 });
        },
      ),
    );
    window.history.pushState({}, "", "/");
    render(<App />);
    await user.click(screen.getByRole("link", { name: "Tenants" }));
    await user.click(await screen.findByRole("link", { name: /Demo tenant/ }));
    expect(await screen.findByText("1 saved draft")).toBeVisible();
    await user.click(
      screen.getAllByRole("button", { name: "Publish Tenant" })[0],
    );
    expect(publish).toHaveBeenCalledOnce();
  });

  it("publishes saved drafts from all seven component metadata endpoints", async () => {
    const user = userEvent.setup();
    const publish = vi.fn();
    const components = [
      "runtime",
      "agent",
      "prompt",
      "knowledge",
      "capabilities",
      "post_call",
      "telephony",
    ];
    server.use(
      http.get("/admin/v1/tenants", () => HttpResponse.json([tenant])),
      http.get(
        `/admin/v1/tenants/${tenantId}/components/:component`,
        ({ params }) =>
          HttpResponse.json(componentState(params.component as string, true)),
      ),
      http.post(
        `/admin/v1/tenants/${tenantId}/components/publish-all`,
        async ({ request }) => {
          expect(await request.json()).toEqual({
            drafts: components.map((component) => ({
              component,
              draft_id: `${component}-draft`,
              version: 1,
            })),
          });
          publish();
          return HttpResponse.json({ id: "release", release_number: 1 });
        },
      ),
    );
    window.history.pushState({}, "", "/");
    render(<App />);
    await user.click(screen.getByRole("link", { name: "Tenants" }));
    await user.click(await screen.findByRole("link", { name: /Demo tenant/ }));
    expect(await screen.findByText("7 saved drafts")).toBeVisible();
    await user.click(
      await screen.findByRole("button", { name: "Publish Tenant" }),
    );
    expect(publish).toHaveBeenCalledOnce();
  });

  it("refreshes the tenant draft snapshot before publishing", async () => {
    const user = userEvent.setup();
    const publish = vi.fn();
    let componentReads = 0;
    server.use(
      http.get("/admin/v1/tenants", () => HttpResponse.json([tenant])),
      http.get(
        `/admin/v1/tenants/${tenantId}/components/:component`,
        ({ params }) => {
          const initial = componentReads < 7;
          componentReads += 1;
          const component = params.component as string;
          return HttpResponse.json(
            componentState(
              component,
              initial
                ? component === "agent"
                : ["agent", "knowledge"].includes(component),
            ),
          );
        },
      ),
      http.post(
        `/admin/v1/tenants/${tenantId}/components/publish-all`,
        async ({ request }) => {
          expect(await request.json()).toEqual({
            drafts: [
              { component: "agent", draft_id: "agent-draft", version: 1 },
              {
                component: "knowledge",
                draft_id: "knowledge-draft",
                version: 1,
              },
            ],
          });
          publish();
          return HttpResponse.json({ id: "release", release_number: 1 });
        },
      ),
    );
    window.history.pushState({}, "", "/");
    render(<App />);
    await user.click(screen.getByRole("link", { name: "Tenants" }));
    await user.click(await screen.findByRole("link", { name: /Demo tenant/ }));
    expect(await screen.findByText("1 saved draft")).toBeVisible();
    await user.click(
      await screen.findByRole("button", { name: "Publish Tenant" }),
    );
    expect(publish).toHaveBeenCalledOnce();
    expect(await screen.findByText("2 saved drafts")).toBeVisible();
  });
});
