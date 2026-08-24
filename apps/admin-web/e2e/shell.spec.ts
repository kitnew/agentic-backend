import { expect, test } from "@playwright/test";

const tenantId = "11111111-1111-4111-8111-111111111111";
const tenant = [
  {
    id: tenantId,
    slug: "demo",
    display_name: "Demo tenant",
    business_type: "hotel",
    status: "active",
    active_release_id: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
];

test("overview opens the tenant product workspace", async ({ page }) => {
  await page.route("**/admin/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/admin/v1/tenants") return route.fulfill({ json: tenant });
    if (
      path.endsWith("/config/revisions") ||
      path.endsWith("/tenant-prompt/revisions")
    )
      return route.fulfill({ json: [] });
    if (path.endsWith("/runtime"))
      return route.fulfill({
        json: { draft_revision: null, latest_published_revision: null },
      });
    if (path.endsWith("/knowledge-base"))
      return route.fulfill({
        json: {
          tenant_id: tenantId,
          draft_revision: null,
          latest_published_revision: null,
          published_documents: [],
        },
      });
    return route.fulfill({ status: 404, json: { detail: path } });
  });
  await page.goto("/");
  const main = page.getByRole("navigation", { name: "Main navigation" });
  await expect(main.getByRole("link")).toHaveCount(4);
  await page.getByRole("link", { name: "Demo tenant" }).click();
  await expect(page).toHaveURL(`/tenants/${tenantId}`);
  await expect(
    page
      .getByRole("navigation", { name: "Tenant navigation" })
      .getByRole("link"),
  ).toHaveCount(6);
  for (const label of [
    "Capabilities",
    "Integrations",
    "Post-call",
    "Telephony",
  ]) {
    const item = page.getByText(label, { exact: true });
    await expect(item.locator("xpath=..")).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await expect(item.locator("xpath=..")).toContainText("Coming later");
  }
  await page.goto(`/tenants/${tenantId}/integrations`);
  await expect(
    page.getByRole("heading", {
      name: "Feature temporarily unavailable in Admin Web",
    }),
  ).toBeVisible();
  await expect(page.getByText(tenantId)).toHaveCount(0);
});
