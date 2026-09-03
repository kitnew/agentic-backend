import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  PageError,
  PageHeader,
  PageLoading,
} from "../../components/page-states";
import { responseData } from "../../core/api/client";
import {
  createIntegrationConnectionV1ManagedResourcesIntegrationConnectionsPost,
  listIntegrationConnectionsV1ManagedResourcesIntegrationConnectionsGet,
  setIntegrationConnectionEnabledV1ManagedResourcesIntegrationConnectionsResourceIdOperationPost,
  updateIntegrationConnectionV1ManagedResourcesIntegrationConnectionsResourceIdPut,
  validateIntegrationConnectionV1ManagedResourcesIntegrationConnectionsResourceIdValidatePost,
} from "../../core/api/control-plane";
import { useTenant } from "../../core/tenant/use-tenant";

export function IntegrationsPage() {
  const { tenantId } = useTenant();
  const [key, setKey] = useState("");
  const [config, setConfig] = useState('{"endpoint":"https://"}');
  const query = useQuery({
    queryKey: ["control-plane", "integrations", tenantId],
    enabled: Boolean(tenantId),
    queryFn: async () =>
      responseData<unknown[]>(
        await listIntegrationConnectionsV1ManagedResourcesIntegrationConnectionsGet(
          { tenant_id: tenantId },
        ),
      ),
  });
  const create = useMutation({
    mutationFn: async () =>
      responseData(
        await createIntegrationConnectionV1ManagedResourcesIntegrationConnectionsPost(
          {
            tenant_id: tenantId as string,
            key,
            integration_kind: "http",
            config: JSON.parse(config),
          },
        ),
      ),
    onSuccess: () => query.refetch(),
  });
  if (!tenantId) return <PageError title="Select a tenant first" />;
  if (query.isPending) return <PageLoading />;
  if (query.isError)
    return <PageError title="Integrations could not be loaded" />;
  return (
    <div className="space-y-6">
      <PageHeader
        title="Integrations"
        detail="HTTP IntegrationConnections are managed immediately by Control Plane."
      />
      <form
        className="space-y-3 rounded border p-4"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <label className="block text-sm">
          Key
          <input
            className="mt-1 block w-full rounded border p-2"
            value={key}
            onChange={(event) => setKey(event.target.value)}
          />
        </label>
        <label className="block text-sm">
          HTTP configuration JSON
          <textarea
            className="mt-1 block min-h-24 w-full rounded border p-2 font-mono"
            value={config}
            onChange={(event) => setConfig(event.target.value)}
          />
        </label>
        <button
          className="rounded bg-slate-950 px-3 py-2 text-sm text-white"
          disabled={!key || create.isPending}
          type="submit"
        >
          Create HTTP integration
        </button>
      </form>
      <ul className="divide-y border-y">
        {query.data.map((item) => {
          const resource = item as Record<string, unknown>;
          const id = String(
            resource.resource_id ?? resource.id ?? resource.key,
          );
          const generation = Number(resource.generation ?? 1);
          const enabled = resource.enabled !== false;
          return (
            <li
              className="flex flex-wrap items-center justify-between gap-3 py-3"
              key={id}
            >
              <span>
                <strong>{String(resource.key ?? id)}</strong>
                <span className="ml-2 text-sm text-muted">
                  {String(resource.integration_kind ?? "http")} ·{" "}
                  {enabled ? "Enabled" : "Disabled"}
                </span>
              </span>
              <span className="flex gap-2">
                <button
                  className="rounded border px-2 py-1 text-sm"
                  onClick={() =>
                    setIntegrationConnectionEnabledV1ManagedResourcesIntegrationConnectionsResourceIdOperationPost(
                      id,
                      enabled ? "disable" : "enable",
                      { expected_generation: generation },
                    ).then(() => query.refetch())
                  }
                  type="button"
                >
                  {enabled ? "Disable" : "Enable"}
                </button>
                <button
                  className="rounded border px-2 py-1 text-sm"
                  onClick={() =>
                    validateIntegrationConnectionV1ManagedResourcesIntegrationConnectionsResourceIdValidatePost(
                      id,
                    ).then(() => query.refetch())
                  }
                  type="button"
                >
                  Validate
                </button>
                <button
                  className="rounded border px-2 py-1 text-sm"
                  onClick={() =>
                    updateIntegrationConnectionV1ManagedResourcesIntegrationConnectionsResourceIdPut(
                      id,
                      {
                        config: resource.config as Record<string, unknown>,
                        credential_ref: resource.credential_ref as
                          | string
                          | null
                          | undefined,
                        expected_generation: generation,
                      },
                    ).then(() => query.refetch())
                  }
                  type="button"
                >
                  Save current
                </button>
              </span>
            </li>
          );
        })}
      </ul>
      {create.isError && (
        <PageError compact title="Integration could not be created" />
      )}
    </div>
  );
}
