import { useQuery } from "@tanstack/react-query";
import { throwAdminResponse } from "../api/client";
import { listTenantsAdminV1TenantsGet } from "../api/generated/admin-tenants/admin-tenants";
import type { TenantResponse } from "../api/generated/models";

export type Tenant = TenantResponse;

export function useTenants() {
  return useQuery({
    queryKey: ["admin", "tenants"],
    queryFn: async () => {
      const pageSize = 100;
      const tenants: Tenant[] = [];
      for (let offset = 0; ; offset += pageSize) {
        const response = await listTenantsAdminV1TenantsGet({
          limit: pageSize,
          offset,
        });
        if (response.status !== 200) return throwAdminResponse(response);
        tenants.push(...response.data);
        if (response.data.length < pageSize) return tenants;
      }
    },
  });
}
