import { expect, test } from "@playwright/test";

const tenantId = "11111111-1111-4111-8111-111111111111";
const publishedName = "Amelia";
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

test("Agent saves a draft without silently publishing it", async ({ page }) => {
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
            active_release_id: "config",
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ],
      });
    if (path.endsWith("/authoring/config") && request.method() === "PUT") {
      const nextName = (await request.postDataJSON()).agent
        .display_name as string;
      draftName = nextName;
      return route.fulfill({
        json: {
          value: config(nextName),
          published_value: config(publishedName),
          source: "draft",
          etag: '"1"',
        },
      });
    }
    if (path.endsWith("/authoring/config"))
      return route.fulfill({
        json: {
          value: config(draftName ?? publishedName),
          published_value: config(publishedName),
          source: draftName ? "draft" : "published",
          etag: draftName ? '"1"' : null,
        },
      });
    if (path.endsWith("/authoring/config/plan"))
      return route.fulfill({ json: { valid: true, errors: [], warnings: [] } });
    return route.fulfill({
      status: 404,
      json: { detail: `Unhandled ${path}` },
    });
  });
  await page.goto(`/tenants/${tenantId}/agent`);
  await page.getByLabel("Display Name").fill("Amelia Updated");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Saved · Pending publish")).toBeVisible();
  await expect(page.getByRole("button", { name: "Publish" })).toHaveCount(0);
  await page.reload();
  await expect(page.getByLabel("Display Name")).toHaveValue("Amelia Updated");
});
