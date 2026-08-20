import { useQuery } from "@tanstack/react-query";

import { responseData } from "../../../core/api/client";
import { listProfilesAdminV1PlatformPromptsProfilesGet } from "../../../core/api/generated/admin-platform-prompts/admin-platform-prompts";
import {
  getActiveConfigAdminV1TenantsTenantIdConfigActiveGet,
  listConfigRevisionsAdminV1TenantsTenantIdConfigRevisionsGet,
} from "../../../core/api/generated/admin-tenants/admin-tenants";
import type {
  ActiveTenantConfig,
  ConfigRevisionResponse,
} from "../../../core/api/generated/models";
import { editableTenantConfig } from "../lib/mappings";

export const agentQueryKey = (tenantId: string) => ["admin", "agent", tenantId];

export async function getAgentConfiguration(tenantId: string) {
  const [active, revisions, profiles] = await Promise.all([
    getActiveConfigAdminV1TenantsTenantIdConfigActiveGet(tenantId),
    listConfigRevisionsAdminV1TenantsTenantIdConfigRevisionsGet(tenantId),
    listProfilesAdminV1PlatformPromptsProfilesGet(),
  ]);
  const activeConfig = responseData<ActiveTenantConfig>(active);
  const configRevisions = responseData<ConfigRevisionResponse[]>(revisions);
  const draft = configRevisions.find((revision) => revision.status === "draft");
  const config = editableTenantConfig(draft ?? activeConfig);
  if (!config) throw new Error("This tenant configuration cannot be edited");
  return {
    activeConfig,
    config,
    configDraft: draft,
    profiles: responseData<string[]>(profiles),
  };
}

export function useAgentConfiguration(tenantId: string) {
  return useQuery({
    queryKey: agentQueryKey(tenantId),
    queryFn: () => getAgentConfiguration(tenantId),
  });
}
