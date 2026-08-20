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
  applyPromptSetAdminV1TenantsTenantIdPromptSetApplyPost,
  createConfigDraftAdminV1TenantsTenantIdConfigDraftsPost,
  publishConfigDraftAdminV1TenantsTenantIdConfigDraftsRevisionIdPublishPost,
  updateConfigDraftAdminV1TenantsTenantIdConfigDraftsRevisionIdPatch,
} from "../../../core/api/generated/admin-tenants/admin-tenants";
import { EditorActions, Field } from "../../../core/configuration/editor";
import { useTenant } from "../../../core/tenant/use-tenant";
import { toAgentForm, toUpdateRequest } from "../lib/mappings";
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
      const request = toUpdateRequest(configuration.config, form);
      const response = configuration.configDraft
        ? await updateConfigDraftAdminV1TenantsTenantIdConfigDraftsRevisionIdPatch(
            tenantId,
            configuration.configDraft.id,
            request,
            {
              headers: { "If-Match": `"${configuration.configDraft.version}"` },
            },
          )
        : await createConfigDraftAdminV1TenantsTenantIdConfigDraftsPost(
            tenantId,
            request,
          );
      responseData(response);
      await canonical();
    },
  });
  const publish = useMutation({
    mutationFn: async () => {
      responseData(
        await publishConfigDraftAdminV1TenantsTenantIdConfigDraftsRevisionIdPublishPost(
          tenantId,
          configuration.configDraft?.id ?? "",
        ),
      );
      responseData(
        await applyPromptSetAdminV1TenantsTenantIdPromptSetApplyPost(tenantId),
      );
      await canonical();
    },
  });
  const update = (field: keyof AgentForm, value: string) =>
    setForm({ ...form, [field]: value });
  const destinations = Object.entries(form.handoff);
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
            <select
              value={form.profile}
              onChange={(event) => update("profile", event.target.value)}
            >
              {configuration.profiles.map((profile) => (
                <option key={profile} value={profile}>
                  {profile.replaceAll("_", " ")}
                </option>
              ))}
            </select>
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
          <section className="space-y-4 border-t pt-6">
            <h2 className="text-lg font-semibold">Handoff</h2>
            {destinations.length ? (
              destinations.map(([key, destination]) => (
                <div
                  className="grid gap-4 rounded-md border p-4 sm:grid-cols-2"
                  key={key}
                >
                  <div className="sm:col-span-2 font-medium capitalize">
                    {key.replaceAll("_", " ")}
                  </div>
                  <Field label="Description">
                    <input
                      value={destination.description}
                      onChange={(event) =>
                        setForm({
                          ...form,
                          handoff: {
                            ...form.handoff,
                            [key]: {
                              ...destination,
                              description: event.target.value,
                            },
                          },
                        })
                      }
                    />
                  </Field>
                  <Field label="Phone number">
                    <input
                      type="tel"
                      value={destination.phoneNumber}
                      onChange={(event) =>
                        setForm({
                          ...form,
                          handoff: {
                            ...form.handoff,
                            [key]: {
                              ...destination,
                              phoneNumber: event.target.value,
                            },
                          },
                        })
                      }
                    />
                  </Field>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted">
                No handoff destinations configured.
              </p>
            )}
          </section>
        </div>
        {(save.isError || publish.isError) && (
          <PageError compact title="Agent change failed" />
        )}
      </div>
    </>
  );
}
