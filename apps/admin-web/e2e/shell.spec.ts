import { expect, test } from "@playwright/test";

const tenant = [
  {
    id: "11111111-1111-4111-8111-111111111111",
    slug: "demo",
    display_name: "Demo tenant",
    business_type: "demo",
    status: "active",
    active_config_revision_id: null,
    active_prompt_set_revision_id: null,
    active_voice_runtime_revision_id: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
];
const tenantId = "11111111-1111-4111-8111-111111111111";

test("shell selects a tenant and preserves its deep link", async ({ page }) => {
  await page.route("**/admin/v1/tenants?limit=100", (route) =>
    route.fulfill({ json: tenant }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("navigation", { name: "Admin navigation" }),
  ).toBeVisible();
  await page.getByLabel("Tenant").selectOption(tenantId);
  await expect(page).toHaveURL(`/tenants/${tenantId}/example`);
  await expect(page.getByRole("heading", { name: "Example" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Example" })).toBeVisible();
});
