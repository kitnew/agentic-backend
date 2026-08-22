import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/app";
import { queryClient } from "../src/app/query-client";
import { PlatformTelephonyPage } from "../src/features/telephony/telephony-page";
import { server } from "./setup";

const tenantId = "11111111-1111-4111-8111-111111111111";
const tenant = {
  id: tenantId,
  slug: "debug-hotel",
  display_name: "Debug Hotel",
  business_type: "hotel",
  status: "active",
  active_config_revision_id: "published",
  active_prompt_set_revision_id: null,
  active_voice_runtime_revision_id: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function state(draft = false) {
  return {
    tenant_id: tenantId,
    desired: {
      phone_number: "+421551234567",
      handoff: { destinations: {} },
    },
    draft_revision_id: draft ? "draft" : null,
    draft_version: draft ? 1 : null,
    published_revision_id: "published",
    provisioning_status: draft ? "pending" : "ready",
    last_error: null,
    last_reconciled_at: "2026-01-01T00:00:00Z",
    readiness: {
      phone_number: draft ? "pending" : "ready",
      incoming_calls: draft ? "pending" : "ready",
      outgoing_calls: draft ? "pending" : "ready",
      human_handoff: "pending",
    },
  };
}

beforeEach(() => {
  window.history.pushState({}, "", `/tenants/${tenantId}/telephony`);
});

describe("Tenant Telephony page", () => {
  it("validates, saves a destination, renders status, and publishes separately", async () => {
    const user = userEvent.setup();
    const save = vi.fn();
    const publish = vi.fn();
    let draft = false;
    server.use(
      http.get("/admin/v1/tenants", () => HttpResponse.json([tenant])),
      http.get(`/admin/v1/tenants/${tenantId}/telephony`, () =>
        HttpResponse.json(state(draft)),
      ),
      http.put(
        `/admin/v1/tenants/${tenantId}/telephony`,
        async ({ request }) => {
          save(await request.json());
          draft = true;
          return HttpResponse.json(state(true));
        },
      ),
      http.post(
        `/admin/v1/tenants/${tenantId}/config/drafts/draft/publish`,
        () => {
          publish();
          draft = false;
          return HttpResponse.json({ id: "draft" });
        },
      ),
    );
    render(<App />);

    expect(await screen.findByText("incoming calls")).toBeVisible();
    expect(screen.getAllByText("ready").length).toBeGreaterThan(1);
    await user.click(screen.getByRole("button", { name: "Add destination" }));
    expect(screen.getByText("Unsaved changes")).toBeVisible();
    await user.clear(screen.getByLabelText("Label"));
    await user.type(screen.getByLabelText("Label"), "Reception");
    const destinationPhone = screen.getByLabelText("Phone number");
    await user.type(destinationPhone, "invalid");
    expect(
      screen.getByText(/unique semantic keys and valid E.164/),
    ).toBeVisible();
    await user.clear(destinationPhone);
    await user.type(destinationPhone, "+421900000001");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    expect(publish).not.toHaveBeenCalled();
    expect(
      await screen.findByText(/Saved changes are not published yet/),
    ).toBeVisible();
    expect(save.mock.calls[0][0]).toMatchObject({
      phone_number: "+421551234567",
      handoff: {
        destinations: {
          destination_1: {
            description: "Reception",
            phone_number: "+421900000001",
          },
        },
      },
    });
    await user.click(await screen.findByRole("button", { name: "Publish" }));
    await waitFor(() => expect(publish).toHaveBeenCalledOnce());
  });

  it("shows business-level provisioning failures", async () => {
    server.use(
      http.get("/admin/v1/tenants", () => HttpResponse.json([tenant])),
      http.get(`/admin/v1/tenants/${tenantId}/telephony`, () =>
        HttpResponse.json({
          ...state(),
          provisioning_status: "error",
          last_error: "Platform telephony is unavailable",
          readiness: {
            ...state().readiness,
            incoming_calls: "error",
            outgoing_calls: "error",
          },
        }),
      ),
    );
    render(<App />);

    expect(
      await screen.findByText("Platform telephony is unavailable"),
    ).toBeVisible();
    expect(screen.getAllByText("error")).toHaveLength(2);
  });

  it("repairs shared platform infrastructure without exposing it as tenant state", async () => {
    const repair = vi.fn();
    const platform = {
      provider: "connected",
      inbound: "ready",
      outbound: "ready",
      dispatch: "ready",
      overall: "ready",
      last_error: null,
      last_reconciled_at: "2026-01-01T00:00:00Z",
      diagnostics: {
        inbound_trunk_id: "ST_inbound",
        outbound_trunk_id: "ST_outbound",
        dispatch_rule_id: "SDR_shared",
      },
    };
    server.use(
      http.get("/admin/v1/platform/telephony", () =>
        HttpResponse.json(platform),
      ),
      http.post("/admin/v1/platform/telephony/reconcile", () => {
        repair();
        return HttpResponse.json(platform);
      }),
    );
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={queryClient}>
        <PlatformTelephonyPage />
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole("button", { name: "Repair" }));
    await waitFor(() => expect(repair).toHaveBeenCalledOnce());
    expect(screen.getByText("Technical diagnostics")).toBeVisible();
    expect(screen.queryByText("ST_inbound")).not.toBeInTheDocument();
  });
});
