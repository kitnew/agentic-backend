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
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("Admin app shell", () => {
  it("renders product navigation and tenant cards without UUID copy", async () => {
    server.use(
      http.get("/admin/v1/tenants", () => HttpResponse.json([tenant])),
    );
    window.history.pushState({}, "", "/");
    render(<App />);
    const navigation = await screen.findByRole("navigation", {
      name: "Main navigation",
    });
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
      await screen.findByRole("heading", { name: "Demo tenant" }),
    ).toBeVisible();
    expect(screen.queryByText(tenant.id)).not.toBeInTheDocument();
  });

  it("exposes current CP tenant authoring navigation", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/admin/v1/tenants", () => HttpResponse.json([tenant])),
    );
    window.history.pushState({}, "", "/");
    render(<App />);
    await user.click(await screen.findByRole("link", { name: /Demo tenant/ }));
    const navigation = await screen.findByRole("navigation", {
      name: "Tenant navigation",
    });
    for (const label of [
      "Runtime",
      "Agent",
      "Prompt",
      "Knowledge Base",
      "Capabilities",
      "Integrations",
      "Post-call",
      "Handoff",
      "Telephony",
      "Playground",
    ]) {
      expect(
        within(navigation).getByText(label, { exact: true }),
      ).toBeVisible();
    }
    expect(
      within(navigation).queryByText("Coming later"),
    ).not.toBeInTheDocument();
  });
});
