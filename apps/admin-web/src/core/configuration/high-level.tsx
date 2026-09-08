import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { PageError, PageLoading } from "../../components/page-states";
import { Button } from "../../components/ui/button";
import { managementMutationOptions, responseData } from "../api/client";
import {
  applyConfigurationManagementV1PlatformConfigurationPut,
  applyConfigurationManagementV1TenantsTenantIdConfigurationPut,
  applySystemConfigurationManagementV1SystemConfigurationPut,
  getConfigurationManagementV1PlatformConfigurationGet,
  getConfigurationManagementV1TenantsTenantIdConfigurationGet,
  getSystemConfigurationManagementV1SystemConfigurationGet,
  type PlatformConfiguration,
  type PlatformConfigurationDesired,
  planConfigurationManagementV1PlatformConfigurationPlanPost,
  planConfigurationManagementV1TenantsTenantIdConfigurationPlanPost,
  planSystemConfigurationManagementV1SystemConfigurationPlanPost,
  publishConfigurationManagementV1PlatformConfigurationPublishPost,
  publishConfigurationManagementV1TenantsTenantIdConfigurationPublishPost,
  type SystemConfiguration,
  type SystemConfigurationDesired,
  type TenantConfiguration,
  type TenantConfigurationDesired,
} from "../api/control-plane";
import { normalizeApiError } from "../api/errors";
import { CodeEditor } from "../ui/foundation";

export type Snapshot<T> = {
  value: T;
  etag: string | null;
  initialized: boolean;
  publishable: boolean;
};

function selected<T>(state: { active?: T | null; draft?: T | null }): T {
  const value = state.draft ?? state.active;
  if (!value) throw new Error("Configuration is incomplete");
  return value;
}

export function systemDesired(
  value: SystemConfiguration,
): SystemConfigurationDesired {
  return {
    stt_defaults: value.stt_defaults,
    llm_defaults: value.llm_defaults,
    tts_defaults: value.tts_defaults,
    realtime_defaults: value.realtime_defaults,
    policies: value.policies,
  };
}

export function platformDesired(
  value: PlatformConfiguration,
): PlatformConfigurationDesired {
  return {
    system_prompt: selected(value.system_prompt),
    profiles: value.profiles.map((profile) => ({
      key: profile.key,
      name: profile.name,
      description: profile.description,
      status: profile.status,
      prompt: selected(profile.prompt),
    })),
    interaction_modes: value.interaction_modes.map((mode) => ({
      key: mode.key,
      name: mode.name,
      description: mode.description,
      status: mode.status,
      prompt: selected(mode.prompt),
    })),
  };
}

export function tenantDesired(
  value: TenantConfiguration,
): TenantConfigurationDesired {
  return {
    tenant_prompt: selected(value.versioned.tenant_prompt),
    knowledge: selected(value.versioned.knowledge),
    agent_personality: selected(value.versioned.agent_personality),
    business_info: selected(value.versioned.business_info),
    actions_definition: selected(value.versioned.actions_definition),
    architecture: value.live.architecture,
    profile_reference: value.live.profile_reference,
    runtime_overrides: value.live.runtime_overrides,
    actions_availability: value.live.actions_availability,
  };
}

function notInitialized<T>(error: unknown): Snapshot<T> {
  if (normalizeApiError(error).status === 404)
    return {
      value: {} as T,
      etag: null,
      initialized: false,
      publishable: false,
    };
  throw error;
}

function planDetails(plan: unknown) {
  const value =
    typeof plan === "object" && plan !== null
      ? (plan as Record<string, unknown>)
      : {};
  return {
    valid: value.valid,
    changes: value.changes ?? {
      catalog_changes: value.catalog_changes ?? [],
      draft_changes: value.draft_changes ?? [],
    },
    warnings: value.warnings ?? [],
    errors: value.errors ?? [],
  };
}

function PlanResult({ plan }: { plan: unknown }) {
  const details = planDetails(plan);
  return (
    <section aria-label="Plan result" className="mt-4 rounded-md border p-4">
      <p>valid: {String(details.valid)}</p>
      <pre className="mt-2 overflow-auto whitespace-pre-wrap text-sm">
        {JSON.stringify(
          {
            changes: details.changes,
            warnings: details.warnings,
            errors: details.errors,
          },
          null,
          2,
        )}
      </pre>
    </section>
  );
}

export function HighLevelEditor<T>({
  title,
  queryKey,
  read,
  plan,
  apply,
  publish,
}: {
  title: string;
  queryKey: readonly unknown[];
  read: () => Promise<Snapshot<T>>;
  plan: (value: T) => Promise<unknown>;
  apply: (value: T, snapshot: Snapshot<T>) => Promise<unknown>;
  publish?: (snapshot: Snapshot<T>) => Promise<unknown>;
}) {
  const query = useQuery({ queryKey, queryFn: read });
  const [text, setText] = useState("");
  useEffect(() => {
    if (query.data) setText(JSON.stringify(query.data.value, null, 2));
  }, [query.data]);

  const parsed = (() => {
    try {
      return JSON.parse(text) as T;
    } catch {
      return undefined;
    }
  })();
  const snapshot = query.data;
  const planMutation = useMutation({
    mutationFn: () => {
      if (parsed === undefined) throw new Error("Enter valid JSON");
      return plan(parsed);
    },
  });
  const applyMutation = useMutation({
    mutationFn: () => {
      if (parsed === undefined || !snapshot)
        throw new Error("Enter valid JSON");
      if (snapshot.initialized && !snapshot.etag)
        throw new Error(
          "Configuration ETag is missing; reload before applying",
        );
      return apply(parsed, snapshot);
    },
    onSuccess: async () => {
      await query.refetch();
    },
  });
  const publishMutation = useMutation({
    mutationFn: () => {
      if (!snapshot || !publish || !snapshot.etag)
        throw new Error("Nothing to publish");
      return publish(snapshot);
    },
    onSuccess: async () => {
      await query.refetch();
    },
  });

  if (query.isPending) return <PageLoading />;
  if (query.isError)
    return (
      <PageError
        error={query.error}
        onRetry={() => void query.refetch().catch(() => undefined)}
        title={`${title} could not be loaded`}
      />
    );
  if (!snapshot) return null;

  const original = JSON.stringify(snapshot.value, null, 2);
  const dirty = text !== original;
  const busy =
    query.isFetching ||
    planMutation.isPending ||
    applyMutation.isPending ||
    publishMutation.isPending;
  const canApply =
    parsed !== undefined && (!snapshot.initialized || snapshot.etag);
  const reload = async () => {
    planMutation.reset();
    applyMutation.reset();
    publishMutation.reset();
    await query.refetch();
  };

  return (
    <>
      <div className="mb-7 border-b pb-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
            <p className="mt-1 text-sm text-muted" role="status">
              {snapshot.initialized ? "Initialized" : "Not initialized"}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={busy}
              onClick={() => void reload()}
              variant="outline"
            >
              Reload
            </Button>
            <Button
              disabled={parsed === undefined || busy}
              loading={planMutation.isPending}
              loadingLabel="Planning…"
              onClick={() =>
                void planMutation.mutateAsync().catch(() => undefined)
              }
              variant="outline"
            >
              Plan
            </Button>
            <Button
              disabled={!canApply || busy}
              loading={applyMutation.isPending}
              loadingLabel="Applying…"
              onClick={() =>
                void applyMutation.mutateAsync().catch(() => undefined)
              }
            >
              Apply
            </Button>
            {publish && (
              <Button
                disabled={
                  dirty ||
                  !snapshot.initialized ||
                  !snapshot.publishable ||
                  busy
                }
                loading={publishMutation.isPending}
                loadingLabel="Publishing…"
                onClick={() =>
                  void publishMutation.mutateAsync().catch(() => undefined)
                }
                variant="outline"
              >
                Publish
              </Button>
            )}
          </div>
        </div>
      </div>
      <CodeEditor
        label={`${title} Desired JSON`}
        minHeight={520}
        onChange={setText}
        value={text}
      />
      {planMutation.data !== undefined && (
        <PlanResult plan={planMutation.data} />
      )}
      {(planMutation.isError ||
        applyMutation.isError ||
        publishMutation.isError) && (
        <PageError
          compact
          error={
            planMutation.error ?? applyMutation.error ?? publishMutation.error
          }
          onRetry={() => void reload().catch(() => undefined)}
          title={`${title} change failed`}
        />
      )}
    </>
  );
}

export function SystemConfigurationEditor() {
  return (
    <HighLevelEditor<SystemConfigurationDesired>
      title="System Configuration"
      queryKey={["control-plane", "system-configuration"]}
      read={async () => {
        try {
          const response =
            await getSystemConfigurationManagementV1SystemConfigurationGet();
          const value = responseData<SystemConfiguration>(response);
          return {
            value: systemDesired(value),
            etag: response.headers.get("etag"),
            initialized: true,
            publishable: false,
          };
        } catch (error) {
          return notInitialized<SystemConfigurationDesired>(error);
        }
      }}
      plan={async (value) =>
        responseData(
          await planSystemConfigurationManagementV1SystemConfigurationPlanPost(
            value,
          ),
        )
      }
      apply={async (value, snapshot) =>
        responseData(
          await applySystemConfigurationManagementV1SystemConfigurationPut(
            value,
            managementMutationOptions(snapshot.etag, !snapshot.initialized),
          ),
        )
      }
    />
  );
}

export function PlatformConfigurationEditor() {
  return (
    <HighLevelEditor<PlatformConfigurationDesired>
      title="Platform Configuration"
      queryKey={["control-plane", "platform-configuration"]}
      read={async () => {
        try {
          const response =
            await getConfigurationManagementV1PlatformConfigurationGet();
          const value = responseData<PlatformConfiguration>(response);
          return {
            value: platformDesired(value),
            etag: response.headers.get("etag"),
            initialized: true,
            publishable: value.status.publishable,
          };
        } catch (error) {
          return notInitialized<PlatformConfigurationDesired>(error);
        }
      }}
      plan={async (value) =>
        responseData(
          await planConfigurationManagementV1PlatformConfigurationPlanPost(
            value,
          ),
        )
      }
      apply={async (value, snapshot) =>
        responseData(
          await applyConfigurationManagementV1PlatformConfigurationPut(
            value,
            managementMutationOptions(snapshot.etag, !snapshot.initialized),
          ),
        )
      }
      publish={async (snapshot) =>
        responseData(
          await publishConfigurationManagementV1PlatformConfigurationPublishPost(
            managementMutationOptions(snapshot.etag),
          ),
        )
      }
    />
  );
}

export function TenantConfigurationEditor({ tenantId }: { tenantId: string }) {
  return (
    <HighLevelEditor<TenantConfigurationDesired>
      title="Tenant Configuration"
      queryKey={["control-plane", "tenant-configuration", tenantId]}
      read={async () => {
        try {
          const response =
            await getConfigurationManagementV1TenantsTenantIdConfigurationGet(
              tenantId,
            );
          const value = responseData<TenantConfiguration>(response);
          return {
            value: tenantDesired(value),
            etag: response.headers.get("etag"),
            initialized: true,
            publishable: value.status.publishable,
          };
        } catch (error) {
          return notInitialized<TenantConfigurationDesired>(error);
        }
      }}
      plan={async (value) =>
        responseData(
          await planConfigurationManagementV1TenantsTenantIdConfigurationPlanPost(
            tenantId,
            value,
          ),
        )
      }
      apply={async (value, snapshot) =>
        responseData(
          await applyConfigurationManagementV1TenantsTenantIdConfigurationPut(
            tenantId,
            value,
            managementMutationOptions(snapshot.etag, !snapshot.initialized),
          ),
        )
      }
      publish={async (snapshot) =>
        responseData(
          await publishConfigurationManagementV1TenantsTenantIdConfigurationPublishPost(
            tenantId,
            managementMutationOptions(snapshot.etag),
          ),
        )
      }
    />
  );
}
