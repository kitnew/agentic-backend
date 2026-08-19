import { expect, test } from "@playwright/test";

const tenantId = "11111111-1111-4111-8111-111111111111";
let agentName = "Amelia";

function config() {
  return {
    schema_version: 4,
    agent: {
      display_name: agentName,
      greeting: "Hello",
      profile: "hotel_assistant",
    },
    business: { name: "Debug Hotel", type: "hotel" },
    conversation: { scope: "property_only" },
    localization: { default_locale: "sk-SK", timezone: "Europe/Bratislava" },
  };
}

test("Agent saves and reloads canonical configuration", async ({ page }) => {
  await page.route("**/admin/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
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
          config: config(),
        },
      });
    if (path.endsWith("/config/revisions")) return route.fulfill({ json: [] });
    if (path.endsWith("/tenant-prompt/revisions"))
      return route.fulfill({
        json: [
          {
            id: "prompt",
            prompt_id: "prompt",
            tenant_id: tenantId,
            text: "Be helpful.",
            status: "published",
            version: 1,
            revision_number: 1,
            created_at: "2026-01-01T00:00:00Z",
            published_at: "2026-01-01T00:00:00Z",
          },
        ],
      });
    if (path.endsWith("/runtime"))
      return route.fulfill({
        json: { draft_revision: null, latest_published_revision: null },
      });
    if (path === "/admin/v1/platform/prompts/profiles")
      return route.fulfill({ json: ["hotel_assistant"] });
    if (path.endsWith("/system/default/revisions"))
      return route.fulfill({
        json: [{ id: "system", text: "System", status: "published" }],
      });
    if (path.endsWith("/profiles/hotel_assistant/revisions"))
      return route.fulfill({
        json: [{ id: "profile", text: "Profile", status: "published" }],
      });
    if (path.endsWith("/config/drafts") && request.method() === "POST") {
      agentName = (await request.postDataJSON()).config.agent.display_name;
      return route.fulfill({ status: 201, json: { id: "draft" } });
    }
    if (path.endsWith("/config/drafts/draft/publish"))
      return route.fulfill({ json: { id: "draft" } });
    if (path.endsWith("/prompt-set/apply"))
      return route.fulfill({ json: { changed: true, prompt_set: {} } });
    return route.fulfill({
      status: 404,
      json: { detail: `Unhandled ${path}` },
    });
  });
  await page.goto(`/tenants/${tenantId}/agent`);
  await expect(page.getByLabel("Agent name")).toHaveValue("Amelia");
  await page.getByLabel("Agent name").fill("Amelia Updated");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Agent configuration saved")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Agent name")).toHaveValue("Amelia Updated");
});
