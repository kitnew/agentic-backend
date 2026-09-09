import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  PageError,
  PageHeader,
  PageLoading,
} from "../../components/page-states";
import { managementMutationOptions, responseData } from "../../core/api/client";
import type {
  CredentialResponse,
  ModelDeploymentCreate,
  ModelDeploymentResponse,
  ProviderConnectionCreateConnectionConfig,
  ProviderConnectionResponse,
  RegistryEntryResponse,
} from "../../core/api/control-plane";
import {
  createConnectionManagementV1ProvidersConnectionsPost,
  createCredentialManagementV1CredentialsPost,
  createDeploymentManagementV1ProvidersDeploymentsPost,
  deploymentKindsManagementV1RegistriesDeploymentKindsGet,
  disableConnectionManagementV1ProvidersConnectionsIdDisablePost,
  disableDeploymentManagementV1ProvidersDeploymentsIdDisablePost,
  enableConnectionManagementV1ProvidersConnectionsIdEnablePost,
  enableDeploymentManagementV1ProvidersDeploymentsIdEnablePost,
  getConnectionManagementV1ProvidersConnectionsIdGet,
  getDeploymentManagementV1ProvidersDeploymentsIdGet,
  listConnectionsManagementV1ProvidersConnectionsGet,
  listCredentialsManagementV1CredentialsGet,
  listDeploymentsManagementV1ProvidersDeploymentsGet,
  providerKindsManagementV1RegistriesProviderKindsGet,
} from "../../core/api/control-plane";

type ProviderData = {
  credentials: CredentialResponse[];
  connections: ProviderConnectionResponse[];
  deployments: ModelDeploymentResponse[];
  providerKinds: RegistryEntryResponse[];
  deploymentKinds: RegistryEntryResponse[];
};

type ToggleInput = {
  id: string;
  resource: "connection" | "deployment";
  operation: "enable" | "disable";
};

function parseJson(value: string, label: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    throw new Error(`${label} must be valid JSON.`);
  }
}

export function PlatformProvidersPage() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [secret, setSecret] = useState("");
  const [connectionKey, setConnectionKey] = useState("");
  const [providerKind, setProviderKind] = useState("");
  const [credentialRef, setCredentialRef] = useState("");
  const [connectionJson, setConnectionJson] = useState("{}");
  const [deploymentKey, setDeploymentKey] = useState("");
  const [connectionRef, setConnectionRef] = useState("");
  const [deploymentKind, setDeploymentKind] = useState("");
  const [deploymentJson, setDeploymentJson] = useState("{}");
  const [capabilitiesJson, setCapabilitiesJson] = useState("{}");

  const query = useQuery({
    queryKey: ["control-plane", "providers"],
    queryFn: async (): Promise<ProviderData> => {
      const [
        credentials,
        connections,
        deployments,
        providerKinds,
        deploymentKinds,
      ] = await Promise.all([
        responseData<CredentialResponse[]>(
          await listCredentialsManagementV1CredentialsGet({
            scope_type: "platform",
          }),
        ),
        responseData<ProviderConnectionResponse[]>(
          await listConnectionsManagementV1ProvidersConnectionsGet(),
        ),
        responseData<ModelDeploymentResponse[]>(
          await listDeploymentsManagementV1ProvidersDeploymentsGet(),
        ),
        responseData<RegistryEntryResponse[]>(
          await providerKindsManagementV1RegistriesProviderKindsGet(),
        ),
        responseData<RegistryEntryResponse[]>(
          await deploymentKindsManagementV1RegistriesDeploymentKindsGet(),
        ),
      ]);
      return {
        credentials,
        connections,
        deployments,
        providerKinds,
        deploymentKinds,
      };
    },
  });

  const createCredential = useMutation({
    mutationFn: async () =>
      responseData(
        await createCredentialManagementV1CredentialsPost(
          { name, secret, scope: { type: "platform" } },
          managementMutationOptions(),
        ),
      ),
    onSuccess: async () => {
      setSecret("");
      await queryClient.invalidateQueries({
        queryKey: ["control-plane", "providers"],
      });
    },
  });

  const createConnection = useMutation({
    mutationFn: async () =>
      responseData(
        await createConnectionManagementV1ProvidersConnectionsPost(
          {
            key: connectionKey,
            provider_kind: providerKind,
            credential_ref: credentialRef,
            connection_config: parseJson(
              connectionJson,
              "Connection config",
            ) as ProviderConnectionCreateConnectionConfig,
          },
          managementMutationOptions(),
        ),
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["control-plane", "providers"],
      });
    },
  });

  const createDeployment = useMutation({
    mutationFn: async () =>
      responseData(
        await createDeploymentManagementV1ProvidersDeploymentsPost(
          {
            key: deploymentKey,
            connection_ref: connectionRef,
            deployment_kind:
              deploymentKind as ModelDeploymentCreate["deployment_kind"],
            deployment_config: parseJson(
              deploymentJson,
              "Deployment config",
            ) as ModelDeploymentCreate["deployment_config"],
            capabilities: parseJson(
              capabilitiesJson,
              "Capabilities",
            ) as ModelDeploymentCreate["capabilities"],
          },
          managementMutationOptions(),
        ),
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["control-plane", "providers"],
      });
    },
  });

  const toggle = useMutation({
    mutationFn: async ({ id, resource, operation }: ToggleInput) => {
      const current =
        resource === "connection"
          ? await getConnectionManagementV1ProvidersConnectionsIdGet(id)
          : await getDeploymentManagementV1ProvidersDeploymentsIdGet(id);
      responseData(current);
      const mutation =
        resource === "connection"
          ? operation === "enable"
            ? enableConnectionManagementV1ProvidersConnectionsIdEnablePost
            : disableConnectionManagementV1ProvidersConnectionsIdDisablePost
          : operation === "enable"
            ? enableDeploymentManagementV1ProvidersDeploymentsIdEnablePost
            : disableDeploymentManagementV1ProvidersDeploymentsIdDisablePost;
      return responseData(
        await mutation(
          id,
          managementMutationOptions(current.headers.get("etag")),
        ),
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["control-plane", "providers"],
      });
    },
  });

  if (query.isPending) return <PageLoading />;
  if (query.isError)
    return (
      <PageError
        title="Providers could not be loaded"
        error={query.error}
        onRetry={() => query.refetch()}
      />
    );

  const {
    credentials,
    connections,
    deployments,
    providerKinds,
    deploymentKinds,
  } = query.data;
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
          createCredential.mutate();
        }}
      >
        <h2 className="text-lg font-semibold">Credentials</h2>
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
          disabled={!name || !secret || createCredential.isPending}
          type="submit"
        >
          Create credential
        </button>
        {createCredential.isError && (
          <PageError
            compact
            error={createCredential.error}
            title="Credential could not be created"
          />
        )}
      </form>

      <form
        className="grid gap-3 rounded border p-4 md:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault();
          createConnection.mutate();
        }}
      >
        <h2 className="md:col-span-2 text-lg font-semibold">
          Provider Connections
        </h2>
        <input
          aria-label="Connection key"
          className="rounded border p-2"
          placeholder="Key"
          value={connectionKey}
          onChange={(event) => setConnectionKey(event.target.value)}
        />
        <select
          aria-label="Provider kind"
          className="rounded border p-2"
          value={providerKind}
          onChange={(event) => setProviderKind(event.target.value)}
        >
          <option value="">Select provider kind</option>
          {providerKinds.map((kind) => (
            <option key={kind.key} value={kind.key}>
              {kind.name} ({kind.key})
            </option>
          ))}
        </select>
        <select
          aria-label="Credential"
          className="rounded border p-2"
          value={credentialRef}
          onChange={(event) => setCredentialRef(event.target.value)}
        >
          <option value="">Select platform credential</option>
          {credentials.map((credential) => (
            <option key={credential.id} value={credential.id}>
              {credential.name} ({credential.id.slice(0, 8)})
            </option>
          ))}
        </select>
        <textarea
          aria-label="Connection config"
          className="min-h-20 rounded border p-2 font-mono md:col-span-2"
          value={connectionJson}
          onChange={(event) => setConnectionJson(event.target.value)}
        />
        <button
          className="rounded bg-slate-950 px-3 py-2 text-sm text-white md:col-span-2"
          disabled={
            !connectionKey ||
            !providerKind ||
            !credentialRef ||
            createConnection.isPending
          }
          type="submit"
        >
          Create connection
        </button>
        {createConnection.isError && (
          <PageError
            compact
            error={createConnection.error}
            title="Provider connection could not be created"
          />
        )}
      </form>

      <form
        className="grid gap-3 rounded border p-4 md:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault();
          createDeployment.mutate();
        }}
      >
        <h2 className="md:col-span-2 text-lg font-semibold">
          Model Deployments
        </h2>
        <input
          aria-label="Deployment key"
          className="rounded border p-2"
          placeholder="Key"
          value={deploymentKey}
          onChange={(event) => setDeploymentKey(event.target.value)}
        />
        <select
          aria-label="Connection"
          className="rounded border p-2"
          value={connectionRef}
          onChange={(event) => setConnectionRef(event.target.value)}
        >
          <option value="">Select provider connection</option>
          {connections.map((connection) => (
            <option key={connection.id} value={connection.id}>
              {connection.key} ({connection.id.slice(0, 8)})
            </option>
          ))}
        </select>
        <select
          aria-label="Deployment kind"
          className="rounded border p-2"
          value={deploymentKind}
          onChange={(event) => setDeploymentKind(event.target.value)}
        >
          <option value="">Select deployment kind</option>
          {deploymentKinds.map((kind) => (
            <option key={kind.key} value={kind.key}>
              {kind.name} ({kind.key})
            </option>
          ))}
        </select>
        <textarea
          aria-label="Deployment config"
          className="min-h-20 rounded border p-2 font-mono md:col-span-2"
          value={deploymentJson}
          onChange={(event) => setDeploymentJson(event.target.value)}
        />
        <textarea
          aria-label="Capabilities"
          className="min-h-20 rounded border p-2 font-mono md:col-span-2"
          value={capabilitiesJson}
          onChange={(event) => setCapabilitiesJson(event.target.value)}
        />
        <button
          className="rounded bg-slate-950 px-3 py-2 text-sm text-white md:col-span-2"
          disabled={
            !deploymentKey ||
            !connectionRef ||
            !deploymentKind ||
            createDeployment.isPending
          }
          type="submit"
        >
          Create deployment
        </button>
        {createDeployment.isError && (
          <PageError
            compact
            error={createDeployment.error}
            title="Model deployment could not be created"
          />
        )}
      </form>

      <ResourceList
        title="Provider Connections"
        items={connections}
        onToggle={(resource, operation) =>
          toggle.mutate({ id: resource.id, resource: "connection", operation })
        }
      />
      <ResourceList
        title="Model Deployments"
        items={deployments}
        onToggle={(resource, operation) =>
          toggle.mutate({ id: resource.id, resource: "deployment", operation })
        }
      />
      {toggle.isError && (
        <PageError
          compact
          error={toggle.error}
          onRetry={() => query.refetch()}
          title="Provider resource action failed"
        />
      )}

      <section>
        <h2 className="mb-2 text-lg font-semibold">Credential inventory</h2>
        <ul className="divide-y border-y">
          {credentials.map((credential) => (
            <li className="py-3" key={credential.id}>
              {credential.name}{" "}
              <span className="text-sm text-muted">Secret never returned</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function ResourceList<T extends { id: string; key: string; enabled: boolean }>({
  title,
  items,
  onToggle,
}: {
  title: string;
  items: T[];
  onToggle: (resource: T, operation: "enable" | "disable") => void;
}) {
  return (
    <section>
      <h2 className="mb-2 text-lg font-semibold">{title}</h2>
      <ul className="divide-y border-y">
        {items.map((resource) => (
          <li
            className="flex items-center justify-between gap-3 py-3"
            key={resource.id}
          >
            <span>
              {resource.key}{" "}
              <span className="text-sm text-muted">
                {resource.enabled ? "Enabled" : "Disabled"}
              </span>
            </span>
            <button
              className="rounded border px-2 py-1 text-sm"
              onClick={() =>
                onToggle(resource, resource.enabled ? "disable" : "enable")
              }
              type="button"
            >
              {resource.enabled ? "Disable" : "Enable"}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
