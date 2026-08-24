import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { queryClient } from "../src/app/query-client";
import { PlatformTelephonyPage } from "../src/features/telephony/telephony-page";
import { server } from "./setup";

describe("Platform Telephony page", () => {
  it("renders ready infrastructure and collapsed diagnostics without fake authoring", async () => {
    const repair = vi.fn();
    const platform = {
      provider: "connected",
      inbound: "ready",
      outbound: "ready",
      dispatch: "ready",
      overall: "ready",
      last_error: null,
      last_reconciled_at: "2026-01-01T00:00:00Z",
      diagnostics: { inbound_trunk_id: "ST_inbound" },
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
    render(
      <QueryClientProvider client={queryClient}>
        <PlatformTelephonyPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Infrastructure status")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Repair" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue(/ST_inbound/)).not.toBeInTheDocument();
    expect(screen.getByText("Technical diagnostics")).toBeVisible();
    const details = screen
      .getByText("Technical diagnostics")
      .closest("details");
    expect(details).not.toHaveAttribute("open");
    await userEvent.setup().click(screen.getByText("Technical diagnostics"));
    expect(details).toHaveAttribute("open");
    expect(screen.getByText("Trunk configuration")).toBeVisible();
    expect(repair).not.toHaveBeenCalled();
  });

  it("offers repair only for connected degraded infrastructure", async () => {
    const repair = vi.fn();
    const platform = {
      provider: "connected",
      inbound: "pending",
      outbound: "ready",
      dispatch: "pending",
      overall: "degraded",
      last_error: "Provisioning incomplete",
      last_reconciled_at: null,
      diagnostics: {},
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
    render(
      <QueryClientProvider client={queryClient}>
        <PlatformTelephonyPage />
      </QueryClientProvider>,
    );
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Repair" }));
    await waitFor(() => expect(repair).toHaveBeenCalledOnce());
  });

  it("does not offer repair when provider configuration is missing", async () => {
    server.use(
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
    );
    render(
      <QueryClientProvider client={queryClient}>
        <PlatformTelephonyPage />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Configuration required")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Repair" }),
    ).not.toBeInTheDocument();
  });
});
