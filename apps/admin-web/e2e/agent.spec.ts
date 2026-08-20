import { expect, test } from "@playwright/test";

const tenantId = "11111111-1111-4111-8111-111111111111";
let publishedName = "Amelia";
let draftName: string | undefined;

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
    contact: { emails: [], phones: [] },
    handoff: { destinations: {} },
  };
}

test("Agent saves a draft before publishing it", async ({ page }) => {
  await page.route("**/admin/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/admin/v1/tenants")
      return route.fulfill({
        json: [
          {
            id: tenantId,
            slug: "debug-hotel",
            display_name: "Debug Hotel",
            business_type: "hotel",
            status: "active",
            active_config_revision_id: "config",
            active_prompt_set_revision_id: "prompt-set",
            active_voice_runtime_revision_id: null,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ],
      });
    if (path.endsWith("/config/active"))
      return route.fulfill({
        json: {
          tenant_id: tenantId,
          revision_id: "config",
          revision_number: 1,
          published_at: "2026-01-01T00:00:00Z",
          config: config(publishedName),
        },
      });
    if (path.endsWith("/config/revisions"))
      return route.fulfill({
        json: draftName
          ? [
              {
                id: "draft",
                tenant_id: tenantId,
                revision_number: 2,
                schema_version: 4,
                config: config(draftName),
                status: "draft",
                version: 1,
                comment: null,
                created_by: null,
                created_at: "2026-01-01T00:00:00Z",
                published_at: null,
              },
            ]
          : [],
      });
    if (path === "/admin/v1/platform/prompts/profiles")
      return route.fulfill({ json: ["hotel_assistant"] });
    if (path.endsWith("/config/drafts") && request.method() === "POST") {
      draftName = (await request.postDataJSON()).config.agent.display_name;
      return route.fulfill({ status: 201, json: { id: "draft" } });
    }
    if (path.endsWith("/config/drafts/draft/publish")) {
      publishedName = draftName as string;
      draftName = undefined;
      return route.fulfill({ json: { id: "draft" } });
    }
    if (path.endsWith("/prompt-set/apply"))
      return route.fulfill({ json: { changed: true, prompt_set: {} } });
    return route.fulfill({
      status: 404,
      json: { detail: `Unhandled ${path}` },
    });
  });
  await page.goto(`/tenants/${tenantId}/agent`);
  await page.getByLabel("Display Name").fill("Amelia Updated");
  await expect(page.getByRole("button", { name: "Publish" })).toBeDisabled();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Saved · Not published")).toBeVisible();
  await page.getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText("Published")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Display Name")).toHaveValue("Amelia Updated");
});
