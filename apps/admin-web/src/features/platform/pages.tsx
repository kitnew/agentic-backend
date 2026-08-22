import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  PageError,
  PageHeader,
  PageLoading,
} from "../../components/page-states";
import { Button } from "../../components/ui/button";
import { responseData } from "../../core/api/client";
import {
  publishAdminV1PlatformComponentsPublishPost,
  saveProfilePromptAdminV1PlatformComponentsProfilesProfileDraftPut,
  saveRuntimeAdminV1PlatformComponentsRuntimeDraftPut,
  saveSystemPromptAdminV1PlatformComponentsSystemPromptDraftPut,
  stateAdminV1PlatformComponentsStateGet,
} from "../../core/api/generated/admin-platform-components/admin-platform-components";
import type { PlatformStateResponse } from "../../core/api/generated/models";
import {
  EditorActions,
  Field,
  StatusBadge,
} from "../../core/configuration/editor";

const platformKey = ["admin", "platform-components"];

async function platformState() {
  return responseData<PlatformStateResponse>(
    await stateAdminV1PlatformComponentsStateGet(),
  );
}

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

function usePlatformPublish(
  state: PlatformStateResponse,
  refetch: () => Promise<void>,
) {
  return useMutation({
    mutationFn: async () =>
      responseData(
        await publishAdminV1PlatformComponentsPublishPost(
          publishRequest(state),
        ),
      ),
    onSuccess: refetch,
  });
}

export function PlatformOverviewPage() {
  const query = useQuery({ queryKey: platformKey, queryFn: platformState });
  const publish = useMutation({
    mutationFn: async () =>
      responseData(
        await publishAdminV1PlatformComponentsPublishPost(
          publishRequest(query.data as PlatformStateResponse),
        ),
      ),
    onSuccess: () => query.refetch(),
  });
  if (query.isPending) return <PageLoading />;
  if (query.isError)
    return (
      <PageError
        title="Platform status could not be loaded"
        onRetry={() => query.refetch()}
      />
    );
  const rows = [
    ["Runtime", Boolean(query.data.runtime_draft)],
    ["System Prompt", Boolean(query.data.system_prompt_draft)],
    [
      "Profile Prompts",
      Object.keys(query.data.profile_prompt_drafts).length > 0,
    ],
  ] as const;
  const unpublished = rows.filter(([, changed]) => changed).length;
  return (
    <>
      <PageHeader title="Platform" />
      <section className="max-w-2xl">
        <h2 className="mb-4 text-lg font-semibold">Configuration status</h2>
        <div className="divide-y border-y">
          {rows.map(([label, changed]) => (
            <div className="flex items-center justify-between py-3" key={label}>
              <span>{label}</span>
              <StatusBadge
                status={changed ? "Saved · Not published" : "Published"}
              />
            </div>
          ))}
        </div>
        <div className="mt-6 flex items-center justify-between gap-4">
          <p className="text-sm text-muted">
            {unpublished} unpublished sections
          </p>
          <Button
            disabled={!unpublished || publish.isPending}
            onClick={() => publish.mutate()}
          >
            {publish.isPending ? "Publishing..." : "Publish All"}
          </Button>
        </div>
        {publish.isError && (
          <PageError compact title="Platform changes could not be published" />
        )}
      </section>
    </>
  );
}

export function PlatformRuntimePage() {
  const query = useQuery({
    queryKey: [...platformKey, "runtime"],
    queryFn: platformState,
  });
  if (query.isPending) return <PageLoading />;
  if (query.isError)
    return <PageError title="Platform runtime could not be loaded" />;
  return (
    <RuntimeEditor
      state={query.data}
      refetch={() => query.refetch().then(() => undefined)}
    />
  );
}

function RuntimeEditor({
  state,
  refetch,
}: {
  state: PlatformStateResponse;
  refetch: () => Promise<void>;
}) {
  const canonical = JSON.stringify(
    state.runtime_draft?.value ?? state.active_runtime ?? {},
    null,
    2,
  );
  const [text, setText] = useState(canonical);
  useEffect(() => setText(canonical), [canonical]);
  const save = useMutation({
    mutationFn: async () => {
      responseData(
        await saveRuntimeAdminV1PlatformComponentsRuntimeDraftPut(
          { policy: JSON.parse(text) },
          state.runtime_draft
            ? { headers: { "If-Match": `"${state.runtime_draft.version}"` } }
            : undefined,
        ),
      );
      await refetch();
    },
  });
  const publish = usePlatformPublish(state, refetch);
  return (
    <PlatformEditor
      title="Runtime"
      text={text}
      setText={setText}
      dirty={text !== canonical}
      draft={state.runtime_draft}
      saving={save.isPending}
      publishing={publish.isPending}
      onSave={() => save.mutateAsync()}
      onPublish={() => publish.mutateAsync().then(() => undefined)}
      error={save.isError || publish.isError}
    />
  );
}

export function PlatformSystemPromptPage() {
  return <PromptEditor title="System Prompt" />;
}

export function PlatformProfilePromptPage() {
  return <PromptEditor title="Profile Prompt" profile />;
}

function PromptEditor({
  title,
  profile = false,
}: {
  title: string;
  profile?: boolean;
}) {
  const query = useQuery({
    queryKey: [...platformKey, title],
    queryFn: platformState,
  });
  const [profileKey, setProfileKey] = useState("default");
  if (query.isPending) return <PageLoading />;
  if (query.isError)
    return <PageError title={`${title} could not be loaded`} />;
  const draft = profile
    ? query.data.profile_prompt_drafts[profileKey]
    : query.data.system_prompt_draft;
  const canonical = profile
    ? (draft?.value ?? query.data.active_profile_prompts[profileKey] ?? "")
    : (draft?.value ?? query.data.active_system_prompt ?? "");
  return (
    <PromptEditorBody
      key={`${profileKey}:${draft?.version ?? "active"}`}
      title={title}
      profile={profile}
      profileKey={profileKey}
      setProfileKey={setProfileKey}
      state={query.data}
      draft={draft}
      canonical={String(canonical)}
      refetch={() => query.refetch().then(() => undefined)}
    />
  );
}

function PromptEditorBody({
  title,
  profile,
  profileKey,
  setProfileKey,
  state,
  draft,
  canonical,
  refetch,
}: {
  title: string;
  profile: boolean;
  profileKey: string;
  setProfileKey: (value: string) => void;
  state: PlatformStateResponse;
  draft: PlatformStateResponse["system_prompt_draft"];
  canonical: string;
  refetch: () => Promise<void>;
}) {
  const [text, setText] = useState(canonical);
  const save = useMutation({
    mutationFn: async () => {
      const options = draft
        ? { headers: { "If-Match": `"${draft.version}"` } }
        : undefined;
      responseData(
        profile
          ? await saveProfilePromptAdminV1PlatformComponentsProfilesProfileDraftPut(
              profileKey,
              { text },
              options,
            )
          : await saveSystemPromptAdminV1PlatformComponentsSystemPromptDraftPut(
              { text },
              options,
            ),
      );
      await refetch();
    },
  });
  const publish = usePlatformPublish(state, refetch);
  return (
    <>
      <PageHeader title={title} />
      <div className="max-w-4xl">
        {profile && (
          <Field label="Profile">
            <input
              value={profileKey}
              onChange={(event) => setProfileKey(event.target.value)}
            />
          </Field>
        )}
        <PlatformEditor
          title={title}
          text={text}
          setText={setText}
          dirty={text !== canonical}
          draft={draft}
          saving={save.isPending}
          publishing={publish.isPending}
          onSave={() => save.mutateAsync()}
          onPublish={() => publish.mutateAsync().then(() => undefined)}
          error={save.isError || publish.isError}
        />
      </div>
    </>
  );
}

function PlatformEditor({
  title,
  text,
  setText,
  dirty,
  draft,
  saving,
  publishing,
  onSave,
  onPublish,
  error,
}: {
  title: string;
  text: string;
  setText: (value: string) => void;
  dirty: boolean;
  draft: { version: number } | null;
  saving: boolean;
  publishing: boolean;
  onSave: () => Promise<void>;
  onPublish: () => Promise<void>;
  error: boolean;
}) {
  return (
    <>
      <EditorActions
        dirty={dirty}
        hasDraft={Boolean(draft)}
        saving={saving}
        publishing={publishing}
        onSave={onSave}
        onPublish={onPublish}
      />
      <Field label={title}>
        <textarea
          className="min-h-96 font-mono"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
      </Field>
      {error && <PageError compact title={`${title} change failed`} />}
    </>
  );
}
