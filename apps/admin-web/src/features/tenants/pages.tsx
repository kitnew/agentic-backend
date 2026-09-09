import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import {
  PageError,
  PageHeader,
  PageLoading,
} from "../../components/page-states";
import { responseData } from "../../core/api/client";
import { createTenantAdminV1TenantsPost } from "../../core/api/generated/admin-tenants/admin-tenants";
import type { TenantResponse } from "../../core/api/generated/models";
import { useTenants } from "../../core/tenant/use-tenants";

export function TenantsPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const tenants = useTenants();
  const [slug, setSlug] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [businessType, setBusinessType] = useState("");
  const createTenant = useMutation({
    mutationFn: async () =>
      responseData<TenantResponse>(
        await createTenantAdminV1TenantsPost({
          slug,
          display_name: displayName,
          business_type: businessType,
        }),
      ),
    onSuccess: async (tenant) => {
      await queryClient.invalidateQueries({ queryKey: ["admin", "tenants"] });
      await navigate({ to: `/tenants/${tenant.id}/configuration` as never });
    },
  });
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
      <form
        className="mb-6 grid gap-3 rounded border p-4 md:grid-cols-3"
        onSubmit={(event) => {
          event.preventDefault();
          createTenant.mutate();
        }}
      >
        <h2 className="md:col-span-3 text-lg font-semibold">Create tenant</h2>
        <input
          aria-label="Tenant slug"
          className="rounded border p-2"
          placeholder="Slug"
          value={slug}
          onChange={(event) => setSlug(event.target.value)}
        />
        <input
          aria-label="Display name"
          className="rounded border p-2"
          placeholder="Display name"
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
        />
        <input
          aria-label="Business type"
          className="rounded border p-2"
          placeholder="Business type"
          value={businessType}
          onChange={(event) => setBusinessType(event.target.value)}
        />
        <button
          className="rounded bg-slate-950 px-3 py-2 text-sm text-white md:col-span-3"
          disabled={
            !slug || !displayName || !businessType || createTenant.isPending
          }
          type="submit"
        >
          Create tenant
        </button>
        {createTenant.isError && (
          <PageError
            compact
            error={createTenant.error}
            title="Tenant could not be created"
          />
        )}
      </form>
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
