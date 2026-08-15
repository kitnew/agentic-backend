import { PageHeader } from "../../components/page-states";
import { useTenant } from "../../core/tenant/use-tenant";

export function ExamplePage() {
  const { tenantId } = useTenant();
  return (
    <>
      <PageHeader title="Example" detail="A tenant-scoped proof feature." />
      <p className="text-sm">
        Tenant: <code>{tenantId}</code>
      </p>
    </>
  );
}
