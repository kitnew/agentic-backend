import { render, screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { App } from "../src/app/app";
import { router } from "../src/routes/router";
import { server } from "./setup";

const tenantId = "11111111-1111-4111-8111-111111111111";

describe("deferred Integrations route", () => {
  it("shows the agentctl placeholder without integration controls", async () => {
    server.use(
      http.get("/admin/v1/tenants", () =>
        HttpResponse.json([
          {
            id: tenantId,
            slug: "demo",
            display_name: "Demo tenant",
            business_type: "hotel",
            status: "active",
            active_release_id: null,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ]),
      ),
    );
    render(<App />);
    await router.navigate({
      to: `/tenants/${tenantId}/integrations/check-availability` as never,
    });

    expect(
      await screen.findByRole("heading", {
        name: "Feature temporarily unavailable in Admin Web",
      }),
    ).toBeVisible();
    expect(
      screen.getByText(
        "Use agentctl for configuration and management until the Admin Web domain model is finalized.",
      ),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /Save|Publish|Repair/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText("New API key")).not.toBeInTheDocument();
  });
});
