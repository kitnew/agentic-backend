import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  PageError,
  PageHeader,
  PageLoading,
} from "../../components/page-states";
import { responseData } from "../../core/api/client";
import {
  createConnectionV1ManagedResourcesProviderConnectionsPost,
  createCredentialV1ManagedResourcesCredentialsPost,
  createDeploymentV1ManagedResourcesModelDeploymentsPost,
  listConnectionsV1ManagedResourcesProviderConnectionsGet,
  listCredentialsV1ManagedResourcesCredentialsGet,
  listDeploymentsV1ManagedResourcesModelDeploymentsGet,
  revokeCredentialV1ManagedResourcesCredentialsResourceIdRevokePost,
  rotateCredentialV1ManagedResourcesCredentialsResourceIdRotatePost,
  setConnectionEnabledV1ManagedResourcesProviderConnectionsResourceIdOperationPost,
  setDeploymentEnabledV1ManagedResourcesModelDeploymentsResourceIdOperationPost,
} from "../../core/api/control-plane";

export function PlatformProvidersPage() {
  const [name, setName] = useState("");
  const [secret, setSecret] = useState("");
  const [connectionJson, setConnectionJson] = useState('{"endpoint":""}');
  const [deploymentJson, setDeploymentJson] = useState('{"model":""}');
  const [connectionKey, setConnectionKey] = useState("");
  const [deploymentKey, setDeploymentKey] = useState("");
  const [credentialRef, setCredentialRef] = useState("");
  const [connectionRef, setConnectionRef] = useState("");
  const [deploymentKind, setDeploymentKind] = useState<
    "llm" | "realtime" | "stt" | "tts"
  >("llm");
  const query = useQuery({
    queryKey: ["control-plane", "providers"],
    queryFn: async () =>
      Promise.all([
        responseData<unknown[]>(
          await listCredentialsV1ManagedResourcesCredentialsGet(),
        ),
        responseData<unknown[]>(
          await listConnectionsV1ManagedResourcesProviderConnectionsGet(),
        ),
        responseData<unknown[]>(
          await listDeploymentsV1ManagedResourcesModelDeploymentsGet(),
        ),
      ]),
  });
  const create = useMutation({
    mutationFn: () =>
      createCredentialV1ManagedResourcesCredentialsPost({ name, secret }),
    onSuccess: () => {
      setSecret("");
      query.refetch();
    },
  });
  const createConnection = useMutation({
    mutationFn: () =>
      createConnectionV1ManagedResourcesProviderConnectionsPost({
        key: connectionKey,
        provider_kind: "openai",
        credential_ref: credentialRef,
        connection_config: JSON.parse(connectionJson),
        enabled: true,
      }),
    onSuccess: () => query.refetch(),
  });
  const createDeployment = useMutation({
    mutationFn: () =>
      createDeploymentV1ManagedResourcesModelDeploymentsPost({
        key: deploymentKey,
        connection_ref: connectionRef,
        deployment_kind: deploymentKind,
        deployment_config: JSON.parse(deploymentJson),
        enabled: true,
      }),
    onSuccess: () => query.refetch(),
  });
  if (query.isPending) return <PageLoading />;
  if (query.isError) return <PageError title="Providers could not be loaded" />;
  const [credentials, connections, deployments] = query.data;
  return (
    <div className="space-y-6">
      <PageHeader
        title="Providers"
        detail="Credential secrets are write-only; connections and deployments are managed by Control Plane."
      />
      <form
        className="space-y-3 rounded border p-4"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <label className="block text-sm">
          Credential name
          <input
            className="mt-1 block w-full rounded border p-2"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="block text-sm">
          Secret
          <input
            className="mt-1 block w-full rounded border p-2"
            type="password"
            value={secret}
            onChange={(event) => setSecret(event.target.value)}
          />
        </label>
        <button
          className="rounded bg-slate-950 px-3 py-2 text-sm text-white"
          disabled={!name || !secret || create.isPending}
          type="submit"
        >
          Create credential
        </button>
      </form>
      <form
        className="grid gap-3 rounded border p-4 md:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault();
          createConnection.mutate();
        }}
      >
        <h2 className="md:col-span-2 text-lg font-semibold">
          Create provider connection
        </h2>
        <input
          aria-label="Connection key"
          className="rounded border p-2"
          placeholder="Key"
          value={connectionKey}
          onChange={(event) => setConnectionKey(event.target.value)}
        />
        <input
          aria-label="Credential reference"
          className="rounded border p-2"
          placeholder="Credential reference"
          value={credentialRef}
          onChange={(event) => setCredentialRef(event.target.value)}
        />
        <textarea
          aria-label="Connection config"
          className="min-h-20 rounded border p-2 font-mono md:col-span-2"
          value={connectionJson}
          onChange={(event) => setConnectionJson(event.target.value)}
        />
        <button
          className="rounded bg-slate-950 px-3 py-2 text-sm text-white md:col-span-2"
          disabled={
            !connectionKey || !credentialRef || createConnection.isPending
          }
          type="submit"
        >
          Create connection
        </button>
      </form>
      <form
        className="grid gap-3 rounded border p-4 md:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault();
          createDeployment.mutate();
        }}
      >
        <h2 className="md:col-span-2 text-lg font-semibold">
          Create model deployment
        </h2>
        <input
          aria-label="Deployment key"
          className="rounded border p-2"
          placeholder="Key"
          value={deploymentKey}
          onChange={(event) => setDeploymentKey(event.target.value)}
        />
        <input
          aria-label="Connection reference"
          className="rounded border p-2"
          placeholder="Connection reference"
          value={connectionRef}
          onChange={(event) => setConnectionRef(event.target.value)}
        />
        <select
          aria-label="Deployment kind"
          className="rounded border p-2"
          value={deploymentKind}
          onChange={(event) =>
            setDeploymentKind(event.target.value as typeof deploymentKind)
          }
        >
          <option value="llm">LLM</option>
          <option value="realtime">Realtime</option>
          <option value="stt">STT</option>
          <option value="tts">TTS</option>
        </select>
        <textarea
          aria-label="Deployment config"
          className="min-h-20 rounded border p-2 font-mono md:col-span-2"
          value={deploymentJson}
          onChange={(event) => setDeploymentJson(event.target.value)}
        />
        <button
          className="rounded bg-slate-950 px-3 py-2 text-sm text-white md:col-span-2"
          disabled={
            !deploymentKey || !connectionRef || createDeployment.isPending
          }
          type="submit"
        >
          Create deployment
        </button>
      </form>
      <ProviderList title="Credentials" items={credentials} />
      <ProviderList
        title="Provider Connections"
        items={connections}
        onToggle={(resource, operation) =>
          setConnectionEnabledV1ManagedResourcesProviderConnectionsResourceIdOperationPost(
            String(resource.resource_id ?? resource.id),
            operation,
            { expected_generation: Number(resource.generation ?? 1) },
          ).then(() => query.refetch())
        }
      />
      <ProviderList
        title="Model Deployments"
        items={deployments}
        onToggle={(resource, operation) =>
          setDeploymentEnabledV1ManagedResourcesModelDeploymentsResourceIdOperationPost(
            String(resource.resource_id ?? resource.id),
            operation,
            { expected_generation: Number(resource.generation ?? 1) },
          ).then(() => query.refetch())
        }
      />
      <CredentialList items={credentials} onRefresh={() => query.refetch()} />
      {create.isError && (
        <PageError compact title="Credential could not be created" />
      )}
    </div>
  );
}

function ProviderList({
  title,
  items,
  onToggle,
}: {
  title: string;
  items: unknown[];
  onToggle?: (
    resource: Record<string, unknown>,
    operation: "enable" | "disable",
  ) => void;
}) {
  return (
    <section>
      <h2 className="mb-2 text-lg font-semibold">{title}</h2>
      <ul className="divide-y border-y">
        {items.map((item) => {
          const resource = item as Record<string, unknown>;
          const enabled = resource.enabled !== false;
          return (
            <li
              className="flex items-center justify-between gap-3 py-3"
              key={String(
                resource.resource_id ?? resource.id ?? JSON.stringify(item),
              )}
            >
              <span>
                {String(
                  resource.key ??
                    resource.name ??
                    resource.resource_id ??
                    "resource",
                )}{" "}
                <span className="text-sm text-muted">
                  {enabled ? "Enabled" : "Disabled"}
                </span>
              </span>
              {onToggle && (
                <button
                  className="rounded border px-2 py-1 text-sm"
                  onClick={() =>
                    onToggle(resource, enabled ? "disable" : "enable")
                  }
                  type="button"
                >
                  {enabled ? "Disable" : "Enable"}
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function CredentialList({
  items,
  onRefresh,
}: {
  items: unknown[];
  onRefresh: () => void;
}) {
  return (
    <section>
      <h2 className="mb-2 text-lg font-semibold">Credential actions</h2>
      <ul className="divide-y border-y">
        {items.map((item) => {
          const resource = item as Record<string, unknown>;
          const id = String(resource.resource_id ?? resource.id);
          const generation = Number(resource.generation ?? 1);
          return (
            <li
              className="flex items-center justify-between gap-3 py-3"
              key={id}
            >
              <span>
                {String(resource.name ?? id)}{" "}
                <span className="text-sm text-muted">
                  Secret never returned
                </span>
              </span>
              <span className="flex gap-2">
                <button
                  className="rounded border px-2 py-1 text-sm"
                  onClick={() =>
                    rotateCredentialV1ManagedResourcesCredentialsResourceIdRotatePost(
                      id,
                      { secret: window.prompt("New secret") ?? "" },
                      { headers: { "If-Match": `"${generation}"` } },
                    ).then(onRefresh)
                  }
                  type="button"
                >
                  Rotate
                </button>
                <button
                  className="rounded border px-2 py-1 text-sm"
                  onClick={() =>
                    revokeCredentialV1ManagedResourcesCredentialsResourceIdRevokePost(
                      id,
                      {},
                    ).then(onRefresh)
                  }
                  type="button"
                >
                  Revoke
                </button>
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
