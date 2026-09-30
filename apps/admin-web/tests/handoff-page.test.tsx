import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { queryClient } from "../src/app/query-client";
import { HandoffPage } from "../src/features/tenants/handoff-page";
import { server } from "./setup";

vi.mock("../src/core/tenant/use-tenant", () => ({
  useTenant: () => ({ tenantId: "tenant-1" }),
}));

describe("Handoff page", () => {
  it("shows a duplicate-key error and keeps the create form", async () => {
    server.use(
      http.get(
        "/management/v1/tenants/:tenantId/telephony/handoff-destinations",
        () => HttpResponse.json([]),
      ),
      http.post(
        "/management/v1/tenants/:tenantId/telephony/handoff-destinations",
        () =>
          HttpResponse.json(
            {
              code: "conflict",
              message: "handoff destination key already exists for tenant",
            },
            { status: 409 },
          ),
      ),
    );
    render(
      <QueryClientProvider client={queryClient}>
        <HandoffPage />
      </QueryClientProvider>,
    );
    const user = userEvent.setup();
    await screen.findByRole("button", { name: "Create destination" });
    await user.type(screen.getByLabelText("Key"), "sales");
    await user.type(screen.getByLabelText("Phone number"), "+420123456789");
    await user.type(screen.getByLabelText("Description"), "Sales team");
    await user.click(
      screen.getByRole("button", { name: "Create destination" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "handoff destination key already exists for tenant",
    );
    expect(screen.getByLabelText("Key")).toHaveValue("sales");
    expect(screen.getByLabelText("Phone number")).toHaveValue("+420123456789");
    expect(screen.getByLabelText("Description")).toHaveValue("Sales team");
  });

  it("edits a disabled destination, then enables and disables it separately", async () => {
    let updateBody: unknown;
    let ifMatch: string | null = null;
    let destination = {
      id: "destination-1",
      key: "sales",
      phone_number: "+420111111111",
      description: "Old",
      enabled: false,
    };
    let generation = 1;
    let lifecycleCalls = 0;
    let getCalls = 0;
    server.use(
      http.get(
        "/management/v1/tenants/:tenantId/telephony/handoff-destinations",
        () => HttpResponse.json([destination]),
      ),
      http.get(
        "/management/v1/tenants/:tenantId/telephony/handoff-destinations/:id",
        () => {
          getCalls++;
          return HttpResponse.json(destination, {
            headers: { ETag: `"generation-${generation}"` },
          });
        },
      ),
      http.put(
        "/management/v1/tenants/:tenantId/telephony/handoff-destinations/:id",
        async ({ request }) => {
          updateBody = await request.json();
          ifMatch = request.headers.get("if-match");
          destination = { ...destination, ...(updateBody as object) };
          generation++;
          return HttpResponse.json(destination);
        },
      ),
      http.post(
        "/management/v1/tenants/:tenantId/telephony/handoff-destinations/:id/enable",
        () => {
          lifecycleCalls++;
          destination = { ...destination, enabled: true };
          generation++;
          return HttpResponse.json(destination);
        },
      ),
      http.post(
        "/management/v1/tenants/:tenantId/telephony/handoff-destinations/:id/disable",
        () => {
          lifecycleCalls++;
          destination = { ...destination, enabled: false };
          generation++;
          return HttpResponse.json(destination);
        },
      ),
    );
    render(
      <QueryClientProvider client={queryClient}>
        <HandoffPage />
      </QueryClientProvider>,
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edit" }));
    await user.clear(await screen.findByLabelText("sales phone number"));
    await user.type(
      screen.getByLabelText("sales phone number"),
      "+420222222222",
    );
    await user.clear(screen.getByLabelText("sales description"));
    await user.type(screen.getByLabelText("sales description"), "New label");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(updateBody).toEqual({
        description: "New label",
        phone_number: "+420222222222",
      }),
    );
    expect(ifMatch).toBe('"generation-1"');
    expect(getCalls).toBe(1);
    expect(lifecycleCalls).toBe(0);
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Save changes" }),
      ).not.toBeInTheDocument(),
    );
    await user.click(await screen.findByRole("button", { name: "Enable" }));
    await waitFor(() => expect(lifecycleCalls).toBe(1));
    await user.click(await screen.findByRole("button", { name: "Disable" }));
    await waitFor(() => expect(lifecycleCalls).toBe(2));
    expect(destination.key).toBe("sales");
    expect(destination.phone_number).toBe("+420222222222");
    expect(destination.description).toBe("New label");
  });

  it("keeps edits after a stale ETag response", async () => {
    const destination = {
      id: "destination-1",
      key: "sales",
      phone_number: "+420111111111",
      description: "Old",
      enabled: true,
    };
    server.use(
      http.get(
        "/management/v1/tenants/:tenantId/telephony/handoff-destinations",
        () => HttpResponse.json([destination]),
      ),
      http.get(
        "/management/v1/tenants/:tenantId/telephony/handoff-destinations/:id",
        () => HttpResponse.json(destination, { headers: { ETag: '"old"' } }),
      ),
      http.put(
        "/management/v1/tenants/:tenantId/telephony/handoff-destinations/:id",
        () =>
          HttpResponse.json(
            { message: "Destination changed on the server" },
            { status: 412 },
          ),
      ),
    );
    render(
      <QueryClientProvider client={queryClient}>
        <HandoffPage />
      </QueryClientProvider>,
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edit" }));
    await user.clear(await screen.findByLabelText("sales description"));
    await user.type(screen.getByLabelText("sales description"), "Changed");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Destination changed on the server",
    );
    expect(screen.getByLabelText("sales description")).toHaveValue("Changed");
    expect(screen.queryByLabelText("sales key")).not.toBeInTheDocument();
  });
});
