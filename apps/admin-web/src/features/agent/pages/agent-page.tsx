import { EmptyState } from "../../../components/page-states";
import { TenantConfigurationEditor } from "../../../core/configuration/high-level";
import { useTenant } from "../../../core/tenant/use-tenant";

export function AgentPage() {
  const { tenantId } = useTenant();
  if (!tenantId) return <EmptyState title="Select a tenant" />;
  return <TenantConfigurationEditor tenantId={tenantId} />;
}
