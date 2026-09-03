import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { PageError, PageLoading } from "../../components/page-states";
import {
  activeV1ScopesPlatformComponentsKindActiveGet,
  activeV1ScopesProfileProfileKeyComponentsKindActiveGet,
  activeV1ScopesTenantTenantIdComponentsKindActiveGet,
  discardDraftV1ScopesPlatformComponentsKindDraftDelete,
  discardDraftV1ScopesProfileProfileKeyComponentsKindDraftDelete,
  discardDraftV1ScopesTenantTenantIdComponentsKindDraftDelete,
  getComponentV1ScopesPlatformComponentsKindGet,
  getComponentV1ScopesProfileProfileKeyComponentsKindGet,
  getComponentV1ScopesTenantTenantIdComponentsKindGet,
  getDraftV1ScopesPlatformComponentsKindDraftGet,
  getDraftV1ScopesProfileProfileKeyComponentsKindDraftGet,
  getDraftV1ScopesTenantTenantIdComponentsKindDraftGet,
  publishV1ScopesPlatformComponentsKindPublishPost,
  publishV1ScopesProfileProfileKeyComponentsKindPublishPost,
  publishV1ScopesTenantTenantIdComponentsKindPublishPost,
  revisionsV1ScopesPlatformComponentsKindRevisionsGet,
  revisionsV1ScopesProfileProfileKeyComponentsKindRevisionsGet,
  revisionsV1ScopesTenantTenantIdComponentsKindRevisionsGet,
  revisionV1ScopesPlatformComponentsKindRevisionsRevisionNumberGet,
  revisionV1ScopesProfileProfileKeyComponentsKindRevisionsRevisionNumberGet,
  revisionV1ScopesTenantTenantIdComponentsKindRevisionsRevisionNumberGet,
  rollbackV1ScopesPlatformComponentsKindRollbackPost,
  rollbackV1ScopesProfileProfileKeyComponentsKindRollbackPost,
  rollbackV1ScopesTenantTenantIdComponentsKindRollbackPost,
  saveDraftV1ScopesPlatformComponentsKindDraftPut,
  saveDraftV1ScopesProfileProfileKeyComponentsKindDraftPut,
  saveDraftV1ScopesTenantTenantIdComponentsKindDraftPut,
} from "../api/control-plane";
import { CodeEditor } from "../ui/foundation";
import {
  AuthoringPlanStatus,
  authoringErrorTitle,
  useAuthoringResource,
} from "./authoring";
import { EditorActions } from "./editor";

export type ControlPlaneScope =
  | { type: "platform" }
  | { type: "tenant"; id: string }
  | { type: "profile"; id: string };

type ComponentSnapshot = {
  value?: unknown;
  version?: number;
  revision_id?: string | null;
};

const options = (etag: string | null | undefined): RequestInit | undefined =>
  etag ? { headers: { "If-Match": etag } } : undefined;

const version = (etag: string | null | undefined) =>
  etag ? Number(etag.replaceAll('"', "")) : undefined;

async function readComponent(scope: ControlPlaneScope, kind: string) {
  const [draft, active] = await Promise.all([
    scope.type === "platform"
      ? getDraftV1ScopesPlatformComponentsKindDraftGet(kind)
      : scope.type === "tenant"
        ? getDraftV1ScopesTenantTenantIdComponentsKindDraftGet(scope.id, kind)
        : getDraftV1ScopesProfileProfileKeyComponentsKindDraftGet(
            scope.id,
            kind,
          ),
    scope.type === "platform"
      ? activeV1ScopesPlatformComponentsKindActiveGet(kind)
      : scope.type === "tenant"
        ? activeV1ScopesTenantTenantIdComponentsKindActiveGet(scope.id, kind)
        : activeV1ScopesProfileProfileKeyComponentsKindActiveGet(
            scope.id,
            kind,
          ),
  ]);
  const draftValue =
    draft.status >= 200 && draft.status < 300
      ? (draft.data as ComponentSnapshot)
      : undefined;
  const activeValue =
    active.status >= 200 && active.status < 300
      ? (active.data as ComponentSnapshot)
      : undefined;
  const selected = draftValue ?? activeValue;
  return {
    value: selected?.value ?? {},
    etag: draftValue?.version === undefined ? null : `"${draftValue.version}"`,
    hasDraft: Boolean(draftValue),
    activeRevisionId: activeValue?.revision_id ?? null,
  };
}

async function saveComponent(
  scope: ControlPlaneScope,
  kind: string,
  value: unknown,
  etag: string | null | undefined,
  activeRevisionId: string | null,
) {
  const body = {
    value: value as Record<string, unknown>,
    schema_version: 1,
    expected_draft_version: version(etag) ?? null,
    expected_active_revision_id: activeRevisionId,
  };
  return scope.type === "platform"
    ? saveDraftV1ScopesPlatformComponentsKindDraftPut(kind, body, options(etag))
    : scope.type === "tenant"
      ? saveDraftV1ScopesTenantTenantIdComponentsKindDraftPut(
          scope.id,
          kind,
          body,
          options(etag),
        )
      : saveDraftV1ScopesProfileProfileKeyComponentsKindDraftPut(
          scope.id,
          kind,
          body,
          options(etag),
        );
}

async function publishComponent(
  scope: ControlPlaneScope,
  kind: string,
  expectedDraftVersion: number,
) {
  return scope.type === "platform"
    ? publishV1ScopesPlatformComponentsKindPublishPost(kind, {
        expected_draft_version: expectedDraftVersion,
      })
    : scope.type === "tenant"
      ? publishV1ScopesTenantTenantIdComponentsKindPublishPost(scope.id, kind, {
          expected_draft_version: expectedDraftVersion,
        })
      : publishV1ScopesProfileProfileKeyComponentsKindPublishPost(
          scope.id,
          kind,
          { expected_draft_version: expectedDraftVersion },
        );
}

export function useControlPlaneComponent<T>({
  scope,
  kind,
  emptyValue,
}: {
  scope: ControlPlaneScope;
  kind: string;
  emptyValue: T;
}) {
  const activeRevisionId = useRef<string | null>(null);
  const resource = useAuthoringResource<T>({
    queryKey: ["control-plane", scope, kind],
    read: async () => {
      const snapshot = await readComponent(scope, kind);
      activeRevisionId.current = snapshot.activeRevisionId;
      return { ...snapshot, value: (snapshot.value ?? emptyValue) as T };
    },
    plan: async () => ({ valid: true, errors: [], warnings: [] }),
    save: (value, requestOptions) =>
      saveComponent(
        scope,
        kind,
        value,
        requestOptions?.headers instanceof Headers
          ? requestOptions.headers.get("If-Match")
          : requestOptions?.headers && !Array.isArray(requestOptions.headers)
            ? requestOptions.headers["If-Match"]
            : undefined,
        activeRevisionId.current,
      ),
  });
  const publish = useMutation({
    mutationFn: () => {
      const expectedDraftVersion = version(resource.query.data?.etag);
      if (!expectedDraftVersion)
        throw new Error("No saved CP draft to publish");
      return publishComponent(scope, kind, expectedDraftVersion);
    },
    onSuccess: () => resource.query.refetch(),
  });
  const discard = useMutation({
    mutationFn: () => {
      const expectedDraftVersion = version(resource.query.data?.etag);
      if (!expectedDraftVersion)
        throw new Error("No saved CP draft to discard");
      return scope.type === "platform"
        ? discardDraftV1ScopesPlatformComponentsKindDraftDelete(kind, {
            expected_draft_version: expectedDraftVersion,
          })
        : scope.type === "tenant"
          ? discardDraftV1ScopesTenantTenantIdComponentsKindDraftDelete(
              scope.id,
              kind,
              { expected_draft_version: expectedDraftVersion },
            )
          : discardDraftV1ScopesProfileProfileKeyComponentsKindDraftDelete(
              scope.id,
              kind,
              { expected_draft_version: expectedDraftVersion },
            );
    },
    onSuccess: () => resource.query.refetch(),
  });
  return { ...resource, publish, discard };
}

export function ControlPlaneJsonEditor({
  title,
  scope,
  kind,
  initialValue = {},
}: {
  title: string;
  scope: ControlPlaneScope;
  kind: string;
  initialValue?: unknown;
}) {
  const resource = useControlPlaneComponent({
    scope,
    kind,
    emptyValue: initialValue,
  });
  const revisions = useQuery({
    queryKey: ["control-plane", scope, kind, "revisions"],
    queryFn: async () => {
      const operation = componentRevisionOperations[scope.type].revisions as (
        ...args: unknown[]
      ) => Promise<{ data: unknown }>;
      const result =
        scope.type === "platform"
          ? await operation(kind, { limit: 20 })
          : await operation(scope.id, kind, { limit: 20 });
      return result.data;
    },
  });
  const rollback = useMutation({
    mutationFn: async (revisionNumber: number) => {
      const operation = componentRevisionOperations[scope.type].rollback as (
        ...args: unknown[]
      ) => Promise<unknown>;
      return scope.type === "platform"
        ? operation(kind, { revision_number: revisionNumber })
        : operation(scope.id, kind, { revision_number: revisionNumber });
    },
    onSuccess: () => resource.query.refetch(),
  });
  const [text, setText] = useState("");
  useEffect(() => {
    if (resource.value !== undefined)
      setText(JSON.stringify(resource.value, null, 2));
  }, [resource.value]);
  const parsed = useMemo(() => {
    try {
      return { value: JSON.parse(text), error: undefined };
    } catch (error) {
      return {
        value: undefined,
        error: error instanceof Error ? error.message : "Invalid JSON",
      };
    }
  }, [text]);
  if (resource.query.isPending) return <PageLoading />;
  if (resource.query.isError)
    return <PageError title={`${title} could not be loaded`} />;
  return (
    <>
      <EditorActions
        dirty={resource.dirty}
        hasDraft={resource.hasDraft}
        onSave={() => resource.save.mutateAsync().then(() => undefined)}
        saveDisabled={!resource.validation.canSave || Boolean(parsed.error)}
        remoteChanged={resource.remoteChanged}
        conflict={resource.conflict}
        onReload={resource.reload}
        saving={resource.save.isPending}
        title={title}
        validating={resource.validation.isValidating}
        onPublish={() => resource.publish.mutateAsync().then(() => undefined)}
        publishing={resource.publish.isPending}
      />
      {resource.hasDraft && !resource.dirty && (
        <button
          className="mb-4 rounded border px-3 py-2 text-sm"
          disabled={resource.discard.isPending}
          onClick={() => resource.discard.mutate()}
          type="button"
        >
          Discard draft
        </button>
      )}
      <AuthoringPlanStatus validation={resource.validation} />
      <CodeEditor
        label={title}
        minHeight={360}
        onChange={(value) => {
          setText(value);
          try {
            resource.setValue(JSON.parse(value));
          } catch {
            // Keep the last valid value until the JSON is complete.
          }
        }}
        value={text}
      />
      {parsed.error && (
        <p className="mt-2 text-sm text-red-600">{parsed.error}</p>
      )}
      {revisions.data && (
        <details className="mt-4 rounded border p-3">
          <summary>Revision history</summary>
          <div className="mt-2 space-y-2 text-sm">
            {Array.isArray(revisions.data) &&
              revisions.data.map((item) => {
                const revision = item as { revision_number?: number };
                const revisionNumber = revision.revision_number;
                return revisionNumber ? (
                  <button
                    className="mr-2 rounded border px-2 py-1"
                    key={revisionNumber}
                    onClick={() => rollback.mutate(revisionNumber)}
                    type="button"
                  >
                    Roll back to revision {revisionNumber}
                  </button>
                ) : null;
              })}
          </div>
        </details>
      )}
      {resource.save.isError && (
        <PageError
          compact
          title={authoringErrorTitle(
            resource.save.error,
            `${title} change failed`,
          )}
        />
      )}
    </>
  );
}

function RevisionHistory({
  scope,
  kind,
  onChanged,
}: {
  scope: ControlPlaneScope;
  kind: string;
  onChanged: () => void;
}) {
  const revisions = useQuery({
    queryKey: ["control-plane", scope, kind, "structured-revisions"],
    queryFn: async () => {
      const operation = componentRevisionOperations[scope.type].revisions as (
        ...args: unknown[]
      ) => Promise<{ data: unknown }>;
      const result =
        scope.type === "platform"
          ? await operation(kind, { limit: 20 })
          : await operation(scope.id, kind, { limit: 20 });
      return result.data;
    },
  });
  const rollback = useMutation({
    mutationFn: async (revisionNumber: number) => {
      const operation = componentRevisionOperations[scope.type].rollback as (
        ...args: unknown[]
      ) => Promise<unknown>;
      return scope.type === "platform"
        ? operation(kind, { revision_number: revisionNumber })
        : operation(scope.id, kind, { revision_number: revisionNumber });
    },
    onSuccess: onChanged,
  });
  if (!Array.isArray(revisions.data) || revisions.data.length === 0)
    return null;
  return (
    <details className="mt-4 rounded border p-3">
      <summary>Revision history</summary>
      <div className="mt-2 flex flex-wrap gap-2">
        {revisions.data.map((item) => {
          const number = (item as { revision_number?: number }).revision_number;
          return number ? (
            <button
              className="rounded border px-2 py-1 text-sm"
              key={number}
              onClick={() => rollback.mutate(number)}
              type="button"
            >
              Roll back to revision {number}
            </button>
          ) : null;
        })}
      </div>
    </details>
  );
}

type StructuredField = {
  path: string;
  label: string;
  type?: "text" | "number" | "checkbox";
  options?: readonly string[];
};

const structuredFields: Record<string, StructuredField[]> = {
  "runtime.llm.defaults": [
    { path: "deployment_ref", label: "Model deployment" },
    { path: "temperature", label: "Temperature", type: "number" },
    {
      path: "reasoning_effort",
      label: "Reasoning effort",
      options: ["", "none", "low", "medium", "high", "xhigh", "max"],
    },
    {
      path: "max_completion_tokens",
      label: "Max completion tokens",
      type: "number",
    },
  ],
  "runtime.stt.defaults": [{ path: "deployment_ref", label: "STT deployment" }],
  "runtime.tts.defaults": [
    { path: "deployment_ref", label: "TTS deployment" },
    { path: "default_voice_id", label: "Default voice" },
    {
      path: "min_sentence_chars",
      label: "Minimum sentence characters",
      type: "number",
    },
  ],
  "runtime.cascade.execution.defaults": [
    {
      path: "speech_activity.min_speech_seconds",
      label: "Minimum speech seconds",
      type: "number",
    },
    {
      path: "speech_activity.min_silence_seconds",
      label: "Minimum silence seconds",
      type: "number",
    },
    {
      path: "speech_activity.activation_threshold",
      label: "Activation threshold",
      type: "number",
    },
    {
      path: "stt_commit.strategy",
      label: "STT commit strategy",
      options: ["local_vad", "provider_vad"],
    },
    {
      path: "endpointing.min_delay_seconds",
      label: "Minimum endpoint delay",
      type: "number",
    },
    {
      path: "endpointing.max_delay_seconds",
      label: "Maximum endpoint delay",
      type: "number",
    },
    {
      path: "interruption.enabled",
      label: "Interruption enabled",
      type: "checkbox",
    },
    {
      path: "response_scheduling.preemptive_generation",
      label: "Preemptive generation",
      type: "checkbox",
    },
    {
      path: "response_scheduling.preemptive_tts",
      label: "Preemptive TTS",
      type: "checkbox",
    },
  ],
  "runtime.realtime.execution.defaults": [
    { path: "deployment_ref", label: "Realtime deployment" },
    {
      path: "input_transcription.deployment_ref",
      label: "Input transcription deployment",
    },
    { path: "default_voice", label: "Default voice" },
    {
      path: "turn_completion.strategy",
      label: "Turn completion",
      options: ["server_vad", "semantic_vad"],
    },
    {
      path: "interruption.enabled",
      label: "Interruption enabled",
      type: "checkbox",
    },
  ],
  "prompt.system": [{ path: "content", label: "System prompt" }],
  "prompt.tenant": [{ path: "content", label: "Tenant prompt" }],
  "knowledge.tenant": [{ path: "content", label: "Knowledge content" }],
  "prompt.profile.selection": [{ path: "profile_key", label: "Profile key" }],
  "runtime.architecture.policy": [
    {
      path: "architectures",
      label: "Architecture priority (cascade,realtime)",
    },
  ],
  "runtime.speech.overrides": [
    { path: "language", label: "Language" },
    { path: "stt.keyterms", label: "STT keyterms (comma separated)" },
    {
      path: "voices.cascade",
      label: "Cascade voice (blank uses platform default)",
    },
    {
      path: "voices.realtime",
      label: "Realtime voice (blank uses platform default)",
    },
  ],
  "agent.tenant": [
    { path: "display_name", label: "Display name" },
    { path: "agent_profile", label: "Agent profile" },
    { path: "greeting", label: "Greeting" },
    {
      path: "conversation_scope",
      label: "Conversation scope",
      options: ["call", "tenant"],
    },
    { path: "locale", label: "Locale" },
    { path: "timezone", label: "Timezone" },
  ],
};

function readPath(value: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((current, key) => {
    return current && typeof current === "object"
      ? (current as Record<string, unknown>)[key]
      : undefined;
  }, value);
}

function writePath(
  value: unknown,
  path: string,
  next: unknown,
): Record<string, unknown> {
  const result = structuredClone(
    value && typeof value === "object" ? value : {},
  );
  let cursor = result as Record<string, unknown>;
  const parts = path.split(".");
  for (const part of parts.slice(0, -1)) {
    cursor[part] =
      cursor[part] && typeof cursor[part] === "object" ? cursor[part] : {};
    cursor = cursor[part] as Record<string, unknown>;
  }
  cursor[parts.at(-1) as string] = next;
  return result as Record<string, unknown>;
}

export function ControlPlaneStructuredEditor({
  title,
  scope,
  kind,
  initialValue = {},
}: {
  title: string;
  scope: ControlPlaneScope;
  kind: string;
  initialValue?: unknown;
}) {
  const resource = useControlPlaneComponent({
    scope,
    kind,
    emptyValue: initialValue,
  });
  if (resource.query.isPending) return <PageLoading />;
  if (resource.query.isError)
    return <PageError title={`${title} could not be loaded`} />;
  const fields = structuredFields[kind] ?? [];
  const value = resource.value ?? initialValue;
  return (
    <>
      <EditorActions
        dirty={resource.dirty}
        hasDraft={resource.hasDraft}
        onSave={() => resource.save.mutateAsync().then(() => undefined)}
        saveDisabled={!resource.validation.canSave}
        remoteChanged={resource.remoteChanged}
        conflict={resource.conflict}
        onReload={resource.reload}
        saving={resource.save.isPending}
        title={title}
        validating={resource.validation.isValidating}
        onPublish={() => resource.publish.mutateAsync().then(() => undefined)}
        publishing={resource.publish.isPending}
      />
      <RevisionHistory
        scope={scope}
        kind={kind}
        onChanged={() => resource.query.refetch()}
      />
      <AuthoringPlanStatus validation={resource.validation} />
      <div className="grid gap-4 rounded border p-4 md:grid-cols-2">
        {fields.map((field) => {
          const current = readPath(value, field.path);
          const set = (next: unknown) =>
            resource.setValue(
              writePath(value, field.path, next) as typeof value,
            );
          const isArchitecture = field.path === "architectures";
          const isKeyterms = field.path === "stt.keyterms";
          return (
            <label
              className="block text-sm"
              htmlFor={`${kind}-${field.path}`}
              key={field.path}
            >
              {field.label}
              {field.options ? (
                <select
                  id={`${kind}-${field.path}`}
                  className="mt-1 block w-full rounded border p-2"
                  value={String(current ?? "")}
                  onChange={(event) => set(event.target.value)}
                >
                  {field.options.map((option) => (
                    <option key={option} value={option}>
                      {option || "Not set"}
                    </option>
                  ))}
                </select>
              ) : field.type === "checkbox" ? (
                <input
                  id={`${kind}-${field.path}`}
                  className="ml-2"
                  type="checkbox"
                  checked={current === true}
                  onChange={(event) => set(event.target.checked)}
                />
              ) : (
                <input
                  id={`${kind}-${field.path}`}
                  className="mt-1 block w-full rounded border p-2"
                  type={field.type ?? "text"}
                  value={
                    Array.isArray(current)
                      ? current.join(",")
                      : current === undefined || current === null
                        ? ""
                        : String(current)
                  }
                  onChange={(event) =>
                    set(
                      isArchitecture || isKeyterms
                        ? event.target.value
                            .split(",")
                            .map((item) => item.trim())
                            .filter(Boolean)
                        : field.type === "number"
                          ? event.target.value === ""
                            ? undefined
                            : Number(event.target.value)
                          : event.target.value,
                    )
                  }
                />
              )}
            </label>
          );
        })}
      </div>
    </>
  );
}

export const componentRevisionOperations = {
  platform: {
    component: getComponentV1ScopesPlatformComponentsKindGet,
    revisions: revisionsV1ScopesPlatformComponentsKindRevisionsGet,
    revision: revisionV1ScopesPlatformComponentsKindRevisionsRevisionNumberGet,
    publish: publishV1ScopesPlatformComponentsKindPublishPost,
    rollback: rollbackV1ScopesPlatformComponentsKindRollbackPost,
  },
  tenant: {
    component: getComponentV1ScopesTenantTenantIdComponentsKindGet,
    revisions: revisionsV1ScopesTenantTenantIdComponentsKindRevisionsGet,
    revision:
      revisionV1ScopesTenantTenantIdComponentsKindRevisionsRevisionNumberGet,
    publish: publishV1ScopesTenantTenantIdComponentsKindPublishPost,
    rollback: rollbackV1ScopesTenantTenantIdComponentsKindRollbackPost,
  },
  profile: {
    component: getComponentV1ScopesProfileProfileKeyComponentsKindGet,
    revisions: revisionsV1ScopesProfileProfileKeyComponentsKindRevisionsGet,
    revision:
      revisionV1ScopesProfileProfileKeyComponentsKindRevisionsRevisionNumberGet,
    publish: publishV1ScopesProfileProfileKeyComponentsKindPublishPost,
    rollback: rollbackV1ScopesProfileProfileKeyComponentsKindRollbackPost,
  },
} as const;
