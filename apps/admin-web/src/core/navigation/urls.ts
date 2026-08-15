import type { NavigationItem } from "./registry";

export function navigationUrl(item: NavigationItem, tenantId?: string) {
  if (item.scope === "global") return item.to;
  if (!tenantId) return undefined;
  return item.to.replace("$tenantId", tenantId);
}
