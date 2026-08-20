import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import {
  PageError,
  PageHeader,
  PageLoading,
} from "../../components/page-states";
import { Button } from "../../components/ui/button";
import { responseData } from "../../core/api/client";
import { showPlatformRuntimeAdminV1PlatformRuntimeGet } from "../../core/api/generated/admin-platform-runtime/admin-platform-runtime";
import { publishTenantAllAdminV1TenantsTenantIdPublishAllPost } from "../../core/api/generated/admin-releases/admin-releases";
import {
  createTenantRuntimeDraftAdminV1TenantsTenantIdRuntimeDraftsPost,
  publishTenantRuntimeDraftAdminV1TenantsTenantIdRuntimeDraftsRevisionIdPublishPost,
  showTenantRuntimeAdminV1TenantsTenantIdRuntimeGet,
  updateTenantRuntimeDraftAdminV1TenantsTenantIdRuntimeDraftsRevisionIdPatch,
} from "../../core/api/generated/admin-tenant-runtime/admin-tenant-runtime";
import {
  createTenantPromptDraftAdminV1TenantsTenantIdTenantPromptDraftsPost,
  getDraftKnowledgeBaseAdminV1TenantsTenantIdKnowledgeBaseDraftGet,
  getPublishedKnowledgeBaseAdminV1TenantsTenantIdKnowledgeBasePublishedGet,
  listConfigRevisionsAdminV1TenantsTenantIdConfigRevisionsGet,
  listTenantPromptRevisionsAdminV1TenantsTenantIdTenantPromptRevisionsGet,
  publishKnowledgeBaseAdminV1TenantsTenantIdKnowledgeBasePublishPost,
  publishTenantPromptDraftAdminV1TenantsTenantIdTenantPromptDraftsRevisionIdPublishPost,
  pushKnowledgeBaseAdminV1TenantsTenantIdKnowledgeBasePushPost,
  showKnowledgeBaseAdminV1TenantsTenantIdKnowledgeBaseGet,
  updateTenantPromptDraftAdminV1TenantsTenantIdTenantPromptDraftsRevisionIdPatch,
} from "../../core/api/generated/admin-tenants/admin-tenants";
import type {
  ConfigRevisionResponse,
  KnowledgeBaseSnapshotResponse,
  KnowledgeBaseStateResponse,
  PlatformRuntimeStateResponse,
  TenantPromptRevisionResponse,
  TenantRuntimeStateResponse,
} from "../../core/api/generated/models";
import {
  EditorActions,
  Field,
  StatusBadge,
} from "../../core/configuration/editor";
import { useTenant } from "../../core/tenant/use-tenant";
import { useTenants } from "../../core/tenant/use-tenants";

function useCurrentTenant() {
  const { tenantId } = useTenant();
  const tenants = useTenants();
  return {
    tenantId,
    tenant: tenants.data?.find((item) => item.id === tenantId),
  };
}

export function TenantsPage() {
  const tenants = useTenants();
  if (tenants.isPending) return <PageLoading />;
  if (tenants.isError)
    return (
      <PageError
        title="Tenants could not be loaded"
        onRetry={() => tenants.refetch()}
      />
    );
  return (
    <>
      <PageHeader title="Tenants" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {tenants.data.map((tenant) => (
          <Link
            className="rounded-lg border bg-panel p-5 transition hover:border-slate-400 hover:shadow-sm"
            key={tenant.id}
            to={`/tenants/${tenant.id}` as never}
          >
            <h2 className="font-semibold">{tenant.display_name}</h2>
            <p className="mt-1 text-sm capitalize text-muted">
              {tenant.business_type.replaceAll("_", " ")}
            </p>
            <p className="mt-7 text-sm font-medium">Open →</p>
          </Link>
        ))}
      </div>
    </>
  );
}

async function tenantStatus(tenantId: string) {
  const [config, prompt, runtime, knowledge] = await Promise.all([
    listConfigRevisionsAdminV1TenantsTenantIdConfigRevisionsGet(tenantId),
    listTenantPromptRevisionsAdminV1TenantsTenantIdTenantPromptRevisionsGet(
      tenantId,
    ),
    showTenantRuntimeAdminV1TenantsTenantIdRuntimeGet(tenantId),
    showKnowledgeBaseAdminV1TenantsTenantIdKnowledgeBaseGet(tenantId),
  ]);
  return {
    config: responseData<ConfigRevisionResponse[]>(config).some(
      (item) => item.status === "draft",
    ),
    prompt: responseData<TenantPromptRevisionResponse[]>(prompt).some(
      (item) => item.status === "draft",
    ),
    runtime: Boolean(
      responseData<TenantRuntimeStateResponse>(runtime).draft_revision,
    ),
    knowledge: Boolean(
      responseData<KnowledgeBaseStateResponse>(knowledge).draft_revision,
    ),
  };
}

export function TenantOverviewPage() {
  const { tenantId, tenant } = useCurrentTenant();
  const query = useQuery({
    queryKey: ["admin", "tenant-status", tenantId],
    queryFn: () => tenantStatus(tenantId as string),
    enabled: Boolean(tenantId),
  });
  const publish = useMutation({
    mutationFn: async () =>
      responseData(
        await publishTenantAllAdminV1TenantsTenantIdPublishAllPost(
          tenantId as string,
        ),
      ),
    onSuccess: () => query.refetch(),
  });
  if (query.isPending) return <PageLoading />;
  if (query.isError || !tenant)
    return <PageError title="Tenant status could not be loaded" />;
  const rows = [
    ["Runtime", query.data.runtime],
    ["Agent", query.data.config],
    ["Prompt", query.data.prompt],
    ["Knowledge Base", query.data.knowledge],
  ] as const;
  const unpublished = rows.filter(([, changed]) => changed).length;
  return (
    <>
      <PageHeader title={tenant.display_name} />
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
          <PageError compact title="Tenant changes could not be published" />
        )}
      </section>
    </>
  );
}

async function runtimeState(tenantId: string) {
  const [tenant, platform] = await Promise.all([
    showTenantRuntimeAdminV1TenantsTenantIdRuntimeGet(tenantId),
    showPlatformRuntimeAdminV1PlatformRuntimeGet(),
  ]);
  return {
    tenant: responseData<TenantRuntimeStateResponse>(tenant),
    platform: responseData<PlatformRuntimeStateResponse>(platform),
  };
}

export function TenantRuntimePage() {
  const { tenantId } = useCurrentTenant();
  const query = useQuery({
    queryKey: ["admin", "tenant-runtime", tenantId],
    queryFn: () => runtimeState(tenantId as string),
    enabled: Boolean(tenantId),
  });
  if (query.isPending) return <PageLoading />;
  if (
    query.isError ||
    !tenantId ||
    !query.data.platform.latest_published_revision
  )
    return <PageError title="Tenant runtime could not be loaded" />;
  return (
    <TenantRuntimeEditor
      key={tenantId}
      tenantId={tenantId}
      state={query.data}
      refetch={() => query.refetch().then(() => undefined)}
    />
  );
}

function TenantRuntimeEditor({
  tenantId,
  state,
  refetch,
}: {
  tenantId: string;
  state: Awaited<ReturnType<typeof runtimeState>>;
  refetch: () => Promise<void>;
}) {
  const saved =
    state.tenant.draft_revision?.settings ??
    state.tenant.latest_published_revision?.settings ??
    {};
  const [model, setModel] = useState(saved.llm?.model ?? "");
  const [voice, setVoice] = useState(saved.tts?.voice_id ?? "");
  const canonical = JSON.stringify(saved);
  const settings = {
    ...(model ? { llm: { model } } : {}),
    ...(voice ? { tts: { voice_id: voice } } : {}),
  };
  const dirty = JSON.stringify(settings) !== canonical;
  const save = useMutation({
    mutationFn: async () => {
      const draft = state.tenant.draft_revision;
      const response = draft
        ? await updateTenantRuntimeDraftAdminV1TenantsTenantIdRuntimeDraftsRevisionIdPatch(
            tenantId,
            draft.id,
            { settings },
            { headers: { "If-Match": `"${draft.version}"` } },
          )
        : await createTenantRuntimeDraftAdminV1TenantsTenantIdRuntimeDraftsPost(
            tenantId,
            { settings },
          );
      responseData(response);
      await refetch();
    },
  });
  const publish = useMutation({
    mutationFn: async () =>
      responseData(
        await publishTenantRuntimeDraftAdminV1TenantsTenantIdRuntimeDraftsRevisionIdPublishPost(
          tenantId,
          state.tenant.draft_revision?.id ?? "",
        ),
      ),
    onSuccess: refetch,
  });
  const defaults = state.platform.latest_published_revision?.policy;
  if (!defaults)
    return <PageError title="Platform runtime could not be loaded" />;
  return (
    <>
      <PageHeader title="Runtime" />
      <div className="max-w-2xl">
        <EditorActions
          dirty={dirty}
          hasDraft={Boolean(state.tenant.draft_revision)}
          saving={save.isPending}
          publishing={publish.isPending}
          onSave={() => save.mutateAsync()}
          onPublish={() => publish.mutateAsync().then(() => undefined)}
        />
        <div className="space-y-6">
          <Field
            label="LLM model"
            detail={`Platform default: ${defaults.llm.model}`}
          >
            <select
              value={model}
              onChange={(event) => setModel(event.target.value)}
            >
              <option value="">Use platform default</option>
              <option value="gpt-4o-mini">gpt-4o-mini</option>
              <option value="gpt-5.6-terra">gpt-5.6-terra</option>
            </select>
          </Field>
          <Field
            label="ElevenLabs Voice ID"
            detail={`Platform default: ${defaults.tts.voice_id}`}
          >
            <input
              placeholder="Use platform default"
              value={voice}
              onChange={(event) => setVoice(event.target.value)}
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

async function promptState(tenantId: string) {
  const revisions = responseData<TenantPromptRevisionResponse[]>(
    await listTenantPromptRevisionsAdminV1TenantsTenantIdTenantPromptRevisionsGet(
      tenantId,
    ),
  );
  return {
    draft: revisions.find((item) => item.status === "draft"),
    published: revisions.find((item) => item.status === "published"),
  };
}

export function TenantPromptPage() {
  const { tenantId } = useCurrentTenant();
  const query = useQuery({
    queryKey: ["admin", "tenant-prompt", tenantId],
    queryFn: () => promptState(tenantId as string),
    enabled: Boolean(tenantId),
  });
  if (query.isPending) return <PageLoading />;
  if (query.isError || !tenantId)
    return <PageError title="Tenant prompt could not be loaded" />;
  return (
    <TenantPromptEditor
      key={tenantId}
      tenantId={tenantId}
      revisions={query.data}
      refetch={() => query.refetch().then(() => undefined)}
    />
  );
}

function TenantPromptEditor({
  tenantId,
  revisions,
  refetch,
}: {
  tenantId: string;
  revisions: Awaited<ReturnType<typeof promptState>>;
  refetch: () => Promise<void>;
}) {
  const canonical = revisions.draft?.text ?? revisions.published?.text ?? "";
  const [text, setText] = useState(canonical);
  const save = useMutation({
    mutationFn: async () => {
      const response = revisions.draft
        ? await updateTenantPromptDraftAdminV1TenantsTenantIdTenantPromptDraftsRevisionIdPatch(
            tenantId,
            revisions.draft.id,
            { text },
            { headers: { "If-Match": `"${revisions.draft.version}"` } },
          )
        : await createTenantPromptDraftAdminV1TenantsTenantIdTenantPromptDraftsPost(
            tenantId,
            { text },
          );
      responseData(response);
      await refetch();
    },
  });
  const publish = useMutation({
    mutationFn: async () =>
      responseData(
        await publishTenantPromptDraftAdminV1TenantsTenantIdTenantPromptDraftsRevisionIdPublishPost(
          tenantId,
          revisions.draft?.id ?? "",
        ),
      ),
    onSuccess: refetch,
  });
  return (
    <>
      <PageHeader title="Prompt" />
      <div className="max-w-4xl">
        <EditorActions
          dirty={text !== canonical}
          hasDraft={Boolean(revisions.draft)}
          saving={save.isPending}
          publishing={publish.isPending}
          onSave={() => save.mutateAsync()}
          onPublish={() => publish.mutateAsync().then(() => undefined)}
        />
        <Field label="Tenant Prompt">
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
    </>
  );
}

async function knowledgeState(tenantId: string) {
  const state = responseData<KnowledgeBaseStateResponse>(
    await showKnowledgeBaseAdminV1TenantsTenantIdKnowledgeBaseGet(tenantId),
  );
  let snapshot: KnowledgeBaseSnapshotResponse | undefined;
  const response = state.draft_revision
    ? await getDraftKnowledgeBaseAdminV1TenantsTenantIdKnowledgeBaseDraftGet(
        tenantId,
      )
    : await getPublishedKnowledgeBaseAdminV1TenantsTenantIdKnowledgeBasePublishedGet(
        tenantId,
      );
  if (response.status === 200)
    snapshot = response.data as KnowledgeBaseSnapshotResponse;
  return {
    state,
    content:
      snapshot?.documents.find((item) => item.key === "knowledge")?.content ??
      "",
  };
}

export function KnowledgeBasePage() {
  const { tenantId } = useCurrentTenant();
  const query = useQuery({
    queryKey: ["admin", "knowledge", tenantId],
    queryFn: () => knowledgeState(tenantId as string),
    enabled: Boolean(tenantId),
  });
  if (query.isPending) return <PageLoading />;
  if (query.isError || !tenantId)
    return <PageError title="Knowledge Base could not be loaded" />;
  return (
    <KnowledgeEditor
      key={tenantId}
      tenantId={tenantId}
      data={query.data}
      refetch={() => query.refetch().then(() => undefined)}
    />
  );
}

function KnowledgeEditor({
  tenantId,
  data,
  refetch,
}: {
  tenantId: string;
  data: Awaited<ReturnType<typeof knowledgeState>>;
  refetch: () => Promise<void>;
}) {
  const [content, setContent] = useState(data.content);
  const save = useMutation({
    mutationFn: async () => {
      responseData(
        await pushKnowledgeBaseAdminV1TenantsTenantIdKnowledgeBasePushPost(
          tenantId,
          {
            documents: [
              { key: "knowledge", media_type: "text/markdown", content },
            ],
          },
        ),
      );
      await refetch();
    },
  });
  const publish = useMutation({
    mutationFn: async () =>
      responseData(
        await publishKnowledgeBaseAdminV1TenantsTenantIdKnowledgeBasePublishPost(
          tenantId,
        ),
      ),
    onSuccess: refetch,
  });
  return (
    <>
      <PageHeader title="Knowledge Base" />
      <div className="max-w-4xl">
        <EditorActions
          dirty={content !== data.content}
          hasDraft={Boolean(data.state.draft_revision)}
          saving={save.isPending}
          publishing={publish.isPending}
          onSave={() => save.mutateAsync()}
          onPublish={() => publish.mutateAsync().then(() => undefined)}
        />
        <Field label="knowledge.md">
          <textarea
            className="min-h-96 font-mono"
            value={content}
            onChange={(event) => setContent(event.target.value)}
          />
        </Field>
        {(save.isError || publish.isError) && (
          <PageError compact title="Knowledge Base change failed" />
        )}
      </div>
    </>
  );
}

export function CapabilitiesPage() {
  return (
    <>
      <PageHeader title="Capabilities" />
      <p className="text-muted">Capability management is in development.</p>
    </>
  );
}
