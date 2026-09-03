import { EmptyState } from "../../../components/page-states";
import { ControlPlaneJsonEditor } from "../../../core/configuration/control-plane";
import { useTenant } from "../../../core/tenant/use-tenant";

export function AgentPage() {
  const { tenantId } = useTenant();
  if (!tenantId) return <EmptyState title="Select a tenant" />;
  return (
    <ControlPlaneJsonEditor
      kind="agent.tenant"
      scope={{ type: "tenant", id: tenantId }}
      title="Agent"
      initialValue={{
        display_name: "",
        agent_profile: "",
        greeting: "",
        locale: "en-US",
        timezone: "UTC",
        conversation_scope: "property_only",
      }}
    />
  );
}
