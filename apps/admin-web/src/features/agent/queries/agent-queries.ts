import { responseData } from "../../../core/api/client";
import { readConfigAdminV1TenantsTenantIdAuthoringConfigGet } from "../../../core/api/generated/admin-authoring/admin-authoring";
import type { AuthoringState } from "../../../core/api/generated/models";

export const agentQueryKey = (tenantId: string) => [
  "admin",
  "tenant-authoring",
  tenantId,
  "config",
];

export async function getAgentConfiguration(tenantId: string) {
  return responseData<AuthoringState>(
    await readConfigAdminV1TenantsTenantIdAuthoringConfigGet(tenantId),
  );
}
