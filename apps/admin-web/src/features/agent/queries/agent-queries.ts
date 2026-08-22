import { useQuery } from "@tanstack/react-query";

import { responseData } from "../../../core/api/client";
import { componentStateAdminV1TenantsTenantIdComponentsComponentGet } from "../../../core/api/generated/admin-tenant-components/admin-tenant-components";
import type { ComponentStateResponse } from "../../../core/api/generated/models";
import { editableAgentComponent } from "../lib/mappings";

export const agentQueryKey = (tenantId: string) => ["admin", "agent", tenantId];

export async function getAgentConfiguration(tenantId: string) {
  const state = responseData<ComponentStateResponse>(
    await componentStateAdminV1TenantsTenantIdComponentsComponentGet(
      tenantId,
      "agent",
    ),
  );
  const config = editableAgentComponent(
    state.draft?.payload ?? state.active_revision?.payload,
  );
  if (!config) throw new Error("Agent component has not been configured");
  return {
    config,
    configDraft: state.draft,
  };
}

export function useAgentConfiguration(tenantId: string) {
  return useQuery({
    queryKey: agentQueryKey(tenantId),
    queryFn: () => getAgentConfiguration(tenantId),
  });
}
