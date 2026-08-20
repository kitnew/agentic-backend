import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/app/app";
import { server } from "./setup";

const tenantId = "11111111-1111-4111-8111-111111111111";
const tenant = {
  id: tenantId,
  slug: "debug-hotel",
  display_name: "Debug Hotel",
  business_type: "hotel",
  status: "active",
  active_config_revision_id: "published",
  active_prompt_set_revision_id: "prompt-set",
  active_voice_runtime_revision_id: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};
let publishedName: string;
let draftName: string | undefined;
let draftVersion: number;

function config(name: string) {
  return {
    schema_version: 4,
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
        reception: { description: "Reception", phone_number: "+421900000001" },
      },
    },
  };
}

function revision(name: string) {
  return {
    id: "draft",
    tenant_id: tenantId,
    revision_number: 2,
    schema_version: 4,
    config: config(name),
    status: "draft",
    version: draftVersion,
    comment: null,
    created_by: null,
    created_at: "2026-01-01T00:00:00Z",
    published_at: null,
  };
}

function useHandlers(saveSpy = vi.fn(), publishSpy = vi.fn()) {
  server.use(
    http.get("/admin/v1/tenants", () => HttpResponse.json([tenant])),
    http.get(`/admin/v1/tenants/${tenantId}/config/active`, () =>
      HttpResponse.json({
        tenant_id: tenantId,
        revision_id: "published",
        revision_number: 1,
        published_at: "2026-01-01T00:00:00Z",
        config: config(publishedName),
      }),
    ),
    http.get(`/admin/v1/tenants/${tenantId}/config/revisions`, () =>
      HttpResponse.json(draftName ? [revision(draftName)] : []),
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
    http.post(
      `/admin/v1/tenants/${tenantId}/config/drafts`,
      async ({ request }) => {
        draftName = (
          (await request.json()) as {
            config: { agent: { display_name: string } };
          }
        ).config.agent.display_name;
        draftVersion = 1;
        saveSpy();
        return HttpResponse.json(revision(draftName), { status: 201 });
      },
    ),
    http.patch(
      `/admin/v1/tenants/${tenantId}/config/drafts/draft`,
      async ({ request }) => {
        draftName = (
          (await request.json()) as {
            config: { agent: { display_name: string } };
          }
        ).config.agent.display_name;
        draftVersion += 1;
        saveSpy();
        return HttpResponse.json(revision(draftName));
      },
    ),
    http.post(
      `/admin/v1/tenants/${tenantId}/config/drafts/draft/publish`,
      () => {
        publishedName = draftName as string;
        draftName = undefined;
        publishSpy();
        return HttpResponse.json({ id: "draft" });
      },
    ),
    http.post(`/admin/v1/tenants/${tenantId}/prompt-set/apply`, () =>
      HttpResponse.json({ changed: true, prompt_set: {} }),
    ),
  );
}

beforeEach(() => {
  publishedName = "Amelia";
  draftName = undefined;
  draftVersion = 0;
  window.history.pushState({}, "", `/tenants/${tenantId}/agent`);
});

describe("Agent page", () => {
  it("keeps Save and Publish separate and never publishes dirty local changes", async () => {
    const user = userEvent.setup();
    const save = vi.fn();
    const publish = vi.fn();
    useHandlers(save, publish);
    render(<App />);
    const name = await screen.findByLabelText("Display Name");
    expect(screen.getByLabelText(/Email addresses/)).toHaveValue(
      "hello@example.com",
    );
    expect(screen.getByLabelText("Phone number")).toHaveValue("+421900000001");
    await user.clear(name);
    await user.type(name, "Amelia Updated");
    expect(screen.getByText("Unsaved changes")).toBeVisible();
    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved · Not published")).toBeVisible();
    expect(save).toHaveBeenCalledOnce();
    expect(publish).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(publish).toHaveBeenCalledOnce());
    expect(await screen.findByText("Published")).toBeVisible();
    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
  });

  it("guards navigation with Stay, Discard, and Save and continue", async () => {
    const user = userEvent.setup();
    const save = vi.fn();
    useHandlers(save);
    render(<App />);
    const name = await screen.findByLabelText("Display Name");
    await user.clear(name);
    await user.type(name, "Changed");
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
    await user.click(screen.getByRole("link", { name: "Platform" }));
    await user.click(screen.getByRole("button", { name: "Save and continue" }));
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    await waitFor(() => expect(window.location.pathname).toBe("/platform"));
  });
});
