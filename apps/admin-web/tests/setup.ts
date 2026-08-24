import "@testing-library/jest-dom/vitest";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, beforeEach } from "vitest";

import { queryClient } from "../src/app/query-client";

export const server = setupServer();
Object.defineProperty(window, "scrollTo", {
  value: () => undefined,
  writable: true,
});

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  server.use(
    http.get("/admin/v1/tenants", () => HttpResponse.json([])),
    http.get("/admin/v1/platform/components/state", () =>
      HttpResponse.json({
        runtime_draft: null,
        system_prompt_draft: null,
        profile_prompt_drafts: {},
        active_release: null,
        active_runtime: null,
        active_system_prompt: null,
        active_profile_prompts: {},
      }),
    ),
    http.get("/admin/v1/platform/telephony", () =>
      HttpResponse.json({
        provider: "configuration_required",
        inbound: "pending",
        outbound: "pending",
        dispatch: "pending",
        overall: "degraded",
        last_error: null,
        last_reconciled_at: null,
        diagnostics: {},
      }),
    ),
    http.get(
      "/admin/v1/tenants/:tenantId/components/:component",
      ({ params }) =>
        HttpResponse.json({
          component: params.component,
          draft: null,
          active_revision: null,
        }),
    ),
    http.get("/admin/v1/tenants/:tenantId", ({ params }) =>
      HttpResponse.json({
        id: params.tenantId,
        slug: "demo",
        display_name: "Demo tenant",
        business_type: "hotel",
        status: "active",
        active_release_id: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      }),
    ),
  );
});
afterEach(() => {
  server.resetHandlers();
  queryClient.clear();
});
afterAll(() => server.close());
