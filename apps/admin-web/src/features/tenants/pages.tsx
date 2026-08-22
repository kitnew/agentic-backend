import { Link } from "@tanstack/react-router";

import {
  PageError,
  PageHeader,
  PageLoading,
} from "../../components/page-states";
import { useTenants } from "../../core/tenant/use-tenants";

export function TenantsPage() {
  const tenants = useTenants();
  if (tenants.isPending) return <PageLoading />;
  if (tenants.isError)
    return (
      <PageError
        title="Tenants could not be loaded"
        onRetry={() => tenants.refetch()}
      />
    );
  return (
    <>
      <PageHeader title="Tenants" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {tenants.data.map((tenant) => (
          <Link
            className="rounded-lg border bg-panel p-5 transition hover:border-slate-400 hover:shadow-sm"
            key={tenant.id}
            to={`/tenants/${tenant.id}` as never}
          >
            <h2 className="font-semibold">{tenant.display_name}</h2>
            <p className="mt-1 text-sm capitalize text-muted">
              {tenant.business_type.replaceAll("_", " ")}
            </p>
            <p className="mt-7 text-sm font-medium">Open →</p>
          </Link>
        ))}
      </div>
    </>
  );
}
