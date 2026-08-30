import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { PageError, PageLoading } from "../../components/page-states";
import { apiErrorMessage, responseData } from "../../core/api/client";
import {
  planKnowledgeAdminV1TenantsTenantIdAuthoringKnowledgePlanPost,
  planPromptAdminV1TenantsTenantIdAuthoringPromptPlanPost,
  planRuntimeAdminV1TenantsTenantIdAuthoringRuntimePlanPost,
  readKnowledgeAdminV1TenantsTenantIdAuthoringKnowledgeGet,
  readPromptAdminV1TenantsTenantIdAuthoringPromptGet,
  readRuntimeAdminV1TenantsTenantIdAuthoringRuntimeGet,
  saveKnowledgeAdminV1TenantsTenantIdAuthoringKnowledgePut,
  savePromptAdminV1TenantsTenantIdAuthoringPromptPut,
  saveRuntimeAdminV1TenantsTenantIdAuthoringRuntimePut,
} from "../../core/api/generated/admin-authoring/admin-authoring";
import {
  componentStateAdminV1TenantsTenantIdComponentsComponentGet,
  publishAllAdminV1TenantsTenantIdComponentsPublishAllPost,
} from "../../core/api/generated/admin-tenant-components/admin-tenant-components";
import { getTenantAdminV1TenantsTenantIdGet } from "../../core/api/generated/admin-tenants/admin-tenants";
import type {
  AuthoringPlan,
  AuthoringState,
  ComponentStateResponse,
  TenantKnowledgeAuthoring,
  TenantPromptAuthoring,
  TenantResponse,
  TenantRuntimeAuthoring,
} from "../../core/api/generated/models";
import { TenantLLMRuntimeOverrideReasoningEffort } from "../../core/api/generated/models";
import {
  AuthoringPlanStatus,
  authoringErrorTitle,
  type TenantAuthoringResource,
  useTenantAuthoringResource,
} from "../../core/configuration/authoring";
import { EditorActions } from "../../core/configuration/editor";
import { useTenant } from "../../core/tenant/use-tenant";
import {
  CodeEditor,
  Field,
  FormGrid,
  ResourceStatus,
  ToggleSection,
  WorkspaceHeader,
} from "../../core/ui/foundation";
import {
  type RuntimeForm,
  type RuntimeKeyterm,
  type RuntimeReasoningEffort,
  toRuntimeForm,
  toRuntimePayload,
  validateKeyterm,
  validateRuntimeForm,
} from "./runtime-mappings";

const allComponents = [
  ["runtime", "Runtime"],
  ["agent", "Agent"],
  ["prompt", "Prompt"],
  ["knowledge", "Knowledge Base"],
  ["capabilities", "Capabilities"],
  ["post_call", "Post-call"],
  ["telephony", "Telephony"],
] as const;
const visibleComponents = allComponents.slice(0, 4);

function useCurrentTenant() {
  const { tenantId } = useTenant();
  const tenant = useQuery({
    queryKey: ["admin", "tenant", tenantId],
    queryFn: async () =>
      responseData<TenantResponse>(
        await getTenantAdminV1TenantsTenantIdGet(tenantId as string),
      ),
    enabled: Boolean(tenantId),
  });
  return {
    tenantId,
    tenant: tenant.data,
    tenantQuery: tenant,
  };
}

async function componentState(tenantId: string, component: string) {
  return responseData<ComponentStateResponse>(
    await componentStateAdminV1TenantsTenantIdComponentsComponentGet(
      tenantId,
      component,
    ),
  );
}

export function TenantAuthoringEditorPage({
  component,
  title,
}: {
  component: "runtime" | "prompt" | "knowledge";
  title: string;
}) {
  const { tenantId } = useTenant();
  if (!tenantId) return <PageError title="Select a tenant first" />;
  if (component === "runtime")
    return <RuntimeAuthoringEditor tenantId={tenantId} title={title} />;
  if (component === "prompt")
    return <PromptAuthoringEditor tenantId={tenantId} title={title} />;
  return <KnowledgeAuthoringEditor tenantId={tenantId} title={title} />;
}

function RuntimeAuthoringEditor({
  tenantId,
  title,
}: {
  tenantId: string;
  title: string;
}) {
  const resource = useTenantAuthoringResource<TenantRuntimeAuthoring>({
    queryKey: ["admin", "tenant-authoring", tenantId, "runtime"],
    read: async () =>
      responseData<AuthoringState>(
        await readRuntimeAdminV1TenantsTenantIdAuthoringRuntimeGet(tenantId),
      ),
    plan: async (value) =>
      responseData<AuthoringPlan>(
        await planRuntimeAdminV1TenantsTenantIdAuthoringRuntimePlanPost(
          tenantId,
          value,
        ),
      ),
    save: (value, options) =>
      saveRuntimeAdminV1TenantsTenantIdAuthoringRuntimePut(
        tenantId,
        value,
        options,
      ),
    emptyValue: {},
  });
  return <RuntimeEditor resource={resource} title={title} />;
}

function RuntimeEditor({
  resource,
  title,
}: {
  resource: TenantAuthoringResource<TenantRuntimeAuthoring>;
  title: string;
}) {
  if (resource.query.isPending) return <PageLoading />;
  if (resource.query.isError)
    return <PageError title={`${title} could not be loaded`} />;
  if (resource.value === undefined)
    return <PageError title={`${title} is not available`} />;

  return <RuntimeEditorForm resource={resource} title={title} />;
}

function RuntimeEditorForm({
  resource,
  title,
}: {
  resource: TenantAuthoringResource<TenantRuntimeAuthoring>;
  title: string;
}) {
  const localEdit = useRef(false);
  const wasDirty = useRef(resource.dirty);
  const [form, setForm] = useState(() =>
    toRuntimeForm(resource.value as TenantRuntimeAuthoring),
  );
  useEffect(() => {
    if (!resource.dirty && resource.value) {
      if (!localEdit.current || wasDirty.current)
        setForm(toRuntimeForm(resource.value as TenantRuntimeAuthoring));
      localEdit.current = false;
    }
    wasDirty.current = resource.dirty;
  }, [resource.dirty, resource.value]);
  const update = <K extends keyof RuntimeForm>(
    field: K,
    value: RuntimeForm[K],
  ) => {
    const next = { ...form, [field]: value };
    localEdit.current = true;
    setForm(next);
    resource.setValue(toRuntimePayload(next));
  };
  const toggleLlm = (enabled: boolean) => {
    const next = {
      ...form,
      llmEnabled: enabled,
      llmState: enabled ? ("value" as const) : ("null" as const),
      llmReasoningEffortState: enabled
        ? ("value" as const)
        : form.llmReasoningEffortState,
    };
    localEdit.current = true;
    setForm(next);
    resource.setValue(toRuntimePayload(next));
  };
  const toggleTts = (enabled: boolean) => {
    const next = {
      ...form,
      ttsEnabled: enabled,
      ttsState: enabled ? ("value" as const) : ("null" as const),
    };
    localEdit.current = true;
    setForm(next);
    resource.setValue(toRuntimePayload(next));
  };
  const updateKeyterms = (sttKeyterms: RuntimeKeyterm[]) => {
    const next = { ...form, sttKeyterms, sttState: "value" as const };
    localEdit.current = true;
    setForm(next);
    resource.setValue(toRuntimePayload(next));
  };
  const localError = validateRuntimeForm(form);
  const saveBlocked = Boolean(localError) || !resource.validation.canSave;
  const reasoningEfforts = Object.values(
    TenantLLMRuntimeOverrideReasoningEffort,
  ) as RuntimeReasoningEffort[];

  return (
    <div className="max-w-4xl">
      <EditorActions
        title={title}
        dirty={resource.dirty}
        hasDraft={resource.hasDraft}
        saving={resource.save.isPending}
        validating={resource.validation.isValidating}
        saveDisabled={saveBlocked}
        remoteChanged={resource.remoteChanged}
        conflict={resource.conflict}
        onReload={resource.reload}
        onSave={() => resource.save.mutateAsync().then(() => undefined)}
      />
      <AuthoringPlanStatus validation={resource.validation} />
      <div className="space-y-1">
        <ToggleSection
          description="Override Platform LLM defaults for this tenant"
          disabledSummary="Using Platform defaults"
          enabled={form.llmEnabled}
          onEnabledChange={toggleLlm}
          title="LLM override"
        >
          <div className="space-y-4">
            <Field label="Model" detail="Backend validates model compatibility">
              <input
                maxLength={255}
                value={form.llmModel}
                onChange={(event) => update("llmModel", event.target.value)}
              />
            </Field>
            <FormGrid>
              <Field label="Reasoning effort">
                <select
                  value={
                    form.llmReasoningEffortState === "value"
                      ? form.llmReasoningEffort
                      : `__${form.llmReasoningEffortState}`
                  }
                  onChange={(event) => {
                    const selected = event.target.value;
                    const next = {
                      ...form,
                      llmReasoningEffort: (selected.startsWith("__")
                        ? form.llmReasoningEffort
                        : selected) as RuntimeReasoningEffort,
                      llmReasoningEffortState: selected.startsWith("__")
                        ? (selected.slice(2) as "absent" | "null")
                        : ("value" as const),
                    };
                    localEdit.current = true;
                    setForm(next);
                    resource.setValue(toRuntimePayload(next));
                  }}
                >
                  <option value="__absent">Omit setting</option>
                  <option value="__null">Provider default (null)</option>
                  {reasoningEfforts.map((effort) => (
                    <option key={effort} value={effort}>
                      {effort}
                    </option>
                  ))}
                </select>
              </Field>
              <Field
                label="Temperature"
                detail="Optional; leave empty for null/omitted"
              >
                <input
                  max={2}
                  min={0}
                  step="any"
                  type="number"
                  value={form.llmTemperature}
                  onChange={(event) => {
                    const next = {
                      ...form,
                      llmTemperature: event.target.value,
                      llmTemperaturePresent: true,
                    };
                    localEdit.current = true;
                    setForm(next);
                    resource.setValue(toRuntimePayload(next));
                  }}
                />
              </Field>
            </FormGrid>
          </div>
        </ToggleSection>
        <section className="rounded-lg border border-slate-200 p-4">
          <div className="mb-3 flex items-start justify-between gap-4">
            <div>
              <h3 className="font-medium text-slate-950">STT keyterms</h3>
              <p className="text-sm text-slate-600">
                Up to 50 terms, 20 characters each.
              </p>
            </div>
            <button
              disabled={form.sttKeyterms.length >= 50}
              onClick={() =>
                updateKeyterms([
                  ...form.sttKeyterms,
                  { id: crypto.randomUUID(), value: "" },
                ])
              }
              type="button"
            >
              Add term
            </button>
          </div>
          <div className="space-y-3">
            {form.sttKeyterms.map((term, index) => {
              const error = validateKeyterm(form.sttKeyterms, index);
              return (
                <div key={term.id}>
                  <div className="flex gap-2">
                    <input
                      aria-invalid={Boolean(error)}
                      aria-label={`Keyterm ${index + 1}`}
                      maxLength={20}
                      value={term.value}
                      onChange={(event) =>
                        updateKeyterms(
                          form.sttKeyterms.map((value, itemIndex) =>
                            itemIndex === index
                              ? { ...value, value: event.target.value }
                              : value,
                          ),
                        )
                      }
                    />
                    <button
                      aria-label={`Remove keyterm ${index + 1}`}
                      onClick={() =>
                        updateKeyterms(
                          form.sttKeyterms.filter(
                            (_, itemIndex) => itemIndex !== index,
                          ),
                        )
                      }
                      type="button"
                    >
                      Remove
                    </button>
                  </div>
                  {error && (
                    <p className="mt-1 text-sm text-red-700">{error}</p>
                  )}
                </div>
              );
            })}
            {form.sttKeyterms.length === 0 && (
              <p className="text-sm text-slate-500">No tenant keyterms.</p>
            )}
          </div>
        </section>
        <ToggleSection
          defaultExpanded={false}
          description="Override the Platform voice for this tenant"
          disabledSummary="Using Platform defaults"
          enabled={form.ttsEnabled}
          onEnabledChange={toggleTts}
          title="TTS override"
        >
          <div className="max-w-md">
            <Field
              label="Voice ID"
              detail="Backend validates the configured voice"
            >
              <input
                maxLength={255}
                value={form.ttsVoiceId}
                onChange={(event) => update("ttsVoiceId", event.target.value)}
              />
            </Field>
          </div>
        </ToggleSection>
      </div>
      {localError && <PageError compact title={localError} />}
      {resource.save.isError && (
        <PageError
          compact
          title={authoringErrorTitle(
            resource.save.error,
            `${title} change failed`,
          )}
        />
      )}
    </div>
  );
}

function PromptAuthoringEditor({
  tenantId,
  title,
}: {
  tenantId: string;
  title: string;
}) {
  const resource = useTenantAuthoringResource<TenantPromptAuthoring>({
    queryKey: ["admin", "tenant-authoring", tenantId, "prompt"],
    read: async () =>
      responseData<AuthoringState>(
        await readPromptAdminV1TenantsTenantIdAuthoringPromptGet(tenantId),
      ),
    plan: async (value) =>
      responseData<AuthoringPlan>(
        await planPromptAdminV1TenantsTenantIdAuthoringPromptPlanPost(
          tenantId,
          value,
        ),
      ),
    save: (value, options) =>
      savePromptAdminV1TenantsTenantIdAuthoringPromptPut(
        tenantId,
        value,
        options,
      ),
    emptyValue: { text: "" },
  });
  return (
    <AuthoringEditorState
      resource={resource}
      title={title}
      format={(value) => value.text ?? ""}
      parse={(text) => ({ text })}
      fieldLabel="Prompt"
      textArea
    />
  );
}

function KnowledgeAuthoringEditor({
  tenantId,
  title,
}: {
  tenantId: string;
  title: string;
}) {
  const resource = useTenantAuthoringResource<TenantKnowledgeAuthoring>({
    queryKey: ["admin", "tenant-authoring", tenantId, "knowledge"],
    read: async () =>
      responseData<AuthoringState>(
        await readKnowledgeAdminV1TenantsTenantIdAuthoringKnowledgeGet(
          tenantId,
        ),
      ),
    plan: async (value) =>
      responseData<AuthoringPlan>(
        await planKnowledgeAdminV1TenantsTenantIdAuthoringKnowledgePlanPost(
          tenantId,
          value,
        ),
      ),
    save: (value, options) =>
      saveKnowledgeAdminV1TenantsTenantIdAuthoringKnowledgePut(
        tenantId,
        value,
        options,
      ),
    emptyValue: { content: "" },
  });
  return (
    <AuthoringEditorState
      resource={resource}
      title={title}
      format={(value) => value.content ?? ""}
      parse={(content) => ({ content })}
      fieldLabel="Knowledge Base"
      textArea
    />
  );
}

function AuthoringEditorState<T>({
  resource,
  title,
  format,
  parse,
  fieldLabel,
  textArea = false,
}: {
  resource: TenantAuthoringResource<T>;
  title: string;
  format: (value: T) => string;
  parse: (text: string) => T;
  fieldLabel: string;
  textArea?: boolean;
}) {
  if (resource.query.isPending) return <PageLoading />;
  if (resource.query.isError)
    return <PageError title={`${title} could not be loaded`} />;
  if (resource.value === undefined)
    return <PageError title={`${title} is not available`} />;
  return (
    <AuthoringEditor
      resource={resource}
      title={title}
      format={format}
      parse={parse}
      fieldLabel={fieldLabel}
      textArea={textArea}
    />
  );
}

function AuthoringEditor<T>({
  resource,
  title,
  format,
  parse,
  fieldLabel,
  textArea,
}: {
  resource: TenantAuthoringResource<T>;
  title: string;
  format: (value: T) => string;
  parse: (text: string) => T;
  fieldLabel: string;
  textArea: boolean;
}) {
  const canonical = format(resource.value as T);
  const [text, setText] = useState(canonical);
  const [parseError, setParseError] = useState<string | null>(null);
  const localEdit = useRef(false);
  const wasDirty = useRef(resource.dirty);
  useEffect(() => {
    if (!resource.dirty) {
      if (!localEdit.current || wasDirty.current)
        setText(format(resource.value as T));
      localEdit.current = false;
    }
    wasDirty.current = resource.dirty;
  }, [format, resource.dirty, resource.value]);
  const update = (next: string) => {
    localEdit.current = true;
    setText(next);
    try {
      resource.setValue(parse(next));
      setParseError(null);
    } catch {
      setParseError(
        textArea ? "Configuration must be valid JSON." : "Invalid value.",
      );
    }
  };
  const saveBlocked = Boolean(parseError) || !resource.validation.canSave;
  return (
    <div className="max-w-4xl">
      <EditorActions
        title={title}
        dirty={resource.dirty}
        hasDraft={resource.hasDraft}
        saving={resource.save.isPending}
        validating={resource.validation.isValidating}
        saveDisabled={saveBlocked}
        remoteChanged={resource.remoteChanged}
        conflict={resource.conflict}
        onReload={resource.reload}
        onSave={() => resource.save.mutateAsync().then(() => undefined)}
      />
      <AuthoringPlanStatus validation={resource.validation} />
      <CodeEditor
        label={fieldLabel}
        minHeight={textArea ? 320 : 240}
        monospace={false}
        onChange={update}
        value={text}
      />
      {parseError && <PageError compact title={parseError} />}
      {resource.save.isError && (
        <PageError
          compact
          title={authoringErrorTitle(
            resource.save.error,
            `${title} change failed`,
          )}
        />
      )}
    </div>
  );
}

export function TenantComponentOverviewPage() {
  const { tenantId, tenant, tenantQuery } = useCurrentTenant();
  const query = useQuery({
    queryKey: ["admin", "tenant-components", tenantId],
    queryFn: () =>
      Promise.all(
        allComponents.map(
          async ([component]) =>
            [
              component,
              await componentState(tenantId as string, component),
            ] as const,
        ),
      ),
    enabled: Boolean(tenantId),
  });
  const publish = useMutation({
    mutationFn: async () => {
      const latest = await query.refetch();
      const drafts =
        latest.data?.flatMap(([component, state]) =>
          state.draft
            ? [
                {
                  component,
                  draft_id: state.draft.id,
                  version: state.draft.version,
                },
              ]
            : [],
        ) ?? [];
      if (!drafts.length) return;
      responseData(
        await publishAllAdminV1TenantsTenantIdComponentsPublishAllPost(
          tenantId as string,
          { drafts },
        ),
      );
    },
    onSuccess: () => query.refetch(),
  });
  if (query.isPending || tenantQuery.isPending) return <PageLoading />;
  if (tenantQuery.isError)
    return (
      <PageError
        title={apiErrorMessage(
          tenantQuery.error,
          "Tenant status could not be loaded",
        )}
      />
    );
  if (query.isError || !tenant)
    return <PageError title="Tenant status could not be loaded" />;
  const states = new Map(query.data);
  const unpublished = query.data.filter(([, state]) => state.draft).length;
  return (
    <>
      <WorkspaceHeader
        description="Saved tenant drafts are released together. Unsaved editor changes are never included in Publish Tenant."
        primaryAction={{
          label: "Publish Tenant",
          disabled: !unpublished || publish.isPending,
          loading: publish.isPending,
          loadingLabel: "Publishing…",
          onClick: () => publish.mutate(),
        }}
        status={
          unpublished
            ? "Saved · Pending publish"
            : tenant.active_release_id
              ? "Published"
              : "Not configured"
        }
        title={tenant.display_name}
      />
      <section className="space-y-6">
        <div>
          <h2 className="text-lg font-semibold">Release status</h2>
          <p className="mt-1 text-sm text-muted">
            {tenant.active_release_id
              ? "Active release published"
              : "No active release"}
          </p>
        </div>
        <div>
          <h2 className="mb-3 text-lg font-semibold">Configuration</h2>
          <div className="divide-y border-y">
            {visibleComponents.map(([component, label]) => (
              <div
                className="flex items-center justify-between py-3"
                key={component}
              >
                <span>{label}</span>
                <ResourceStatus
                  status={
                    states.get(component)?.draft
                      ? "Saved · Pending publish"
                      : states.get(component)?.active_revision
                        ? "Published"
                        : "Not configured"
                  }
                />
              </div>
            ))}
          </div>
          <p className="mt-3 text-sm text-muted">
            {unpublished} saved {unpublished === 1 ? "draft" : "drafts"}
          </p>
        </div>
        {publish.isError && (
          <PageError compact title="Tenant changes could not be published" />
        )}
      </section>
    </>
  );
}
