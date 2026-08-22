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
  componentStateAdminV1TenantsTenantIdComponentsComponentGet,
  publishAllAdminV1TenantsTenantIdComponentsPublishAllPost,
  publishComponentAdminV1TenantsTenantIdComponentsComponentPublishPost,
  saveDraftAdminV1TenantsTenantIdComponentsComponentDraftPut,
} from "../../core/api/generated/admin-tenant-components/admin-tenant-components";
import type { ComponentStateResponse } from "../../core/api/generated/models";
import {
  EditorActions,
  Field,
  StatusBadge,
} from "../../core/configuration/editor";
import { useTenant } from "../../core/tenant/use-tenant";
import { useTenants } from "../../core/tenant/use-tenants";

const components = [
  ["runtime", "Runtime"],
  ["agent", "Agent"],
  ["prompt", "Prompt"],
  ["knowledge", "Knowledge Base"],
  ["capabilities", "Capabilities"],
  ["telephony", "Telephony"],
] as const;

function useCurrentTenant() {
  const { tenantId } = useTenant();
  const tenants = useTenants();
  return {
    tenantId,
    tenant: tenants.data?.find((item) => item.id === tenantId),
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

export function TenantComponentOverviewPage() {
  const { tenantId, tenant } = useCurrentTenant();
  const query = useQuery({
    queryKey: ["admin", "tenant-components", tenantId],
    queryFn: () =>
      Promise.all(
        components.map(
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
      const drafts =
        query.data?.flatMap(([component, state]) =>
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
  if (query.isPending) return <PageLoading />;
  if (query.isError || !tenant)
    return <PageError title="Tenant status could not be loaded" />;
  const states = new Map(query.data);
  const unpublished = query.data.filter(([, state]) => state.draft).length;
  return (
    <>
      <PageHeader title={tenant.display_name} />
      <section className="max-w-2xl">
        <h2 className="mb-4 text-lg font-semibold">Configuration status</h2>
        <div className="divide-y border-y">
          {components.map(([component, label]) => (
            <div
              className="flex items-center justify-between py-3"
              key={component}
            >
              <span>{label}</span>
              <StatusBadge
                status={
                  states.get(component)?.draft
                    ? "Saved · Not published"
                    : "Published"
                }
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

export function TenantComponentEditorPage({
  component,
  title,
}: {
  component: (typeof components)[number][0];
  title: string;
}) {
  const { tenantId } = useCurrentTenant();
  const query = useQuery({
    queryKey: ["admin", "tenant-component", tenantId, component],
    queryFn: () => componentState(tenantId as string, component),
    enabled: Boolean(tenantId),
  });
  if (query.isPending) return <PageLoading />;
  if (query.isError || !tenantId)
    return <PageError title={`${title} could not be loaded`} />;
  return (
    <ComponentEditor
      key={`${tenantId}:${component}:${query.data.draft?.version ?? "active"}`}
      tenantId={tenantId}
      component={component}
      title={title}
      state={query.data}
      refetch={() => query.refetch().then(() => undefined)}
    />
  );
}

function ComponentEditor({
  tenantId,
  component,
  title,
  state,
  refetch,
}: {
  tenantId: string;
  component: (typeof components)[number][0];
  title: string;
  state: ComponentStateResponse;
  refetch: () => Promise<void>;
}) {
  const canonical = JSON.stringify(
    state.draft?.payload ?? state.active_revision?.payload ?? {},
    null,
    2,
  );
  const [text, setText] = useState(canonical);
  const [parseError, setParseError] = useState<string | null>(null);
  useEffect(() => setText(canonical), [canonical]);
  const save = useMutation({
    mutationFn: async () => {
      let payload: Record<string, unknown>;
      try {
        payload = JSON.parse(text) as Record<string, unknown>;
      } catch {
        setParseError("Configuration must be valid JSON.");
        return;
      }
      setParseError(null);
      responseData(
        await saveDraftAdminV1TenantsTenantIdComponentsComponentDraftPut(
          tenantId,
          component,
          { payload },
          state.draft
            ? { headers: { "If-Match": `"${state.draft.version}"` } }
            : undefined,
        ),
      );
      await refetch();
    },
  });
  const publish = useMutation({
    mutationFn: async () => {
      if (!state.draft) return;
      responseData(
        await publishComponentAdminV1TenantsTenantIdComponentsComponentPublishPost(
          tenantId,
          component,
          { draft_id: state.draft.id, version: state.draft.version },
        ),
      );
      await refetch();
    },
  });
  return (
    <>
      <PageHeader title={title} />
      <div className="max-w-4xl">
        <EditorActions
          dirty={text !== canonical}
          hasDraft={Boolean(state.draft)}
          saving={save.isPending}
          publishing={publish.isPending}
          onSave={() => save.mutateAsync()}
          onPublish={() => publish.mutateAsync()}
        />
        <Field label={`${title} configuration`}>
          <textarea
            className="min-h-96 font-mono"
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        </Field>
        {(parseError || save.isError || publish.isError) && (
          <PageError compact title={parseError ?? `${title} change failed`} />
        )}
      </div>
    </>
  );
}
