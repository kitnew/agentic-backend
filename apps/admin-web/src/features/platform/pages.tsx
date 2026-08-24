import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type ChangeEvent,
  type ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  EmptyState,
  PageError,
  PageLoading,
} from "../../components/page-states";
import { responseData } from "../../core/api/client";
import {
  planProfilePromptAdminV1PlatformComponentsProfilesProfilePlanPost,
  planRuntimeAdminV1PlatformComponentsRuntimePlanPost,
  planSystemPromptAdminV1PlatformComponentsSystemPromptPlanPost,
  publishAdminV1PlatformComponentsPublishPost,
  saveProfilePromptAdminV1PlatformComponentsProfilesProfileDraftPut,
  saveRuntimeAdminV1PlatformComponentsRuntimeDraftPut,
  saveSystemPromptAdminV1PlatformComponentsSystemPromptDraftPut,
  stateAdminV1PlatformComponentsStateGet,
} from "../../core/api/generated/admin-platform-components/admin-platform-components";
import { showPlatformTelephonyAdminV1PlatformTelephonyGet } from "../../core/api/generated/admin-platform-telephony/admin-platform-telephony";
import type {
  AuthoringPlan,
  PlatformRuntimePolicy,
  PlatformStateResponse,
  PlatformTelephonyResponse,
} from "../../core/api/generated/models";
import { LLMRuntimeSettingsReasoningEffort } from "../../core/api/generated/models/lLMRuntimeSettingsReasoningEffort";
import {
  AuthoringPlanStatus,
  authoringErrorTitle,
  useAuthoringResource,
} from "../../core/configuration/authoring";
import { EditorActions } from "../../core/configuration/editor";
import {
  CodeEditor,
  Field,
  FormGrid,
  FormSection,
  ProfileSelector,
  ResourceStatus,
  type ResourceStatusValue,
  WorkspaceHeader,
} from "../../core/ui/foundation";
import {
  type PlatformRuntimeForm,
  toPlatformRuntimeForm,
  toPlatformRuntimePolicy,
} from "./runtime-form";

const platformKey = ["admin", "platform-components"] as const;

async function platformState() {
  return responseData<PlatformStateResponse>(
    await stateAdminV1PlatformComponentsStateGet(),
  );
}

const draftEtag = (version?: number) =>
  version === undefined ? null : `"${version}"`;
const componentStatus = (
  active: boolean,
  draft: boolean,
): ResourceStatusValue =>
  draft ? "Saved · Pending publish" : active ? "Published" : "Not configured";

function publishRequest(state: PlatformStateResponse) {
  return {
    runtime_version: state.runtime_draft?.version,
    system_prompt_version: state.system_prompt_draft?.version,
    profile_prompt_versions: Object.fromEntries(
      Object.entries(state.profile_prompt_drafts).map(([key, draft]) => [
        key,
        draft.version,
      ]),
    ),
  };
}

export function PlatformOverviewPage() {
  const query = useQuery({ queryKey: platformKey, queryFn: platformState });
  const queryClient = useQueryClient();
  const telephony = useQuery({
    queryKey: ["admin", "platform", "telephony"],
    queryFn: async () =>
      responseData<PlatformTelephonyResponse>(
        await showPlatformTelephonyAdminV1PlatformTelephonyGet(),
      ),
  });
  const publish = useMutation({
    mutationFn: async () =>
      responseData(
        await publishAdminV1PlatformComponentsPublishPost(
          publishRequest(query.data as PlatformStateResponse),
        ),
      ),
    onSuccess: async () => {
      await query.refetch();
      await queryClient.invalidateQueries({ queryKey: platformKey });
    },
  });
  if (query.isPending) return <PageLoading />;
  if (query.isError)
    return (
      <PageError
        title="Platform status could not be loaded"
        onRetry={() => query.refetch()}
      />
    );

  const state = query.data;
  const activeProfiles = Object.keys(state.active_profile_prompts).length;
  const draftProfiles = Object.keys(state.profile_prompt_drafts).length;
  const profileCount = new Set([
    ...Object.keys(state.active_profile_prompts),
    ...Object.keys(state.profile_prompt_drafts),
  ]).size;
  const hasDrafts = Boolean(
    state.runtime_draft || state.system_prompt_draft || draftProfiles,
  );
  const canPublish =
    hasDrafts &&
    Boolean(
      state.active_release ||
        (state.runtime_draft && state.system_prompt_draft),
    );
  const telephonyStatus: ResourceStatusValue | undefined = telephony.isPending
    ? undefined
    : telephony.isError
      ? "Degraded"
      : telephony.data?.provider === "configuration_required"
        ? "Not configured"
        : telephony.data?.overall === "ready"
          ? "Ready"
          : "Degraded";

  return (
    <>
      <WorkspaceHeader
        description="Platform defaults, reusable profiles, and shared infrastructure. Publishing creates one aggregate Platform Release from saved drafts."
        primaryAction={{
          label: "Publish Platform",
          disabled: !canPublish || publish.isPending,
          loading: publish.isPending,
          loadingLabel: "Publishing…",
          onClick: () => publish.mutate(),
        }}
        status={
          hasDrafts
            ? "Saved · Pending publish"
            : state.active_release
              ? "Published"
              : "Not configured"
        }
        title="Platform"
      />
      <section className="space-y-6">
        <div>
          <h2 className="text-lg font-semibold">Release status</h2>
          <p className="mt-1 text-sm text-muted">
            {state.active_release
              ? `Active release #${state.active_release.release_number}`
              : "No Platform Release has been published."}
          </p>
          {!canPublish && hasDrafts && !state.active_release && (
            <p className="mt-2 text-sm text-warning">
              The first release requires saved Runtime and System Prompt drafts.
            </p>
          )}
        </div>
        <div>
          <h2 className="mb-3 text-lg font-semibold">Configuration</h2>
          <div className="divide-y border-y">
            <ConfigurationRow
              label="Runtime"
              status={componentStatus(
                Boolean(state.active_runtime),
                Boolean(state.runtime_draft),
              )}
            />
            <ConfigurationRow
              label="System Prompt"
              status={componentStatus(
                Boolean(state.active_system_prompt),
                Boolean(state.system_prompt_draft),
              )}
            />
            <ConfigurationRow
              detail={`${profileCount} ${profileCount === 1 ? "profile" : "profiles"}`}
              label="Profiles"
              status={componentStatus(activeProfiles > 0, draftProfiles > 0)}
            />
            <ConfigurationRow
              detail={
                telephony.isPending
                  ? "Loading status…"
                  : telephony.isError
                    ? "Status unavailable"
                    : undefined
              }
              label="Telephony"
              status={telephonyStatus}
            />
          </div>
        </div>
        {publish.isError && (
          <PageError compact title="Platform changes could not be published" />
        )}
      </section>
    </>
  );
}

function ConfigurationRow({
  label,
  detail,
  status,
}: {
  label: string;
  detail?: string;
  status?: ResourceStatusValue;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 py-3">
      <div>
        <span className="font-medium">{label}</span>
        {detail && <span className="ml-2 text-sm text-muted">{detail}</span>}
      </div>
      {status && <ResourceStatus status={status} />}
    </div>
  );
}

export function PlatformRuntimePage() {
  const resource = useAuthoringResource<PlatformRuntimePolicy | null>({
    queryKey: [...platformKey, "runtime"],
    read: async () => {
      const state = await platformState();
      return {
        value: (state.runtime_draft?.value ??
          state.active_runtime) as PlatformRuntimePolicy | null,
        etag: draftEtag(state.runtime_draft?.version),
        hasDraft: Boolean(state.runtime_draft),
      };
    },
    plan: async (policy) => {
      if (!policy) throw new Error("Runtime is not configured");
      return responseData<AuthoringPlan>(
        await planRuntimeAdminV1PlatformComponentsRuntimePlanPost({ policy }),
      );
    },
    save: async (policy, options) => {
      if (!policy) throw new Error("Runtime is not configured");
      return saveRuntimeAdminV1PlatformComponentsRuntimeDraftPut(
        { policy },
        options,
      );
    },
  });
  if (resource.query.isPending) return <PageLoading />;
  if (resource.query.isError)
    return <PageError title="Platform runtime could not be loaded" />;
  if (!resource.value)
    return (
      <>
        <WorkspaceHeader status="Not configured" title="Runtime" />
        <EmptyState
          title="Runtime is not configured"
          detail="A typed Platform Runtime policy is required before it can be edited here."
        />
      </>
    );
  return <RuntimeEditor policy={resource.value} resource={resource} />;
}

function RuntimeEditor({
  policy,
  resource,
}: {
  policy: PlatformRuntimePolicy;
  resource: ReturnType<
    typeof useAuthoringResource<PlatformRuntimePolicy | null>
  >;
}) {
  const [form, setForm] = useState(() => toPlatformRuntimeForm(policy));
  const localEdit = useRef(false);
  const wasDirty = useRef(resource.dirty);
  const [structuralError, setStructuralError] = useState<string>();
  useEffect(() => {
    if (!resource.dirty) {
      if (!localEdit.current || wasDirty.current)
        setForm(toPlatformRuntimeForm(policy));
      localEdit.current = false;
    }
    wasDirty.current = resource.dirty;
  }, [policy, resource.dirty]);
  const change = (patch: Partial<PlatformRuntimeForm>) => {
    const next = { ...form, ...patch };
    localEdit.current = true;
    setForm(next);
    try {
      resource.setValue(toPlatformRuntimePolicy(next));
      setStructuralError(undefined);
    } catch (error) {
      setStructuralError((error as Error).message);
    }
  };
  const field = (key: keyof PlatformRuntimeForm) => ({
    value: form[key] ?? "",
    onChange: (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      change({ [key]: event.target.value }),
  });

  return (
    <>
      <EditorActions
        description="Defaults used by tenant runtimes unless a tenant override is enabled."
        dirty={resource.dirty}
        hasDraft={resource.hasDraft}
        onSave={() => resource.save.mutateAsync().then(() => undefined)}
        saveDisabled={Boolean(structuralError) || !resource.validation.canSave}
        remoteChanged={resource.remoteChanged}
        conflict={resource.conflict}
        onReload={resource.reload}
        saving={resource.save.isPending}
        title="Runtime"
        validating={resource.validation.isValidating}
      />
      <AuthoringPlanStatus validation={resource.validation} />
      {structuralError && <PageError compact title={structuralError} />}
      <div className="space-y-1">
        <FormSection description="Model and generation settings" title="LLM">
          <p className="mb-4 text-sm text-muted">Provider: Azure OpenAI</p>
          <FormGrid>
            <Field label="Model">
              <input {...field("llmModel")} />
            </Field>
            <Field label="Reasoning setting">
              <select {...field("reasoningMode")}>
                <option value="null">Provider default</option>
                <option value="omitted">Omit setting</option>
                <option value="value">Explicit value</option>
              </select>
            </Field>
            {form.reasoningMode === "value" && (
              <Field label="Reasoning effort">
                <select {...field("reasoningEffort")}>
                  {Object.values(LLMRuntimeSettingsReasoningEffort)
                    .filter(
                      (value): value is Exclude<typeof value, null> =>
                        value !== null,
                    )
                    .map((value) => (
                      <option key={value}>{value}</option>
                    ))}
                </select>
              </Field>
            )}
            <Field label="Temperature setting">
              <select {...field("temperatureMode")}>
                <option value="null">Provider default</option>
                <option value="omitted">Omit setting</option>
                <option value="value">Custom value</option>
              </select>
            </Field>
            {form.temperatureMode === "value" && (
              <Field label="Temperature">
                <input
                  max="2"
                  min="0"
                  step="0.1"
                  type="number"
                  {...field("temperature")}
                />
              </Field>
            )}
          </FormGrid>
        </FormSection>
        <FormSection
          defaultExpanded={false}
          description="Speech recognition settings"
          title="STT"
        >
          <p className="mb-4 text-sm text-muted">Provider: ElevenLabs</p>
          <FormGrid>
            <Field label="Model">
              <input {...field("sttModel")} />
            </Field>
          </FormGrid>
        </FormSection>
        <FormSection
          defaultExpanded={false}
          description="Local and server speech activity thresholds"
          title="Voice Activity Detection"
        >
          <FormGrid>
            <NumberField
              label="Local minimum speech (seconds)"
              input={field("localMinSpeech")}
            />
            <NumberField
              label="Local minimum silence (seconds)"
              input={field("localMinSilence")}
            />
            <NumberField
              label="Local activation threshold"
              input={field("localActivationThreshold")}
              max="1"
            />
            <NumberField
              label="Server silence threshold (seconds)"
              input={field("serverSilenceThreshold")}
            />
            <NumberField
              label="Server activity threshold"
              input={field("serverActivityThreshold")}
              max="1"
            />
            <NumberField
              label="Server minimum speech (ms)"
              input={field("serverMinSpeech")}
              step="1"
            />
            <NumberField
              label="Server minimum silence (ms)"
              input={field("serverMinSilence")}
              step="1"
            />
          </FormGrid>
        </FormSection>
        <FormSection
          defaultExpanded={false}
          description="STT turn detection and endpoint timing"
          title="Endpointing"
        >
          <p className="mb-4 text-sm text-muted">Detection: STT</p>
          <FormGrid>
            <NumberField
              label="Minimum endpointing delay (seconds)"
              input={field("endpointingMinDelay")}
            />
            <NumberField
              label="Maximum endpointing delay (seconds)"
              input={field("endpointingMaxDelay")}
            />
          </FormGrid>
        </FormSection>
        <FormSection
          defaultExpanded={false}
          description="Speech synthesis and voice settings"
          title="TTS"
        >
          <p className="mb-4 text-sm text-muted">Provider: ElevenLabs</p>
          <FormGrid>
            <Field label="Model">
              <input {...field("ttsModel")} />
            </Field>
            <Field label="Voice ID">
              <input {...field("voiceId")} />
            </Field>
          </FormGrid>
        </FormSection>
      </div>
      {resource.save.isError && (
        <PageError compact title="Runtime change failed" />
      )}
    </>
  );
}

function NumberField({
  label,
  input,
  max,
  step = "0.01",
}: {
  label: string;
  input: {
    value: string;
    onChange: (event: ChangeEvent<HTMLInputElement>) => void;
  };
  max?: string;
  step?: string;
}) {
  return (
    <Field label={label}>
      <input max={max} min="0" step={step} type="number" {...input} />
    </Field>
  );
}

export function PlatformSystemPromptPage() {
  const resource = usePromptResource();
  if (resource.query.isPending) return <PageLoading />;
  if (resource.query.isError)
    return <PageError title="System Prompt could not be loaded" />;
  return <PromptEditor resource={resource} title="System Prompt" />;
}

function usePromptResource(profile?: string) {
  return useAuthoringResource<string>({
    queryKey: profile
      ? [...platformKey, "profile", profile]
      : [...platformKey, "system-prompt"],
    read: async () => {
      const state = await platformState();
      const draft = profile
        ? state.profile_prompt_drafts[profile]
        : state.system_prompt_draft;
      const active = profile
        ? state.active_profile_prompts[profile]
        : state.active_system_prompt;
      return {
        value: String(draft?.value ?? active ?? ""),
        etag: draftEtag(draft?.version),
        hasDraft: Boolean(draft),
      };
    },
    plan: async (text) =>
      responseData<AuthoringPlan>(
        profile
          ? await planProfilePromptAdminV1PlatformComponentsProfilesProfilePlanPost(
              profile,
              { text },
            )
          : await planSystemPromptAdminV1PlatformComponentsSystemPromptPlanPost(
              { text },
            ),
      ),
    save: (text, options) =>
      profile
        ? saveProfilePromptAdminV1PlatformComponentsProfilesProfileDraftPut(
            profile,
            { text },
            options,
          )
        : saveSystemPromptAdminV1PlatformComponentsSystemPromptDraftPut(
            { text },
            options,
          ),
  });
}

function PromptEditor({
  title,
  resource,
  selector,
}: {
  title: string;
  resource: ReturnType<typeof usePromptResource>;
  selector?: ReactNode;
}) {
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
      />
      {selector}
      <AuthoringPlanStatus validation={resource.validation} />
      <CodeEditor
        label={title === "Profiles" ? "Profile prompt" : "Prompt"}
        minHeight={360}
        monospace={false}
        onChange={resource.setValue}
        value={resource.value ?? ""}
      />
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

export function PlatformProfilePromptPage() {
  const query = useQuery({
    queryKey: [...platformKey, "profile-keys"],
    queryFn: platformState,
  });
  const keys = useMemo(
    () =>
      query.data
        ? [
            ...new Set([
              ...Object.keys(query.data.active_profile_prompts),
              ...Object.keys(query.data.profile_prompt_drafts),
            ]),
          ].sort()
        : [],
    [query.data],
  );
  const [selected, setSelected] = useState("");
  useEffect(() => {
    if (!selected && keys.length) setSelected(keys[0]);
  }, [keys, selected]);
  if (query.isPending) return <PageLoading />;
  if (query.isError) return <PageError title="Profiles could not be loaded" />;
  if (!selected)
    return (
      <>
        <WorkspaceHeader status="Not configured" title="Profiles" />
        <EmptyState
          title="No profiles"
          detail="No active or saved profile prompts are available."
        />
      </>
    );
  return (
    <ProfileEditor onSelect={setSelected} profile={selected} profiles={keys} />
  );
}

function ProfileEditor({
  profile,
  profiles,
  onSelect,
}: {
  profile: string;
  profiles: string[];
  onSelect: (profile: string) => void;
}) {
  const resource = usePromptResource(profile);
  if (resource.query.isPending) return <PageLoading />;
  if (resource.query.isError)
    return <PageError title="Profile could not be loaded" />;
  return (
    <PromptEditor
      resource={resource}
      selector={
        <div className="mb-6 max-w-md">
          <ProfileSelector
            disabled={resource.dirty || resource.save.isPending}
            helperText={
              resource.dirty
                ? "Save or discard changes before switching profiles."
                : undefined
            }
            label="Profile"
            onChange={onSelect}
            options={[
              ...(profiles.includes(profile)
                ? []
                : [{ value: profile, label: `${profile} (unavailable)` }]),
              ...profiles.map((value) => ({ value, label: value })),
            ]}
            value={profile}
          />
        </div>
      }
      title="Profiles"
    />
  );
}
