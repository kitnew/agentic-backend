import { useQueries } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { EmptyState, PageHeader } from "../../components/page-states";
import {
  activeV1ScopesTenantTenantIdComponentsKindActiveGet,
  getDraftV1ScopesTenantTenantIdComponentsKindDraftGet,
} from "../../core/api/control-plane";
import { AuthoringPlanStatus } from "../../core/configuration/authoring";
import {
  ControlPlaneJsonEditor,
  ControlPlaneStructuredEditor,
  useControlPlaneComponent,
} from "../../core/configuration/control-plane";
import { EditorActions } from "../../core/configuration/editor";
import { useTenant } from "../../core/tenant/use-tenant";

const componentKinds = {
  runtime: ["runtime.architecture.policy", "Architecture Policy", "runtime"],
  speech: ["runtime.speech.overrides", "Speech Overrides", "runtime/speech"],
  profile: [
    "prompt.profile.selection",
    "Prompt Profile Selection",
    "prompt/profile-selection",
  ],
  prompt: ["prompt.tenant", "Tenant Prompt", "prompt"],
  knowledge: ["knowledge.tenant", "Knowledge", "knowledge-base"],
  capabilities: ["capabilities.tenant", "Capabilities", "capabilities"],
  post_call: ["post_call.tenant", "Post-call", "post-call"],
} as const;

export function TenantComponentOverviewPage() {
  const { tenantId } = useTenant();
  const statuses = useQueries({
    queries: Object.entries(componentKinds).map(([key, [kind]]) => ({
      queryKey: ["control-plane", "tenant-status", tenantId, kind],
      enabled: Boolean(tenantId),
      queryFn: async () => {
        const [active, draft] = await Promise.all([
          activeV1ScopesTenantTenantIdComponentsKindActiveGet(
            tenantId ?? "",
            kind,
          ),
          getDraftV1ScopesTenantTenantIdComponentsKindDraftGet(
            tenantId ?? "",
            kind,
          ),
        ]);
        return {
          key,
          active: active.status >= 200 && active.status < 300,
          draft: draft.status >= 200 && draft.status < 300,
        };
      },
    })),
  });
  if (!tenantId) return <EmptyState title="Select a tenant" />;
  return (
    <>
      <PageHeader
        title="Tenant"
        detail="Identity is owned by Backend; configuration is owned by Control Plane."
      />
      <div className="grid gap-3 md:grid-cols-2">
        {Object.entries(componentKinds).map(([key, [, title, path]]) => (
          <Link
            className="rounded border p-4"
            key={key}
            to={`/tenants/${tenantId}/${path}` as never}
          >
            {title}
          </Link>
        ))}
      </div>
      <section className="mt-6 rounded border p-4">
        <h2 className="mb-3 text-lg font-semibold">Control Plane readiness</h2>
        <ul className="grid gap-2 sm:grid-cols-2">
          {statuses.map((query, index) => {
            const item = query.data;
            const [, title] = Object.values(componentKinds)[index];
            const status = query.isPending
              ? "Loading"
              : item?.active
                ? item.draft
                  ? "Draft changes"
                  : "Published"
                : item?.draft
                  ? "Draft only"
                  : "Missing";
            return (
              <li
                className="flex items-center justify-between rounded bg-slate-50 px-3 py-2 text-sm"
                key={title}
              >
                <span>{title}</span>
                <span
                  className={
                    status === "Missing"
                      ? "text-muted"
                      : status === "Draft changes"
                        ? "text-warning"
                        : "text-success"
                  }
                >
                  {status}
                </span>
              </li>
            );
          })}
        </ul>
        <p className="mt-3 text-sm text-muted">
          Execution resolvability is owned by Control Plane RuntimeResolver and
          is not inferred here.
        </p>
      </section>
    </>
  );
}

export function TenantAuthoringEditorPage({
  component,
  title,
}: {
  component: "runtime" | "speech" | "profile" | "prompt" | "knowledge";
  title: string;
}) {
  const { tenantId } = useTenant();
  if (!tenantId) return <EmptyState title="Select a tenant" />;
  const [kind] = componentKinds[component];
  return (
    <ControlPlaneStructuredEditor
      kind={kind}
      scope={{ type: "tenant", id: tenantId }}
      title={title}
      initialValue={component === "knowledge" ? { content: "" } : {}}
    />
  );
}

export function TenantJsonComponentPage({
  component,
}: {
  component: "capabilities" | "post_call";
}) {
  const { tenantId } = useTenant();
  if (!tenantId) return <EmptyState title="Select a tenant" />;
  if (component === "capabilities")
    return <CapabilitiesEditor tenantId={tenantId} />;
  const [kind, title] = componentKinds[component];
  return (
    <ControlPlaneJsonEditor
      kind={kind}
      scope={{ type: "tenant", id: tenantId }}
      title={title}
    />
  );
}

type CapabilityProfile = {
  enabled: boolean;
  description: string;
  announcement: string | Record<string, string>;
  agent_input_schema: Record<string, unknown>;
  bindings: Record<string, string>;
  input_constraints: unknown[];
  business_policy: Record<string, unknown>;
  execution: Record<string, unknown>;
  result_schema?: Record<string, unknown> | null;
};

type CapabilityConfig = {
  capabilities: Record<string, boolean | CapabilityProfile>;
};

const defaultCapability: CapabilityProfile = {
  enabled: true,
  description: "",
  announcement: "",
  agent_input_schema: {
    type: "object",
    properties: {},
    required: [],
    additionalProperties: false,
  },
  bindings: {},
  input_constraints: [],
  business_policy: {},
  execution: {
    integration_connection_ref: "",
    method: "POST",
    path: "",
    timeout_seconds: 10,
  },
  result_schema: null,
};

function CapabilitiesEditor({ tenantId }: { tenantId: string }) {
  const resource = useControlPlaneComponent<CapabilityConfig>({
    scope: { type: "tenant", id: tenantId },
    kind: "capabilities.tenant",
    emptyValue: { capabilities: {} },
  });
  const [selected, setSelected] = useState<string>();
  if (resource.query.isPending) return <p>Loading…</p>;
  if (resource.query.isError) return <p>Capabilities could not be loaded</p>;
  const capabilities = resource.value?.capabilities ?? {};
  const key =
    selected && keyExists(capabilities, selected)
      ? selected
      : Object.keys(capabilities)[0];
  const profile =
    key && typeof capabilities[key] === "object"
      ? (capabilities[key] as CapabilityProfile)
      : undefined;
  const setCapabilities = (next: Record<string, boolean | CapabilityProfile>) =>
    resource.setValue({ capabilities: next });
  const edit = (patch: Partial<CapabilityProfile>) => {
    if (!key || !profile) return;
    setCapabilities({ ...capabilities, [key]: { ...profile, ...patch } });
  };
  const jsonField = (
    label: string,
    value: unknown,
    onChange: (value: unknown) => void,
  ) => (
    <label className="block text-sm">
      <span>{label}</span>
      <textarea
        className="mt-1 min-h-20 w-full rounded border p-2 font-mono"
        value={JSON.stringify(value ?? {}, null, 2)}
        onChange={(event) => {
          try {
            onChange(JSON.parse(event.target.value));
          } catch {
            /* wait for valid JSON */
          }
        }}
      />
    </label>
  );
  return (
    <div className="space-y-5">
      <EditorActions
        dirty={resource.dirty}
        hasDraft={resource.hasDraft}
        onSave={() => resource.save.mutateAsync().then(() => undefined)}
        saveDisabled={!resource.validation.canSave}
        remoteChanged={resource.remoteChanged}
        conflict={resource.conflict}
        onReload={resource.reload}
        saving={resource.save.isPending}
        title="Capabilities"
        validating={resource.validation.isValidating}
        onPublish={() => resource.publish.mutateAsync().then(() => undefined)}
        publishing={resource.publish.isPending}
      />
      <AuthoringPlanStatus validation={resource.validation} />
      <div className="flex flex-wrap gap-2">
        {Object.keys(capabilities).map((item) => (
          <button
            className={`rounded border px-2 py-1 text-sm ${item === key ? "bg-slate-100" : ""}`}
            key={item}
            onClick={() => setSelected(item)}
            type="button"
          >
            {item}
          </button>
        ))}
        <button
          className="rounded bg-slate-950 px-2 py-1 text-sm text-white"
          onClick={() => {
            const next = `capability_${Object.keys(capabilities).length + 1}`;
            setCapabilities({
              ...capabilities,
              [next]: { ...defaultCapability },
            });
            setSelected(next);
          }}
          type="button"
        >
          Add capability
        </button>
      </div>
      {key && profile ? (
        <section className="grid gap-4 rounded border p-4 md:grid-cols-2">
          <label className="block text-sm">
            Semantic key
            <input
              className="mt-1 block w-full rounded border p-2"
              value={key}
              onChange={(event) => {
                const next = event.target.value;
                const copy = { ...capabilities };
                delete copy[key];
                copy[next] = profile;
                setCapabilities(copy);
                setSelected(next);
              }}
            />
          </label>
          <label className="block text-sm">
            Enabled
            <input
              className="ml-2"
              type="checkbox"
              checked={profile.enabled}
              onChange={(event) => edit({ enabled: event.target.checked })}
            />
          </label>
          <label className="block text-sm">
            Description
            <input
              className="mt-1 block w-full rounded border p-2"
              value={profile.description}
              onChange={(event) => edit({ description: event.target.value })}
            />
          </label>
          <label className="block text-sm">
            Announcement
            <input
              className="mt-1 block w-full rounded border p-2"
              value={
                typeof profile.announcement === "string"
                  ? profile.announcement
                  : JSON.stringify(profile.announcement)
              }
              onChange={(event) => edit({ announcement: event.target.value })}
            />
          </label>
          {jsonField(
            "Request JSON Schema",
            profile.agent_input_schema,
            (value) =>
              edit({ agent_input_schema: value as Record<string, unknown> }),
          )}
          {jsonField("Canonical/source bindings", profile.bindings, (value) =>
            edit({ bindings: value as Record<string, string> }),
          )}
          {jsonField(
            "Validation constraints",
            profile.input_constraints,
            (value) => edit({ input_constraints: value as unknown[] }),
          )}
          {jsonField("Business policy", profile.business_policy, (value) =>
            edit({ business_policy: value as Record<string, unknown> }),
          )}
          {jsonField(
            "Execution / integration binding",
            profile.execution,
            (value) => edit({ execution: value as Record<string, unknown> }),
          )}
          {jsonField("Result schema", profile.result_schema, (value) =>
            edit({ result_schema: value as Record<string, unknown> }),
          )}
          <button
            className="rounded border px-3 py-2 text-sm"
            onClick={() => {
              const copy = { ...capabilities };
              delete copy[key];
              setCapabilities(copy);
              setSelected(Object.keys(copy)[0]);
            }}
            type="button"
          >
            Remove capability
          </button>
        </section>
      ) : (
        <p className="rounded border p-4 text-sm text-muted">
          Add a capability to begin authoring.
        </p>
      )}
    </div>
  );
}

function keyExists(
  value: Record<string, unknown>,
  key: string,
): key is keyof typeof value {
  return Object.hasOwn(value, key);
}
