import { useParams } from "@tanstack/react-router";

export function useTenant() {
  const params = useParams({ strict: false });
  const tenantId =
    "tenantId" in params && typeof params.tenantId === "string"
      ? params.tenantId
      : undefined;
  return { tenantId, isTenantScope: tenantId !== undefined };
}
