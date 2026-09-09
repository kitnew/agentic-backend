import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { App } from "../src/app/app";
import { server } from "./setup";

const tenant = {
  id: "44444444-4444-4444-8444-444444444444",
  slug: "demo-hotel",
  display_name: "Demo Hotel",
  business_type: "hotel",
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function requiredRequest(request: Request | undefined): Request {
  if (!request) throw new Error("Expected request was not captured");
  return request;
}

describe("Admin Web tenant creation", () => {
  it("uses Backend tenant create, invalidates the list, and opens tenant management", async () => {
    const user = userEvent.setup();
    let tenants: (typeof tenant)[] = [];
    let request: Request | undefined;
    const cpTenantMutation = vi.fn();
    server.use(
      http.get("/admin/v1/tenants", () => HttpResponse.json(tenants)),
      http.post("/admin/v1/tenants", async ({ request: incoming }) => {
        request = incoming;
        tenants = [tenant];
        return HttpResponse.json(tenant, { status: 201 });
      }),
      http.get("/management/v1/tenants/:tenantId/configuration", () =>
        HttpResponse.json(
          {
            code: "configuration_not_initialized",
            message: "Not initialized",
            issues: [],
            request_id: "request-config",
          },
          { status: 404 },
        ),
      ),
      http.put("/management/v1/tenants/:tenantId/configuration", () => {
        cpTenantMutation();
        return HttpResponse.json({});
      }),
    );
    window.history.pushState({}, "", "/tenants");
    render(<App />);

    await user.click(
      await screen.findByRole("button", { name: "Create tenant" }),
    );
    await user.type(screen.getByLabelText("Tenant slug"), "demo-hotel");
    await user.type(screen.getByLabelText("Display name"), "Demo Hotel");
    await user.type(screen.getByLabelText("Business type"), "hotel");
    await user.click(screen.getByRole("button", { name: "Create tenant" }));

    await waitFor(() => expect(request).toBeDefined());
    const tenantRequest = requiredRequest(request);
    expect(await tenantRequest.clone().json()).toEqual({
      slug: "demo-hotel",
      display_name: "Demo Hotel",
      business_type: "hotel",
    });
    expect(Object.keys(await tenantRequest.clone().json())).toEqual([
      "slug",
      "display_name",
      "business_type",
    ]);
    await waitFor(() =>
      expect(window.location.pathname).toBe(`/tenants/${tenant.id}/runtime`),
    );
    expect(await screen.findByText("Tenant Configuration")).toBeVisible();
    expect(cpTenantMutation).not.toHaveBeenCalled();
  });
});
