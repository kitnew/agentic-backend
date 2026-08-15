import { useQuery } from "@tanstack/react-query";
import { throwAdminResponse } from "../api/client";
import { listTenantsAdminV1TenantsGet } from "../api/generated/admin-tenants/admin-tenants";
import type { TenantResponse } from "../api/generated/models";

export type Tenant = TenantResponse;

export function useTenants() {
  return useQuery({
    queryKey: ["admin", "tenants"],
    queryFn: async () => {
      const response = await listTenantsAdminV1TenantsGet({ limit: 100 });
      if (response.status === 200) return response.data;
      return throwAdminResponse(response);
    },
  });
}
