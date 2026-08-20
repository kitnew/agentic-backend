import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { App } from "../src/app/app";
import { server } from "./setup";

const tenant = {
  id: "11111111-1111-4111-8111-111111111111",
  slug: "demo",
  display_name: "Demo tenant",
  business_type: "hotel",
  status: "active",
  active_config_revision_id: null,
  active_prompt_set_revision_id: null,
  active_voice_runtime_revision_id: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("Admin app shell", () => {
  it("renders exactly four product navigation items and tenant cards without UUID copy", async () => {
    server.use(
      http.get("/admin/v1/tenants", () => HttpResponse.json([tenant])),
    );
    window.history.pushState({}, "", "/");
    render(<App />);
    const navigation = await screen.findByRole("navigation", {
      name: "Main navigation",
    });
    expect(within(navigation).getAllByRole("link")).toHaveLength(4);
    expect(
      within(navigation).getByRole("link", { name: "Overview" }),
    ).toBeVisible();
    expect(
      within(navigation).getByRole("link", { name: "Platform" }),
    ).toBeVisible();
    expect(
      within(navigation).getByRole("link", { name: "Tenants" }),
    ).toBeVisible();
    expect(
      within(navigation).getByRole("link", { name: "Observability ↗" }),
    ).toHaveAttribute("target", "_blank");
    expect(
      await screen.findByRole("heading", { name: "Demo tenant" }),
    ).toBeVisible();
    expect(screen.queryByText(tenant.id)).not.toBeInTheDocument();
    expect(screen.queryByText("Example")).not.toBeInTheDocument();
    expect(screen.queryByText("Admin Web V0")).not.toBeInTheDocument();
  });

  it("renders the exact tenant secondary navigation", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/admin/v1/tenants", () => HttpResponse.json([tenant])),
      http.get(`/admin/v1/tenants/${tenant.id}/config/revisions`, () =>
        HttpResponse.json([]),
      ),
      http.get(`/admin/v1/tenants/${tenant.id}/tenant-prompt/revisions`, () =>
        HttpResponse.json([]),
      ),
      http.get(`/admin/v1/tenants/${tenant.id}/runtime`, () =>
        HttpResponse.json({
          draft_revision: null,
          latest_published_revision: null,
        }),
      ),
      http.get(`/admin/v1/tenants/${tenant.id}/knowledge-base`, () =>
        HttpResponse.json({
          tenant_id: tenant.id,
          draft_revision: null,
          latest_published_revision: null,
          published_documents: [],
        }),
      ),
    );
    window.history.pushState({}, "", "/");
    render(<App />);
    await user.click(await screen.findByRole("link", { name: /Demo tenant/ }));
    const navigation = await screen.findByRole("navigation", {
      name: "Tenant navigation",
    });
    expect(
      within(navigation)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual([
      "Runtime",
      "Agent",
      "Prompt",
      "Knowledge Base",
      "Capabilities",
      "Playground",
    ]);
    expect(screen.getByText("Demo tenant", { selector: "a" })).toBeVisible();
    expect(screen.queryByText(tenant.id)).not.toBeInTheDocument();
  });
});
