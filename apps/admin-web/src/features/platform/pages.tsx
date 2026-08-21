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
  createProfilePromptDraftAdminV1PlatformPromptsProfilesDraftsPost,
  createSystemPromptDraftAdminV1PlatformPromptsSystemDraftsPost,
  listProfilePromptRevisionsAdminV1PlatformPromptsProfilesKeyRevisionsGet,
  listProfilesAdminV1PlatformPromptsProfilesGet,
  listSystemPromptRevisionsAdminV1PlatformPromptsSystemKeyRevisionsGet,
  publishProfilePromptDraftAdminV1PlatformPromptsProfilesDraftsRevisionIdPublishPost,
  publishSystemPromptDraftAdminV1PlatformPromptsSystemDraftsRevisionIdPublishPost,
  updateProfilePromptDraftAdminV1PlatformPromptsProfilesDraftsRevisionIdPatch,
  updateSystemPromptDraftAdminV1PlatformPromptsSystemDraftsRevisionIdPatch,
} from "../../core/api/generated/admin-platform-prompts/admin-platform-prompts";
import {
  createPlatformRuntimeDraftAdminV1PlatformRuntimeDraftsPost,
  publishPlatformRuntimeDraftAdminV1PlatformRuntimeDraftsRevisionIdPublishPost,
  showPlatformRuntimeAdminV1PlatformRuntimeGet,
  updatePlatformRuntimeDraftAdminV1PlatformRuntimeDraftsRevisionIdPatch,
} from "../../core/api/generated/admin-platform-runtime/admin-platform-runtime";
import { publishPlatformAllAdminV1PlatformPublishAllPost } from "../../core/api/generated/admin-releases/admin-releases";
import type {
  PlatformRuntimePolicy,
  PlatformRuntimeStateResponse,
  PromptTextRevisionResponse,
} from "../../core/api/generated/models";
import {
  EditorActions,
  Field,
  StatusBadge,
} from "../../core/configuration/editor";

const platformKey = ["admin", "platform"];

const isReasoningModel = (model: string) =>
  /^(gpt-5|o1|o3|o4)/.test(model.split("/").pop()?.toLowerCase() ?? "");

function draftAndPublished(revisions: PromptTextRevisionResponse[]) {
  return {
    draft: revisions.find((item) => item.status === "draft"),
    published: revisions.find((item) => item.status === "published"),
  };
}

async function platformState() {
  const [runtime, profiles, system] = await Promise.all([
    showPlatformRuntimeAdminV1PlatformRuntimeGet(),
    listProfilesAdminV1PlatformPromptsProfilesGet(),
    listSystemPromptRevisionsAdminV1PlatformPromptsSystemKeyRevisionsGet(
      "default",
    ),
  ]);
  const profileKeys = responseData<string[]>(profiles);
  const profileRevisions = await Promise.all(
    profileKeys.map(async (key) => ({
      key,
      revisions: responseData<PromptTextRevisionResponse[]>(
        await listProfilePromptRevisionsAdminV1PlatformPromptsProfilesKeyRevisionsGet(
          key,
        ),
      ),
    })),
  );
  return {
    runtime: responseData<PlatformRuntimeStateResponse>(runtime),
    system: draftAndPublished(
      responseData<PromptTextRevisionResponse[]>(system),
    ),
    profiles: profileRevisions.map(({ key, revisions }) => ({
      key,
      ...draftAndPublished(revisions),
    })),
  };
}

export function PlatformOverviewPage() {
  const query = useQuery({ queryKey: platformKey, queryFn: platformState });
  const publish = useMutation({
    mutationFn: async () =>
      responseData(await publishPlatformAllAdminV1PlatformPublishAllPost()),
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
    ["Runtime", Boolean(query.data.runtime.draft_revision)],
    ["System Prompt", Boolean(query.data.system.draft)],
    ["Profile Prompts", query.data.profiles.some((item) => item.draft)],
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
            {unpublished} unpublished{" "}
            {unpublished === 1 ? "section" : "sections"}
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

async function runtimeState() {
  return responseData<PlatformRuntimeStateResponse>(
    await showPlatformRuntimeAdminV1PlatformRuntimeGet(),
  );
}

export function PlatformRuntimePage() {
  const query = useQuery({
    queryKey: [...platformKey, "runtime"],
    queryFn: runtimeState,
  });
  if (query.isPending) return <PageLoading />;
  if (
    query.isError ||
    (!query.data.draft_revision && !query.data.latest_published_revision)
  )
    return (
      <PageError
        title="Platform runtime could not be loaded"
        onRetry={() => query.refetch()}
      />
    );
  return (
    <PlatformRuntimeEditor
      state={query.data}
      refetch={() => query.refetch().then(() => undefined)}
    />
  );
}

function PlatformRuntimeEditor({
  state,
  refetch,
}: {
  state: PlatformRuntimeStateResponse;
  refetch: () => Promise<void>;
}) {
  const canonical =
    state.draft_revision?.policy ?? state.latest_published_revision?.policy;
  const [policy, setPolicy] = useState<PlatformRuntimePolicy>(
    canonical as PlatformRuntimePolicy,
  );
  useEffect(() => setPolicy(canonical as PlatformRuntimePolicy), [canonical]);
  const dirty = JSON.stringify(policy) !== JSON.stringify(canonical);
  const save = useMutation({
    mutationFn: async () => {
      const response = state.draft_revision
        ? await updatePlatformRuntimeDraftAdminV1PlatformRuntimeDraftsRevisionIdPatch(
            state.draft_revision.id,
            { policy },
            { headers: { "If-Match": `"${state.draft_revision.version}"` } },
          )
        : await createPlatformRuntimeDraftAdminV1PlatformRuntimeDraftsPost({
            policy,
          });
      responseData(response);
      await refetch();
    },
  });
  const publish = useMutation({
    mutationFn: async () =>
      responseData(
        await publishPlatformRuntimeDraftAdminV1PlatformRuntimeDraftsRevisionIdPublishPost(
          state.draft_revision?.id ?? "",
        ),
      ),
    onSuccess: refetch,
  });
  const number = (
    section: keyof PlatformRuntimePolicy,
    key: string,
    value: string,
  ) =>
    setPolicy({
      ...policy,
      [section]: { ...policy[section], [key]: Number(value) },
    });
  const text = (
    section: keyof PlatformRuntimePolicy,
    key: string,
    value: string,
  ) =>
    setPolicy({ ...policy, [section]: { ...policy[section], [key]: value } });
  const reasoningModel = isReasoningModel(policy.llm.model);
  return (
    <>
      <PageHeader title="Runtime" />
      <div className="max-w-3xl">
        <EditorActions
          dirty={dirty}
          hasDraft={Boolean(state.draft_revision)}
          saving={save.isPending}
          publishing={publish.isPending}
          onSave={() => save.mutateAsync()}
          onPublish={() => publish.mutateAsync().then(() => undefined)}
        />
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="LLM model">
            <input
              value={policy.llm.model}
              onChange={(event) => {
                const model = event.target.value;
                setPolicy({
                  ...policy,
                  llm: {
                    ...policy.llm,
                    model,
                    reasoning_effort: isReasoningModel(model)
                      ? (policy.llm.reasoning_effort ?? "none")
                      : "none",
                    ...(isReasoningModel(model) ? { temperature: null } : {}),
                  },
                });
              }}
            />
          </Field>
          <Field label="LLM reasoning effort">
            <select
              disabled={!reasoningModel}
              value={policy.llm.reasoning_effort ?? "none"}
              onChange={(event) =>
                text("llm", "reasoning_effort", event.target.value)
              }
            >
              {(
                reasoningModel
                  ? (["none", "low", "medium", "high", "xhigh", "max"] as const)
                  : (["none"] as const)
              ).map((effort) => (
                <option key={effort} value={effort}>
                  {effort}
                </option>
              ))}
            </select>
          </Field>
          {!reasoningModel && (
            <Field label="LLM temperature">
              <input
                min="0"
                max="2"
                step="0.1"
                type="number"
                value={policy.llm.temperature ?? ""}
                onChange={(event) =>
                  number("llm", "temperature", event.target.value)
                }
              />
            </Field>
          )}
          <Field label="ElevenLabs voice ID">
            <input
              value={policy.tts.voice_id}
              onChange={(event) => text("tts", "voice_id", event.target.value)}
            />
          </Field>
          <Field label="ElevenLabs TTS model">
            <input
              value={policy.tts.model}
              onChange={(event) => text("tts", "model", event.target.value)}
            />
          </Field>
          <Field label="ElevenLabs STT model">
            <input
              value={policy.stt.model}
              onChange={(event) => text("stt", "model", event.target.value)}
            />
          </Field>
          <Field label="Local VAD activation threshold">
            <input
              min="0"
              max="1"
              step="0.01"
              type="number"
              value={policy.local_vad.activation_threshold}
              onChange={(event) =>
                number("local_vad", "activation_threshold", event.target.value)
              }
            />
          </Field>
          <Field label="Minimum speech (seconds)">
            <input
              min="0.01"
              step="0.01"
              type="number"
              value={policy.local_vad.min_speech_seconds}
              onChange={(event) =>
                number("local_vad", "min_speech_seconds", event.target.value)
              }
            />
          </Field>
          <Field label="Minimum silence (seconds)">
            <input
              min="0.01"
              step="0.01"
              type="number"
              value={policy.local_vad.min_silence_seconds}
              onChange={(event) =>
                number("local_vad", "min_silence_seconds", event.target.value)
              }
            />
          </Field>
          <Field label="STT activity threshold">
            <input
              min="0"
              max="1"
              step="0.01"
              type="number"
              value={policy.stt.server_vad.activity_threshold}
              onChange={(event) =>
                setPolicy({
                  ...policy,
                  stt: {
                    ...policy.stt,
                    server_vad: {
                      ...policy.stt.server_vad,
                      activity_threshold: Number(event.target.value),
                    },
                  },
                })
              }
            />
          </Field>
          <Field label="STT minimum speech (ms)">
            <input
              min="1"
              type="number"
              value={policy.stt.server_vad.min_speech_ms}
              onChange={(event) =>
                setPolicy({
                  ...policy,
                  stt: {
                    ...policy.stt,
                    server_vad: {
                      ...policy.stt.server_vad,
                      min_speech_ms: Number(event.target.value),
                    },
                  },
                })
              }
            />
          </Field>
          <Field label="STT minimum silence (ms)">
            <input
              min="1"
              type="number"
              value={policy.stt.server_vad.min_silence_ms}
              onChange={(event) =>
                setPolicy({
                  ...policy,
                  stt: {
                    ...policy.stt,
                    server_vad: {
                      ...policy.stt.server_vad,
                      min_silence_ms: Number(event.target.value),
                    },
                  },
                })
              }
            />
          </Field>
          <Field label="STT silence threshold (seconds)">
            <input
              min="0.01"
              step="0.01"
              type="number"
              value={policy.stt.server_vad.silence_threshold_seconds}
              onChange={(event) =>
                setPolicy({
                  ...policy,
                  stt: {
                    ...policy.stt,
                    server_vad: {
                      ...policy.stt.server_vad,
                      silence_threshold_seconds: Number(event.target.value),
                    },
                  },
                })
              }
            />
          </Field>
          <Field label="Endpointing minimum (seconds)">
            <input
              min="0.01"
              step="0.01"
              type="number"
              value={policy.turn.min_endpointing_delay_seconds}
              onChange={(event) =>
                number(
                  "turn",
                  "min_endpointing_delay_seconds",
                  event.target.value,
                )
              }
            />
          </Field>
          <Field label="Endpointing maximum (seconds)">
            <input
              min="0.01"
              step="0.01"
              type="number"
              value={policy.turn.max_endpointing_delay_seconds}
              onChange={(event) =>
                number(
                  "turn",
                  "max_endpointing_delay_seconds",
                  event.target.value,
                )
              }
            />
          </Field>
        </div>
        {(save.isError || publish.isError) && (
          <PageError compact title="Runtime change failed" />
        )}
      </div>
    </>
  );
}

function PromptEditor({ profile }: { profile?: string }) {
  const key = profile ?? "default";
  const query = useQuery({
    queryKey: [...platformKey, profile ? "profile" : "system", key],
    queryFn: async () =>
      draftAndPublished(
        responseData<PromptTextRevisionResponse[]>(
          profile
            ? await listProfilePromptRevisionsAdminV1PlatformPromptsProfilesKeyRevisionsGet(
                key,
              )
            : await listSystemPromptRevisionsAdminV1PlatformPromptsSystemKeyRevisionsGet(
                key,
              ),
        ),
      ),
  });
  if (query.isPending) return <PageLoading />;
  if (query.isError) return <PageError title="Prompt could not be loaded" />;
  return (
    <PromptEditorForm
      key={key}
      profile={profile}
      revisions={query.data}
      refetch={() => query.refetch().then(() => undefined)}
    />
  );
}

function PromptEditorForm({
  profile,
  revisions,
  refetch,
}: {
  profile?: string;
  revisions: ReturnType<typeof draftAndPublished>;
  refetch: () => Promise<void>;
}) {
  const canonical = revisions.draft?.text ?? revisions.published?.text ?? "";
  const [text, setText] = useState(canonical);
  useEffect(() => setText(canonical), [canonical]);
  const dirty = text !== canonical;
  const save = useMutation({
    mutationFn: async () => {
      const response = revisions.draft
        ? profile
          ? await updateProfilePromptDraftAdminV1PlatformPromptsProfilesDraftsRevisionIdPatch(
              revisions.draft.id,
              { text },
              { headers: { "If-Match": `"${revisions.draft.version}"` } },
            )
          : await updateSystemPromptDraftAdminV1PlatformPromptsSystemDraftsRevisionIdPatch(
              revisions.draft.id,
              { text },
              { headers: { "If-Match": `"${revisions.draft.version}"` } },
            )
        : profile
          ? await createProfilePromptDraftAdminV1PlatformPromptsProfilesDraftsPost(
              { key: profile, text },
            )
          : await createSystemPromptDraftAdminV1PlatformPromptsSystemDraftsPost(
              { key: "default", text },
            );
      responseData(response);
      await refetch();
    },
  });
  const publish = useMutation({
    mutationFn: async () =>
      responseData(
        profile
          ? await publishProfilePromptDraftAdminV1PlatformPromptsProfilesDraftsRevisionIdPublishPost(
              revisions.draft?.id ?? "",
            )
          : await publishSystemPromptDraftAdminV1PlatformPromptsSystemDraftsRevisionIdPublishPost(
              revisions.draft?.id ?? "",
            ),
      ),
    onSuccess: refetch,
  });
  return (
    <div className="max-w-4xl">
      <EditorActions
        dirty={dirty}
        hasDraft={Boolean(revisions.draft)}
        saving={save.isPending}
        publishing={publish.isPending}
        onSave={() => save.mutateAsync()}
        onPublish={() => publish.mutateAsync().then(() => undefined)}
      />
      <Field label={profile ? "Profile Prompt" : "System Prompt"}>
        <textarea
          className="min-h-96 font-mono"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
      </Field>
      {(save.isError || publish.isError) && (
        <PageError compact title="Prompt change failed" />
      )}
    </div>
  );
}

export function PlatformSystemPromptPage() {
  return (
    <>
      <PageHeader title="System Prompt" />
      <PromptEditor />
    </>
  );
}

export function PlatformProfilePromptPage() {
  const profiles = useQuery({
    queryKey: [...platformKey, "profiles"],
    queryFn: async () =>
      responseData<string[]>(
        await listProfilesAdminV1PlatformPromptsProfilesGet(),
      ),
  });
  const [selected, setSelected] = useState("");
  useEffect(() => {
    if (!selected && profiles.data?.[0]) setSelected(profiles.data[0]);
  }, [profiles.data, selected]);
  if (profiles.isPending) return <PageLoading />;
  if (profiles.isError || !selected)
    return <PageError title="Profiles could not be loaded" />;
  return (
    <>
      <PageHeader title="Profile Prompt" />
      <div className="mb-6 max-w-sm">
        <Field label="Profile">
          <select
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
          >
            {profiles.data.map((profile) => (
              <option key={profile} value={profile}>
                {profile.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <PromptEditor profile={selected} />
    </>
  );
}
