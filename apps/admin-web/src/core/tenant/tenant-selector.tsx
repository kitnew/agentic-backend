import { useNavigate } from "@tanstack/react-router";
import { PageError } from "../../components/page-states";
import { Select } from "../../components/ui/select";
import { useTenant } from "./use-tenant";
import { useTenants } from "./use-tenants";

export function TenantSelector() {
  const navigate = useNavigate();
  const { tenantId } = useTenant();
  const tenants = useTenants();
  if (tenants.isPending)
    return <p className="text-sm text-muted">Loading tenants…</p>;
  if (tenants.isError)
    return (
      <PageError
        compact
        title="Tenant list unavailable"
        onRetry={() => tenants.refetch()}
      />
    );
  if (tenants.data.length === 0)
    return <p className="text-sm text-muted">No tenants</p>;
  return (
    <label className="block text-sm font-medium" htmlFor="tenant-selector">
      Tenant
      <Select
        aria-label="Tenant"
        className="mt-1"
        id="tenant-selector"
        onChange={(event) => {
          const selected = event.target.value;
          const suffix = tenantId
            ? location.pathname
                .replace(tenantId, selected)
                .replace(location.search, "")
            : `/tenants/${selected}/example`;
          void navigate({ to: suffix });
        }}
        value={tenantId ?? ""}
      >
        {!tenantId && (
          <option value="" disabled>
            Select a tenant
          </option>
        )}
        {tenants.data.map((tenant) => (
          <option key={tenant.id} value={tenant.id}>
            {tenant.display_name}
          </option>
        ))}
      </Select>
    </label>
  );
}
