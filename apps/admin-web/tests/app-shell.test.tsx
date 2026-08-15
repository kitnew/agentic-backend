import { render, screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { App } from "../src/app/app";
import { server } from "./setup";

const tenant = {
  id: "11111111-1111-4111-8111-111111111111",
  slug: "demo",
  display_name: "Demo tenant",
  business_type: "demo",
  status: "active",
  active_config_revision_id: null,
  active_prompt_set_revision_id: null,
  active_voice_runtime_revision_id: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("Admin app shell", () => {
  it("renders feature-derived navigation and tenant selector data", async () => {
    server.use(
      http.get("/admin/v1/tenants", () => HttpResponse.json([tenant])),
    );
    render(<App />);
    expect(
      await screen.findByRole("navigation", { name: "Admin navigation" }),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "Overview" })).toBeVisible();
    expect(screen.getByText("Example")).toBeVisible();
    expect(
      await screen.findByRole("option", { name: "Demo tenant" }),
    ).toBeVisible();
  });

  it("renders a tenant-list failure predictably", async () => {
    server.use(
      http.get("/admin/v1/tenants", () =>
        HttpResponse.json({ detail: "denied" }, { status: 401 }),
      ),
    );
    render(<App />);
    expect(await screen.findByText("Tenant list unavailable")).toBeVisible();
  });

  it("renders an empty tenant selector without manual ID entry", async () => {
    server.use(http.get("/admin/v1/tenants", () => HttpResponse.json([])));
    render(<App />);
    expect(await screen.findByText("No tenants")).toBeVisible();
  });
});
