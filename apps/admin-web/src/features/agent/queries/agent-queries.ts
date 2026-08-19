import { useQuery } from "@tanstack/react-query";

import { throwAdminResponse } from "../../../core/api/client";
import {
  listProfilePromptRevisionsAdminV1PlatformPromptsProfilesKeyRevisionsGet,
  listProfilesAdminV1PlatformPromptsProfilesGet,
  listSystemPromptRevisionsAdminV1PlatformPromptsSystemKeyRevisionsGet,
} from "../../../core/api/generated/admin-platform-prompts/admin-platform-prompts";
import { showTenantRuntimeAdminV1TenantsTenantIdRuntimeGet } from "../../../core/api/generated/admin-tenant-runtime/admin-tenant-runtime";
import {
  getActiveConfigAdminV1TenantsTenantIdConfigActiveGet,
  listConfigRevisionsAdminV1TenantsTenantIdConfigRevisionsGet,
  listTenantPromptRevisionsAdminV1TenantsTenantIdTenantPromptRevisionsGet,
} from "../../../core/api/generated/admin-tenants/admin-tenants";
import type {
  ActiveTenantConfig,
  ConfigRevisionResponse,
  PromptTextRevisionResponse,
  TenantPromptRevisionResponse,
  TenantRuntimeStateResponse,
} from "../../../core/api/generated/models";
import { editableTenantConfig } from "../lib/mappings";

export const agentQueryKey = (tenantId: string) => ["admin", "agent", tenantId];

function data(response: {
  status: number;
  data: unknown;
  headers: Headers;
}): unknown {
  if (response.status >= 200 && response.status < 300) return response.data;
  return throwAdminResponse(response);
}

export async function getAgentConfiguration(tenantId: string) {
  const [active, revisions, prompts, runtime, profiles, system] =
    await Promise.all([
      getActiveConfigAdminV1TenantsTenantIdConfigActiveGet(tenantId),
      listConfigRevisionsAdminV1TenantsTenantIdConfigRevisionsGet(tenantId),
      listTenantPromptRevisionsAdminV1TenantsTenantIdTenantPromptRevisionsGet(
        tenantId,
      ),
      showTenantRuntimeAdminV1TenantsTenantIdRuntimeGet(tenantId),
      listProfilesAdminV1PlatformPromptsProfilesGet(),
      listSystemPromptRevisionsAdminV1PlatformPromptsSystemKeyRevisionsGet(
        "default",
      ),
    ]);
  const activeConfig = data(active) as ActiveTenantConfig;
  const configRevisions = data(revisions) as ConfigRevisionResponse[];
  const promptRevisions = data(prompts) as TenantPromptRevisionResponse[];
  const systemRevisions = data(system) as PromptTextRevisionResponse[];
  const draft = configRevisions.find((revision) => revision.status === "draft");
  const config = editableTenantConfig(draft ?? activeConfig);
  if (!config)
    throw new Error("This tenant configuration cannot be edited by Agent V1");
  const profile =
    await listProfilePromptRevisionsAdminV1PlatformPromptsProfilesKeyRevisionsGet(
      config.agent.profile,
    );
  return {
    activeConfig,
    config,
    configDraft: draft,
    prompt:
      promptRevisions.find((revision) => revision.status === "draft") ??
      promptRevisions.find((revision) => revision.status === "published"),
    runtime: data(runtime) as TenantRuntimeStateResponse,
    profiles: data(profiles) as string[],
    systemPrompt: systemRevisions.find(
      (revision) => revision.status === "published",
    )?.text,
    profilePrompt: (data(profile) as PromptTextRevisionResponse[]).find(
      (revision) => revision.status === "published",
    )?.text,
  };
}

export function useAgentConfiguration(tenantId: string) {
  return useQuery({
    queryKey: agentQueryKey(tenantId),
    queryFn: () => getAgentConfiguration(tenantId),
  });
}
