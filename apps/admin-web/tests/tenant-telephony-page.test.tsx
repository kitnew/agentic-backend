import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { queryClient } from "../src/app/query-client";
import { TenantTelephonyPage } from "../src/features/telephony/tenant-page";
import { server } from "./setup";

vi.mock("../src/core/tenant/use-tenant", () => ({
  useTenant: () => ({ tenantId: "tenant-1" }),
}));

describe("Tenant Telephony page", () => {
  it("shows both active DIDs and disables only the selected assignment with its ETag", async () => {
    let disabled = false;
    let ifMatch: string | null = null;
    let enableIfMatch: string | null = null;
    const assignments = [
      {
        id: "did-1",
        tenant_id: "tenant-1",
        phone_number: "+421552301272",
        enabled: true,
      },
      {
        id: "did-2",
        tenant_id: "tenant-1",
        phone_number: "+421552301299",
        enabled: true,
      },
    ];
    server.use(
      http.get(
        "/management/v1/tenants/:tenantId/telephony/phone-number-assignments",
        () =>
          HttpResponse.json(
            assignments.map((item) =>
              item.id === "did-2" ? { ...item, enabled: !disabled } : item,
            ),
          ),
      ),
      http.get(
        "/management/v1/tenants/:tenantId/telephony/phone-number-assignments/:id",
        ({ params }) =>
          HttpResponse.json(
            params.id === "did-2"
              ? { ...assignments[1], enabled: !disabled }
              : assignments[0],
            {
              headers: {
                ETag: disabled ? '"did-generation-2"' : '"did-generation-1"',
              },
            },
          ),
      ),
      http.post(
        "/management/v1/tenants/:tenantId/telephony/phone-number-assignments/:id/disable",
        ({ request, params }) => {
          ifMatch = request.headers.get("if-match");
          expect(params.id).toBe("did-2");
          disabled = true;
          return HttpResponse.json({ ...assignments[1], enabled: false });
        },
      ),
      http.post(
        "/management/v1/tenants/:tenantId/telephony/phone-number-assignments/:id/enable",
        ({ request, params }) => {
          enableIfMatch = request.headers.get("if-match");
          expect(params.id).toBe("did-2");
          disabled = false;
          return HttpResponse.json(assignments[1]);
        },
      ),
      http.get("/admin/v1/tenants/:tenantId/telephony/status", () =>
        HttpResponse.json({
          tenant_id: "tenant-1",
          draft: null,
          published: { phone_number: "+421552301272" },
          publication: "published",
          claim: { state: "ready", phone_number: "+421552301272" },
          provisioning: { state: "ready", last_error: null },
        }),
      ),
    );
    render(
      <QueryClientProvider client={queryClient}>
        <TenantTelephonyPage />
      </QueryClientProvider>,
    );
    const row = (phone: string) =>
      screen.getByText(phone).closest("li") as HTMLElement;
    expect(await screen.findByText("+421552301272")).toBeVisible();
    expect(screen.getByText("+421552301299")).toBeVisible();
    await userEvent
      .setup()
      .click(
        within(row("+421552301299")).getByRole("button", { name: "Disable" }),
      );
    await waitFor(() => expect(ifMatch).toBe('"did-generation-1"'));
    expect(
      await within(row("+421552301299")).findByRole("button", {
        name: "Enable",
      }),
    ).toBeVisible();
    expect(
      within(row("+421552301272")).getByRole("button", { name: "Disable" }),
    ).toBeVisible();
    await userEvent
      .setup()
      .click(
        within(row("+421552301299")).getByRole("button", { name: "Enable" }),
      );
    await waitFor(() => expect(enableIfMatch).toBe('"did-generation-2"'));
    expect(
      await within(row("+421552301299")).findByRole("button", {
        name: "Disable",
      }),
    ).toBeVisible();
  });
});
