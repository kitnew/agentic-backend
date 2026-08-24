import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/app";
import type { AuthoringPlan } from "../src/core/api/generated/models";
import { router } from "../src/routes/router";
import { server } from "./setup";

const tenantId = "11111111-1111-4111-8111-111111111111";
const tenant = {
  id: tenantId,
  slug: "debug-hotel",
  display_name: "Debug Hotel",
  business_type: "hotel",
  status: "active",
  active_release_id: "published",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};
let publishedName: string;
let draftName: string | undefined;
let draftVersion: number;
let savedConfig: ReturnType<typeof config> | undefined;

function config(name: string) {
  return {
    agent: {
      display_name: name,
      greeting: "Hello",
      profile: "hotel_assistant",
    },
    business: { name: "Debug Hotel", type: "hotel" },
    conversation: { scope: "property_only" },
    localization: { default_locale: "sk-SK", timezone: "Europe/Bratislava" },
    contact: {
      address: "Main street",
      emails: ["hello@example.com"],
      phones: ["+421900000000"],
      website: "https://example.com",
    },
    handoff: {
      destinations: {
        reception: {
          description: "Reception requests",
          phone_number: "+421900000001",
        },
      },
    },
  };
}

function authoringState(name: string, source: "draft" | "published") {
  return {
    value: config(name),
    published_value: config(publishedName),
    source,
    etag: source === "draft" ? `"${draftVersion}"` : null,
  };
}

function useHandlers(
  saveSpy = vi.fn(),
  planResponse: AuthoringPlan = { valid: true, errors: [], warnings: [] },
  conflict = false,
) {
  server.use(
    http.get("/admin/v1/tenants", () => HttpResponse.json([tenant])),
    http.get(`/admin/v1/tenants/${tenantId}/authoring/config`, () =>
      HttpResponse.json(
        authoringState(
          draftName ?? publishedName,
          draftName ? "draft" : "published",
        ),
      ),
    ),
    http.get("/admin/v1/platform/prompts/profiles", () =>
      HttpResponse.json(["hotel_assistant"]),
    ),
    http.get("/admin/v1/platform/runtime", () =>
      HttpResponse.json({
        draft_revision: null,
        latest_published_revision: null,
      }),
    ),
    http.get("/admin/v1/platform/prompts/system/default/revisions", () =>
      HttpResponse.json([]),
    ),
    http.get(
      "/admin/v1/platform/prompts/profiles/hotel_assistant/revisions",
      () => HttpResponse.json([]),
    ),
    http.get(`/admin/v1/tenants/${tenantId}/tenant-prompt/revisions`, () =>
      HttpResponse.json([]),
    ),
    http.get(`/admin/v1/tenants/${tenantId}/runtime`, () =>
      HttpResponse.json({
        draft_revision: null,
        latest_published_revision: null,
      }),
    ),
    http.get(`/admin/v1/tenants/${tenantId}/knowledge-base`, () =>
      HttpResponse.json({
        tenant_id: tenantId,
        draft_revision: null,
        latest_published_revision: null,
        published_documents: [],
      }),
    ),
    http.post(`/admin/v1/tenants/${tenantId}/authoring/config/plan`, () =>
      HttpResponse.json(planResponse),
    ),
    http.put(
      `/admin/v1/tenants/${tenantId}/authoring/config`,
      async ({ request }) => {
        expect(request.headers.get("If-Match")).toBe(
          draftName ? `"${draftVersion}"` : null,
        );
        if (conflict)
          return HttpResponse.json(
            { detail: "draft version does not match If-Match" },
            { status: 412 },
          );
        savedConfig = (await request.json()) as ReturnType<typeof config>;
        draftName = savedConfig.agent.display_name;
        draftVersion = draftVersion + 1;
        saveSpy();
        return HttpResponse.json(authoringState(draftName, "draft"));
      },
    ),
  );
}

beforeEach(() => {
  publishedName = "Amelia";
  draftName = undefined;
  draftVersion = 0;
  savedConfig = undefined;
  window.history.pushState({}, "", `/tenants/${tenantId}/agent`);
});

describe("Agent page", () => {
  it("loads and saves localization and handoff destinations", async () => {
    const user = userEvent.setup();
    useHandlers();
    render(<App />);
    expect(await screen.findByLabelText(/Default locale/)).toHaveValue("sk-SK");
    expect(screen.getByLabelText(/Timezone/)).toHaveValue("Europe/Bratislava");
    expect(screen.getByLabelText(/Key/)).toHaveValue("reception");
    expect(screen.getByLabelText("Description")).toHaveValue(
      "Reception requests",
    );
    expect(screen.getAllByLabelText(/Phone number/)[1]).toHaveValue(
      "+421900000001",
    );

    await user.clear(screen.getByLabelText(/Timezone/));
    await user.type(screen.getByLabelText(/Timezone/), "UTC");
    await user.click(screen.getByRole("button", { name: "Add destination" }));
    const keys = screen.getAllByLabelText(/Key/);
    const descriptions = screen.getAllByLabelText("Description");
    const phones = screen.getAllByLabelText(/Phone number/);
    await user.clear(keys[1]);
    await user.type(keys[1], "manager");
    await user.type(descriptions[1], "Manager requests");
    await user.type(phones[2], "+421900000002");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Saved · Pending publish")).toBeVisible();
    expect(savedConfig).toMatchObject({
      localization: { default_locale: "sk-SK", timezone: "UTC" },
      handoff: {
        destinations: {
          reception: { phone_number: "+421900000001" },
          manager: { phone_number: "+421900000002" },
        },
      },
      business: config("Amelia").business,
      conversation: config("Amelia").conversation,
    });
  });

  it("removes a handoff destination without rebuilding hidden config fields", async () => {
    const user = userEvent.setup();
    useHandlers();
    render(<App />);
    await screen.findByLabelText(/Default locale/);
    await user.click(screen.getByRole("button", { name: "Remove reception" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved · Pending publish")).toBeVisible();
    expect(savedConfig).toMatchObject({
      business: config("Amelia").business,
      conversation: config("Amelia").conversation,
      handoff: { destinations: {} },
    });
  });

  it("blocks Save on a Backend handoff validation error", async () => {
    const user = userEvent.setup();
    useHandlers(undefined, {
      valid: false,
      errors: [
        {
          code: "invalid_phone",
          path: "handoff.destinations.reception.phone_number",
          message: "Phone number is invalid",
        },
      ],
      warnings: [],
    });
    render(<App />);
    await screen.findByLabelText(/Default locale/);
    const handoffPhone = screen.getAllByLabelText(/Phone number/)[1];
    await user.clear(handoffPhone);
    await user.type(handoffPhone, "not-a-phone");
    expect(await screen.findByText(/Phone number is invalid/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("plans and saves through the authoring API without component publish", async () => {
    const user = userEvent.setup();
    const save = vi.fn();
    useHandlers(save);
    render(<App />);
    const name = await screen.findByLabelText("Display Name");
    expect(screen.getByLabelText(/Email addresses/)).toHaveValue(
      "hello@example.com",
    );
    await user.clear(name);
    await user.type(name, "Amelia Updated");
    expect(screen.getByText("Unsaved changes")).toBeVisible();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved · Pending publish")).toBeVisible();
    expect(save).toHaveBeenCalledOnce();
    expect(
      screen.queryByRole("button", { name: "Publish" }),
    ).not.toBeInTheDocument();
  });

  it("guards navigation with Stay, Discard, and Save and continue", async () => {
    const user = userEvent.setup();
    const save = vi.fn();
    useHandlers(save);
    render(<App />);
    const name = await screen.findByLabelText("Display Name");
    await user.clear(name);
    await user.type(name, "Changed");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
    );
    await user.click(screen.getByRole("link", { name: "Platform" }));
    expect(
      screen.getByRole("dialog", { name: "Unsaved changes" }),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Stay" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(window.location.pathname).toContain("/agent");
    await user.click(screen.getByRole("link", { name: "Platform" }));
    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    await waitFor(() => expect(window.location.pathname).toBe("/platform"));

    await user.click(screen.getByRole("link", { name: "Tenants" }));
    await user.click(await screen.findByRole("link", { name: /Debug Hotel/ }));
    await user.click(await screen.findByRole("link", { name: "Agent" }));
    const secondName = await screen.findByLabelText("Display Name");
    await user.clear(secondName);
    await user.type(secondName, "Saved on leave");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
    );
    await user.click(screen.getByRole("link", { name: "Platform" }));
    await user.click(screen.getByRole("button", { name: "Save and continue" }));
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    await waitFor(() => expect(window.location.pathname).toBe("/platform"));
  });

  it("blocks Save and shows backend plan issues", async () => {
    const user = userEvent.setup();
    const save = vi.fn();
    useHandlers(save, {
      valid: false,
      errors: [
        {
          code: "invalid_profile",
          path: "agent.profile",
          message: "Unknown profile",
        },
      ],
      warnings: [],
    });
    render(<App />);
    await router.navigate({ to: `/tenants/${tenantId}/agent` as never });
    const name = await screen.findByLabelText("Display Name");
    await user.clear(name);
    await user.type(name, "Changed");
    expect(await screen.findByText(/Unknown profile/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(save).not.toHaveBeenCalled();
  });

  it("reports an authoring save concurrency conflict", async () => {
    const user = userEvent.setup();
    const save = vi.fn();
    draftName = "Amelia";
    draftVersion = 1;
    useHandlers(save, undefined, true);
    render(<App />);
    await router.navigate({ to: `/tenants/${tenantId}/agent` as never });
    const name = await screen.findByLabelText("Display Name");
    await user.clear(name);
    await user.type(name, "Changed");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText(
        "This configuration changed on the server. Reload before saving again.",
      ),
    ).toBeVisible();
    expect(save).not.toHaveBeenCalled();
  });
});
