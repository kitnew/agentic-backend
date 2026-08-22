import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { queryClient } from "../src/app/query-client";
import { PlatformTelephonyPage } from "../src/features/telephony/telephony-page";
import { server } from "./setup";

describe("Platform Telephony page", () => {
  it("repairs shared infrastructure without exposing it as tenant configuration", async () => {
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
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={queryClient}>
        <PlatformTelephonyPage />
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole("button", { name: "Repair" }));
    await waitFor(() => expect(repair).toHaveBeenCalledOnce());
    expect(screen.getByText("Technical diagnostics")).toBeVisible();
  });
});
