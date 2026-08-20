import { Link } from "@tanstack/react-router";

import {
  PageError,
  PageHeader,
  PageLoading,
} from "../../components/page-states";
import { useTenants } from "../../core/tenant/use-tenants";

export function OverviewPage() {
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
      <PageHeader title="Overview" />
      <h2 className="mb-4 text-lg font-semibold">Tenants</h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {tenants.data.map((tenant) => (
          <Link
            className="flex min-h-52 flex-col rounded-lg border bg-panel p-5 transition hover:border-slate-400 hover:shadow-sm"
            key={tenant.id}
            to={`/tenants/${tenant.id}` as never}
          >
            <h3 className="text-lg font-semibold">{tenant.display_name}</h3>
            <p className="mt-2 text-sm capitalize text-muted">
              {tenant.business_type.replaceAll("_", " ")}
            </p>
            <p className="mt-4 text-sm font-medium capitalize">
              {tenant.status.replaceAll("_", " ")}
            </p>
            <p className="mt-auto pt-6 text-sm font-medium">Open →</p>
          </Link>
        ))}
      </div>
    </>
  );
}
