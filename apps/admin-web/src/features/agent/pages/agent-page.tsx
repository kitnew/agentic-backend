import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  EmptyState,
  PageError,
  PageHeader,
  PageLoading,
} from "../../../components/page-states";
import { responseData } from "../../../core/api/client";
import {
  publishComponentAdminV1TenantsTenantIdComponentsComponentPublishPost,
  saveDraftAdminV1TenantsTenantIdComponentsComponentDraftPut,
} from "../../../core/api/generated/admin-tenant-components/admin-tenant-components";
import { EditorActions, Field } from "../../../core/configuration/editor";
import { useTenant } from "../../../core/tenant/use-tenant";
import { toAgentForm, toAgentPayload } from "../lib/mappings";
import {
  agentQueryKey,
  getAgentConfiguration,
  useAgentConfiguration,
} from "../queries/agent-queries";
import type { AgentForm } from "../schemas/agent-form";

export function AgentPage() {
  const { tenantId } = useTenant();
  if (!tenantId) return <EmptyState title="Select a tenant" />;
  return <AgentPageContents tenantId={tenantId} />;
}

function AgentPageContents({ tenantId }: { tenantId: string }) {
  const query = useAgentConfiguration(tenantId);
  if (query.isPending) return <PageLoading />;
  if (query.isError)
    return (
      <PageError
        title="Agent configuration could not be loaded"
        onRetry={() => query.refetch()}
      />
    );
  return (
    <AgentEditor
      key={tenantId}
      tenantId={tenantId}
      configuration={query.data}
    />
  );
}

function AgentEditor({
  tenantId,
  configuration,
}: {
  tenantId: string;
  configuration: Awaited<ReturnType<typeof getAgentConfiguration>>;
}) {
  const queryClient = useQueryClient();
  const initial = toAgentForm(configuration.config);
  const [form, setForm] = useState(initial);
  const dirty = JSON.stringify(form) !== JSON.stringify(initial);
  const canonical = async () => {
    const next = await getAgentConfiguration(tenantId);
    queryClient.setQueryData(agentQueryKey(tenantId), next);
    setForm(toAgentForm(next.config));
  };
  const save = useMutation({
    mutationFn: async () => {
      responseData(
        await saveDraftAdminV1TenantsTenantIdComponentsComponentDraftPut(
          tenantId,
          "agent",
          { payload: toAgentPayload(configuration.config, form) },
          configuration.configDraft
            ? {
                headers: {
                  "If-Match": `"${configuration.configDraft.version}"`,
                },
              }
            : undefined,
        ),
      );
      await canonical();
    },
  });
  const publish = useMutation({
    mutationFn: async () => {
      responseData(
        await publishComponentAdminV1TenantsTenantIdComponentsComponentPublishPost(
          tenantId,
          "agent",
          {
            draft_id: configuration.configDraft?.id ?? "",
            version: configuration.configDraft?.version ?? 0,
          },
        ),
      );
      await canonical();
    },
  });
  const update = (field: keyof AgentForm, value: string) =>
    setForm({ ...form, [field]: value });
  return (
    <>
      <PageHeader title="Agent" />
      <div className="max-w-3xl">
        <EditorActions
          dirty={dirty}
          hasDraft={Boolean(configuration.configDraft)}
          saving={save.isPending}
          publishing={publish.isPending}
          onSave={() => save.mutateAsync()}
          onPublish={() => publish.mutateAsync()}
        />
        <div className="space-y-6">
          <Field label="Display Name">
            <input
              value={form.displayName}
              onChange={(event) => update("displayName", event.target.value)}
            />
          </Field>
          <Field label="Greeting">
            <textarea
              rows={4}
              value={form.greeting}
              onChange={(event) => update("greeting", event.target.value)}
            />
          </Field>
          <Field label="Profile">
            <input
              value={form.profile}
              onChange={(event) => update("profile", event.target.value)}
            />
          </Field>
          <section className="space-y-4 border-t pt-6">
            <h2 className="text-lg font-semibold">Contact</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Address">
                <input
                  value={form.address}
                  onChange={(event) => update("address", event.target.value)}
                />
              </Field>
              <Field label="Website">
                <input
                  type="url"
                  value={form.website}
                  onChange={(event) => update("website", event.target.value)}
                />
              </Field>
              <Field label="Email addresses" detail="One per line">
                <textarea
                  rows={3}
                  value={form.emails}
                  onChange={(event) => update("emails", event.target.value)}
                />
              </Field>
              <Field label="Phone numbers" detail="One per line">
                <textarea
                  rows={3}
                  value={form.phones}
                  onChange={(event) => update("phones", event.target.value)}
                />
              </Field>
            </div>
          </section>
        </div>
        {(save.isError || publish.isError) && (
          <PageError compact title="Agent change failed" />
        )}
      </div>
    </>
  );
}
