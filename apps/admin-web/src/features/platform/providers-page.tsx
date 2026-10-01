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
  updateConnectionManagementV1ProvidersConnectionsIdPut,
  updateDeploymentManagementV1ProvidersDeploymentsIdPut,
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

type ConfigField = {
  name: string;
  label: string;
  type?: "text" | "url" | "number";
  required?: boolean;
  min?: number;
  max?: number;
  step?: number | "any";
  defaultValue?: string;
  staticValue?: string;
};

const connectionFields: Record<string, ConfigField[]> = {
  azure_openai: [
    {
      name: "endpoint",
      label: "Azure OpenAI endpoint",
      type: "url",
      required: true,
    },
    { name: "api_version", label: "API version" },
  ],
};

const deploymentFields: Record<string, Record<string, ConfigField[]>> = {
  azure_openai: {
    llm: [
      {
        name: "deployment_name",
        label: "Azure deployment name",
        required: true,
      },
      { name: "model", label: "Model", required: true },
      { name: "api_version", label: "API version", required: true },
    ],
    realtime: [
      {
        name: "deployment_name",
        label: "Azure deployment name",
        required: true,
      },
    ],
    stt: [
      {
        name: "deployment_name",
        label: "Azure deployment name",
        required: true,
      },
      { name: "model", label: "Model", required: true },
    ],
  },
  openai: {
    llm: [{ name: "model", label: "Model", required: true }],
  },
  elevenlabs: {
    stt: [{ name: "model_id", label: "Model ID", required: true }],
    tts: [{ name: "model_id", label: "Model ID", required: true }],
  },
  deepgram: {
    stt: [{ name: "model_id", label: "Model ID", required: true }],
  },
  soniox: {
    stt: [
      {
        name: "model",
        label: "Soniox model",
        staticValue: "stt-rt-v5",
      },
      {
        name: "max_endpoint_delay_ms",
        label: "Soniox maximum endpoint delay",
        type: "number",
        min: 500,
        max: 3000,
        defaultValue: "2000",
        required: true,
      },
      {
        name: "endpoint_sensitivity",
        label: "Soniox endpoint sensitivity",
        type: "number",
        min: -1,
        max: 1,
        step: "any",
      },
      {
        name: "endpoint_latency_adjustment_level",
        label: "Soniox endpoint latency adjustment",
        type: "number",
        min: 0,
        max: 3,
      },
    ],
  },
};

const capabilityFields: Record<string, { name: string; label: string }[]> = {
  llm: [
    { name: "supports_temperature", label: "Supports temperature" },
    { name: "supports_reasoning_effort", label: "Supports reasoning effort" },
  ],
  realtime: [
    { name: "supports_server_vad", label: "Supports server VAD" },
    { name: "supports_semantic_vad", label: "Supports semantic VAD" },
  ],
  stt: [
    { name: "supports_cascade", label: "Supports cascade STT" },
    {
      name: "supports_realtime_input_transcription",
      label: "Supports Realtime input transcription",
    },
    {
      name: "supports_native_endpointing",
      label: "Supports native STT endpointing",
    },
  ],
  tts: [],
};

function buildConfig(
  fields: ConfigField[],
  values: Record<string, string>,
): Record<string, unknown> {
  return Object.fromEntries(
    fields.flatMap((field) => {
      const value =
        field.staticValue ?? values[field.name] ?? field.defaultValue ?? "";
      if (value === "" && !field.required && field.type !== "number") return [];
      return [
        [
          field.name,
          field.type === "number"
            ? value === ""
              ? null
              : Number(value)
            : value,
        ],
      ];
    }),
  );
}

function buildCapabilities(
  providerKind: string,
  deploymentKind: string,
  values: Record<string, boolean>,
): Record<string, unknown> {
  if (providerKind === "soniox") {
    return {
      kind: "stt",
      supports_cascade: true,
      supports_realtime_input_transcription: false,
      supports_native_endpointing: true,
    };
  }
  return {
    kind: deploymentKind,
    ...Object.fromEntries(
      (capabilityFields[deploymentKind] ?? []).map(({ name }) => [
        name,
        Boolean(values[name]),
      ]),
    ),
  };
}

function supportedDeploymentKinds(provider: RegistryEntryResponse | undefined) {
  const kinds = provider?.metadata.deployment_kinds;
  return Array.isArray(kinds)
    ? kinds.filter((kind): kind is string => typeof kind === "string")
    : null;
}

function connectionsForKind(
  connections: ProviderConnectionResponse[],
  providers: RegistryEntryResponse[],
  deploymentKind: string,
) {
  if (!deploymentKind) return connections;
  return connections.filter((connection) => {
    const provider = providers.find(
      ({ key }) => key === connection.provider_kind,
    );
    const kinds = supportedDeploymentKinds(provider);
    return !kinds || kinds.includes(deploymentKind);
  });
}

function ConfigInputs({
  fields,
  values,
  onChange,
}: {
  fields: ConfigField[];
  values: Record<string, string>;
  onChange: (name: string, value: string) => void;
}) {
  return (
    <div className="grid gap-3 md:col-span-2 md:grid-cols-3">
      {fields.map((field) => (
        <label className="block text-sm" key={field.name}>
          {field.label}
          <input
            aria-label={field.label}
            className="mt-1 block w-full rounded border p-2"
            type={field.type ?? "text"}
            required={field.required}
            min={field.min}
            max={field.max}
            step={field.step}
            readOnly={field.staticValue !== undefined}
            value={
              field.staticValue ??
              values[field.name] ??
              field.defaultValue ??
              ""
            }
            onChange={(event) => onChange(field.name, event.target.value)}
          />
        </label>
      ))}
    </div>
  );
}

export function PlatformProvidersPage() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [secret, setSecret] = useState("");
  const [connectionKey, setConnectionKey] = useState("");
  const [providerKind, setProviderKind] = useState("");
  const [credentialRef, setCredentialRef] = useState("");
  const [connectionValues, setConnectionValues] = useState<
    Record<string, string>
  >({});
  const [editingConnectionId, setEditingConnectionId] = useState<string>();
  const [deploymentKey, setDeploymentKey] = useState("");
  const [connectionRef, setConnectionRef] = useState("");
  const [deploymentKind, setDeploymentKind] = useState("");
  const [serviceTier, setServiceTier] = useState("default");
  const [deploymentValues, setDeploymentValues] = useState<
    Record<string, string>
  >({});
  const [capabilityValues, setCapabilityValues] = useState<
    Record<string, boolean>
  >({});
  const [editingDeploymentId, setEditingDeploymentId] = useState<string>();
  const [sonioxRegion, setSonioxRegion] = useState("eu");

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

  const selectedConnection = query.data?.connections.find(
    ({ id }) => id === connectionRef,
  );
  const selectedProvider = query.data?.providerKinds.find(
    ({ key }) => key === selectedConnection?.provider_kind,
  );
  const connectionConfigFields = connectionFields[providerKind] ?? [];
  const deploymentConfigFields =
    deploymentFields[selectedConnection?.provider_kind ?? ""]?.[
      deploymentKind
    ] ?? [];
  const deploymentKindsForConnection =
    supportedDeploymentKinds(selectedProvider);
  const availableDeploymentKinds = deploymentKindsForConnection
    ? (query.data?.deploymentKinds.filter(({ key }) =>
        deploymentKindsForConnection.includes(key),
      ) ?? [])
    : (query.data?.deploymentKinds ?? []);
  const availableConnections = connectionsForKind(
    query.data?.connections ?? [],
    query.data?.providerKinds ?? [],
    deploymentKind,
  );
  const configuredTiers = selectedProvider?.metadata.service_tiers;
  const serviceTiers =
    configuredTiers && typeof configuredTiers === "object"
      ? Object.entries(configuredTiers as Record<string, unknown>).filter(
          (entry): entry is [string, string] => typeof entry[1] === "string",
        )
      : [];
  const sonioxStt =
    selectedConnection?.provider_kind === "soniox" && deploymentKind === "stt";
  const sonioxConnection = providerKind === "soniox";

  const clearDeploymentForm = () => {
    setEditingDeploymentId(undefined);
    setDeploymentKey("");
    setConnectionRef("");
    setDeploymentKind("");
    setDeploymentValues({});
    setCapabilityValues({});
    setServiceTier("default");
  };

  const clearConnectionForm = () => {
    setEditingConnectionId(undefined);
    setConnectionKey("");
    setProviderKind("");
    setCredentialRef("");
    setConnectionValues({});
    setSonioxRegion("eu");
  };

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
    mutationFn: async () => {
      const connectionConfig = sonioxConnection
        ? { region: sonioxRegion }
        : (buildConfig(
            connectionConfigFields,
            connectionValues,
          ) as ProviderConnectionCreateConnectionConfig);
      if (editingConnectionId) {
        const current =
          await getConnectionManagementV1ProvidersConnectionsIdGet(
            editingConnectionId,
          );
        return responseData(
          await updateConnectionManagementV1ProvidersConnectionsIdPut(
            editingConnectionId,
            {
              credential_ref: credentialRef,
              connection_config: connectionConfig,
            },
            managementMutationOptions(current.headers.get("etag")),
          ),
        );
      }
      return responseData(
        await createConnectionManagementV1ProvidersConnectionsPost(
          {
            key: connectionKey,
            provider_kind: providerKind,
            credential_ref: credentialRef,
            connection_config: connectionConfig,
          },
          managementMutationOptions(),
        ),
      );
    },
    onSuccess: async () => {
      clearConnectionForm();
      await queryClient.invalidateQueries({
        queryKey: ["control-plane", "providers"],
      });
    },
  });

  const createDeployment = useMutation({
    mutationFn: async () => {
      const deploymentConfig = {
        ...buildConfig(deploymentConfigFields, deploymentValues),
        ...(deploymentKind === "llm" && serviceTiers.length
          ? { service_tier: serviceTier }
          : {}),
      } as ModelDeploymentCreate["deployment_config"];
      const capabilities = buildCapabilities(
        selectedConnection?.provider_kind ?? "",
        deploymentKind,
        capabilityValues,
      ) as ModelDeploymentCreate["capabilities"];
      if (editingDeploymentId) {
        const current =
          await getDeploymentManagementV1ProvidersDeploymentsIdGet(
            editingDeploymentId,
          );
        return responseData(
          await updateDeploymentManagementV1ProvidersDeploymentsIdPut(
            editingDeploymentId,
            {
              connection_ref: connectionRef,
              deployment_config: deploymentConfig,
              capabilities,
            },
            managementMutationOptions(current.headers.get("etag")),
          ),
        );
      }
      return responseData(
        await createDeploymentManagementV1ProvidersDeploymentsPost(
          {
            key: deploymentKey,
            connection_ref: connectionRef,
            deployment_kind:
              deploymentKind as ModelDeploymentCreate["deployment_kind"],
            deployment_config: deploymentConfig,
            capabilities,
          },
          managementMutationOptions(),
        ),
      );
    },
    onSuccess: async () => {
      clearDeploymentForm();
      await queryClient.invalidateQueries({
        queryKey: ["control-plane", "providers"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["control-plane", "model-deployments"],
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
      await queryClient.invalidateQueries({
        queryKey: ["control-plane", "model-deployments"],
      });
    },
  });

  const updateServiceTier = useMutation({
    mutationFn: async ({
      deployment,
      serviceTier,
    }: {
      deployment: ModelDeploymentResponse;
      serviceTier: string;
    }) => {
      const current = await getDeploymentManagementV1ProvidersDeploymentsIdGet(
        deployment.id,
      );
      const value = responseData<ModelDeploymentResponse>(current);
      return responseData(
        await updateDeploymentManagementV1ProvidersDeploymentsIdPut(
          deployment.id,
          {
            connection_ref: value.connection_ref,
            deployment_config: {
              ...value.deployment_config,
              service_tier: serviceTier,
            },
            capabilities: value.capabilities,
          },
          managementMutationOptions(current.headers.get("etag")),
        ),
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["control-plane", "providers"],
      });
      await queryClient.invalidateQueries({
        queryKey: ["control-plane", "model-deployments"],
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

  const { credentials, connections, deployments, providerKinds } = query.data;
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
          {editingConnectionId
            ? "Edit provider connection"
            : "Provider Connections"}
        </h2>
        <input
          aria-label="Connection key"
          className="rounded border p-2"
          placeholder="Key"
          value={connectionKey}
          readOnly={Boolean(editingConnectionId)}
          onChange={(event) => setConnectionKey(event.target.value)}
        />
        <select
          aria-label="Provider kind"
          className="rounded border p-2"
          disabled={Boolean(editingConnectionId)}
          value={providerKind}
          onChange={(event) => {
            setProviderKind(event.target.value);
            setConnectionValues({});
          }}
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
        {connectionConfigFields.length > 0 && (
          <ConfigInputs
            fields={connectionConfigFields}
            values={connectionValues}
            onChange={(field, value) =>
              setConnectionValues((current) => ({ ...current, [field]: value }))
            }
          />
        )}
        {sonioxConnection && (
          <label className="block text-sm md:col-span-2">
            Soniox processing region
            <select
              aria-label="Soniox processing region"
              className="mt-1 block w-full rounded border p-2"
              value={sonioxRegion}
              onChange={(event) => setSonioxRegion(event.target.value)}
            >
              <option value="eu">EU</option>
              <option value="global">Global</option>
            </select>
          </label>
        )}
        {!sonioxConnection &&
          connectionConfigFields.length === 0 &&
          providerKind && (
            <p className="text-sm text-muted md:col-span-2">
              This provider has no connection-specific settings.
            </p>
          )}
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
          {editingConnectionId ? "Save connection" : "Create connection"}
        </button>
        {editingConnectionId && (
          <button
            className="rounded border px-3 py-2 text-sm md:col-span-2"
            onClick={clearConnectionForm}
            type="button"
          >
            Cancel edit
          </button>
        )}
        {createConnection.isError && (
          <PageError
            compact
            error={createConnection.error}
            title="Provider connection could not be saved"
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
          {editingDeploymentId ? "Edit model deployment" : "Model Deployments"}
        </h2>
        <input
          aria-label="Deployment key"
          className="rounded border p-2"
          placeholder="Key"
          value={deploymentKey}
          readOnly={Boolean(editingDeploymentId)}
          onChange={(event) => setDeploymentKey(event.target.value)}
        />
        <select
          aria-label="Connection"
          className="rounded border p-2"
          value={connectionRef}
          onChange={(event) => {
            setConnectionRef(event.target.value);
            setServiceTier("default");
            setDeploymentValues({});
            setCapabilityValues({});
            const nextConnection = connections.find(
              ({ id }) => id === event.target.value,
            );
            const nextProvider = providerKinds.find(
              ({ key }) => key === nextConnection?.provider_kind,
            );
            const kinds = supportedDeploymentKinds(nextProvider);
            if (deploymentKind && kinds && !kinds.includes(deploymentKind)) {
              setDeploymentKind("");
            }
          }}
        >
          <option value="">Select provider connection</option>
          {availableConnections.map((connection) => (
            <option key={connection.id} value={connection.id}>
              {connection.key} ({connection.id.slice(0, 8)})
            </option>
          ))}
        </select>
        <select
          aria-label="Deployment kind"
          className="rounded border p-2"
          disabled={Boolean(editingDeploymentId)}
          value={deploymentKind}
          onChange={(event) => {
            setDeploymentKind(event.target.value);
            setDeploymentValues({});
            setCapabilityValues({});
            setServiceTier("default");
          }}
        >
          <option value="">Select deployment kind</option>
          {availableDeploymentKinds.map((kind) => (
            <option key={kind.key} value={kind.key}>
              {kind.name} ({kind.key})
            </option>
          ))}
        </select>
        {deploymentKind === "llm" && serviceTiers.length > 0 && (
          <label className="block text-sm">
            Service tier
            <select
              aria-label="Service tier"
              className="mt-1 block w-full rounded border p-2"
              value={serviceTier}
              onChange={(event) => setServiceTier(event.target.value)}
            >
              {serviceTiers.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        )}
        {deploymentConfigFields.length > 0 && (
          <ConfigInputs
            fields={deploymentConfigFields}
            values={deploymentValues}
            onChange={(field, value) =>
              setDeploymentValues((current) => ({ ...current, [field]: value }))
            }
          />
        )}
        {deploymentKind &&
          (sonioxStt ? (
            <p className="text-sm text-muted md:col-span-2">
              Soniox capabilities are fixed by the Control Plane schema.
            </p>
          ) : (
            <fieldset className="grid gap-2 md:col-span-2 md:grid-cols-2">
              <legend className="mb-1 text-sm font-medium">Capabilities</legend>
              {(capabilityFields[deploymentKind] ?? []).map((field) => (
                <label
                  className="flex items-center gap-2 text-sm"
                  key={field.name}
                >
                  <input
                    aria-label={field.label}
                    checked={Boolean(capabilityValues[field.name])}
                    onChange={(event) =>
                      setCapabilityValues((current) => ({
                        ...current,
                        [field.name]: event.target.checked,
                      }))
                    }
                    type="checkbox"
                  />
                  {field.label}
                </label>
              ))}
              {deploymentKind === "tts" && (
                <p className="text-sm text-muted">
                  No additional TTS capability flags.
                </p>
              )}
            </fieldset>
          ))}
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
          {editingDeploymentId ? "Save deployment" : "Create deployment"}
        </button>
        {editingDeploymentId && (
          <button
            className="rounded border px-3 py-2 text-sm md:col-span-2"
            onClick={clearDeploymentForm}
            type="button"
          >
            Cancel edit
          </button>
        )}
        {createDeployment.isError && (
          <PageError
            compact
            error={createDeployment.error}
            title="Model deployment could not be saved"
          />
        )}
      </form>

      <ResourceList
        title="Provider Connections"
        items={connections}
        onEdit={(connection) => {
          const config = connection.connection_config;
          setEditingConnectionId(connection.id);
          setConnectionKey(connection.key);
          setProviderKind(connection.provider_kind);
          setCredentialRef(connection.credential_ref);
          setConnectionValues(
            Object.fromEntries(
              (connectionFields[connection.provider_kind] ?? []).map(
                (field) => [field.name, String(config[field.name] ?? "")],
              ),
            ),
          );
          setSonioxRegion(String(config.region ?? "global"));
        }}
        onToggle={(resource, operation) =>
          toggle.mutate({ id: resource.id, resource: "connection", operation })
        }
      />
      <section>
        <h2 className="mb-2 text-lg font-semibold">Model Deployments</h2>
        <ul className="divide-y border-y">
          {deployments.map((deployment) => {
            const providerKind = connections.find(
              ({ id }) => id === deployment.connection_ref,
            )?.provider_kind;
            const tierMetadata = providerKinds.find(
              ({ key }) => key === providerKind,
            )?.metadata.service_tiers;
            const tiers =
              deployment.deployment_kind === "llm" &&
              tierMetadata &&
              typeof tierMetadata === "object"
                ? Object.entries(
                    tierMetadata as Record<string, unknown>,
                  ).filter(
                    (entry): entry is [string, string] =>
                      typeof entry[1] === "string",
                  )
                : [];
            return (
              <li
                className="flex flex-wrap items-center justify-between gap-3 py-3"
                key={deployment.id}
              >
                <span>
                  {deployment.key}{" "}
                  <span className="text-sm text-muted">
                    {deployment.enabled ? "Enabled" : "Disabled"}
                  </span>
                </span>
                {tiers.length > 0 && (
                  <label className="text-sm">
                    Service tier
                    <select
                      aria-label={`Service tier ${deployment.key}`}
                      className="ml-2 rounded border p-1"
                      value={String(
                        deployment.deployment_config.service_tier ?? "default",
                      )}
                      disabled={updateServiceTier.isPending}
                      onChange={(event) =>
                        updateServiceTier.mutate({
                          deployment,
                          serviceTier: event.target.value,
                        })
                      }
                    >
                      {tiers.map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <button
                  className="rounded border px-2 py-1 text-sm"
                  onClick={() => {
                    const fields =
                      deploymentFields[providerKind ?? ""]?.[
                        deployment.deployment_kind
                      ] ?? [];
                    const config = deployment.deployment_config;
                    const capabilities = deployment.capabilities as Record<
                      string,
                      unknown
                    >;
                    setEditingDeploymentId(deployment.id);
                    setDeploymentKey(deployment.key);
                    setConnectionRef(deployment.connection_ref);
                    setDeploymentKind(deployment.deployment_kind);
                    setDeploymentValues(
                      Object.fromEntries(
                        fields.map((field) => [
                          field.name,
                          String(
                            config[field.name] ?? field.defaultValue ?? "",
                          ),
                        ]),
                      ),
                    );
                    setCapabilityValues(
                      Object.fromEntries(
                        (
                          capabilityFields[deployment.deployment_kind] ?? []
                        ).map(({ name }) => [
                          name,
                          Boolean(capabilities[name]),
                        ]),
                      ),
                    );
                    setServiceTier(String(config.service_tier ?? "default"));
                  }}
                  type="button"
                >
                  Edit
                </button>
                <button
                  className="rounded border px-2 py-1 text-sm"
                  onClick={() =>
                    toggle.mutate({
                      id: deployment.id,
                      resource: "deployment",
                      operation: deployment.enabled ? "disable" : "enable",
                    })
                  }
                  type="button"
                >
                  {deployment.enabled ? "Disable" : "Enable"}
                </button>
              </li>
            );
          })}
        </ul>
      </section>
      {toggle.isError && (
        <PageError
          compact
          error={toggle.error}
          onRetry={() => query.refetch()}
          title="Provider resource action failed"
        />
      )}
      {updateServiceTier.isError && (
        <PageError
          compact
          error={updateServiceTier.error}
          onRetry={() => query.refetch()}
          title="Service tier could not be updated"
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
  onEdit,
}: {
  title: string;
  items: T[];
  onToggle: (resource: T, operation: "enable" | "disable") => void;
  onEdit?: (resource: T) => void;
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
            <div className="flex gap-2">
              {onEdit && (
                <button
                  className="rounded border px-2 py-1 text-sm"
                  onClick={() => onEdit(resource)}
                  type="button"
                >
                  Edit
                </button>
              )}
              <button
                className="rounded border px-2 py-1 text-sm"
                onClick={() =>
                  onToggle(resource, resource.enabled ? "disable" : "enable")
                }
                type="button"
              >
                {resource.enabled ? "Disable" : "Enable"}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
