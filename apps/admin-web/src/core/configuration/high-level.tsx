import { useMutation, useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useRef, useState } from "react";

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
import { semanticSerialize } from "./authoring";
import {
  emptyPlatformFormState,
  emptySystemFormState,
  emptyTenantFormState,
  PlatformConfigurationForm,
  platformDesiredFromForm,
  platformFormState,
  SystemConfigurationForm,
  systemDesiredFromForm,
  systemFormState,
  TenantConfigurationForm,
  tenantDesiredFromForm,
  tenantFormState,
  type ValidationMessages,
} from "./forms";

export type Snapshot<T> = {
  value: T;
  etag: string | null;
  initialized: boolean;
  publishable: boolean;
  hasDraft: boolean;
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

function notInitialized<T>(error: unknown, value: T): Snapshot<T> {
  if (normalizeApiError(error).status === 404)
    return {
      value,
      etag: null,
      initialized: false,
      publishable: false,
      hasDraft: false,
    };
  throw error;
}

type PlanDetails = {
  valid: boolean;
  changes: Array<{ operation: string; path: string }>;
  catalogChanges: Array<{ operation: string; path: string }>;
  draftChanges: Array<{ operation: string; path: string }>;
  immediateChanges: Array<{ operation: string; path: string }>;
  warnings: string[];
  errors: Array<{ path: string; code: string; message: string }>;
};

function changes(value: unknown): Array<{ operation: string; path: string }> {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is { operation: string; path: string } =>
      typeof item === "object" &&
      item !== null &&
      typeof item.operation === "string" &&
      typeof item.path === "string",
  );
}

function planDetails(plan: unknown): PlanDetails {
  const value =
    typeof plan === "object" && plan !== null
      ? (plan as Record<string, unknown>)
      : {};
  const nestedChanges =
    typeof value.changes === "object" && value.changes !== null
      ? (value.changes as Record<string, unknown>)
      : {};
  const errors = Array.isArray(value.errors)
    ? value.errors.filter(
        (item): item is { path: string; code: string; message: string } =>
          typeof item === "object" &&
          item !== null &&
          typeof item.path === "string" &&
          typeof item.code === "string" &&
          typeof item.message === "string",
      )
    : [];
  return {
    valid: value.valid === true,
    changes: changes(value.changes),
    catalogChanges: changes(value.catalog_changes),
    draftChanges: changes(value.draft_changes ?? nestedChanges.draft),
    immediateChanges: changes(nestedChanges.immediate),
    warnings: Array.isArray(value.warnings)
      ? value.warnings.filter(
          (item): item is string => typeof item === "string",
        )
      : [],
    errors,
  };
}

function ChangeList({
  label,
  items,
}: {
  label: string;
  items: Array<{ operation: string; path: string }>;
}) {
  if (!items.length) return null;
  return (
    <div className="mt-3">
      <h3 className="font-medium">{label}</h3>
      <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
        {items.map((item) => (
          <li key={`${label}:${item.operation}:${item.path}`}>
            {item.path}: {item.operation}
          </li>
        ))}
      </ul>
    </div>
  );
}

function PlanResult({ plan }: { plan: unknown }) {
  const details = planDetails(plan);
  return (
    <section aria-label="Plan result" className="mt-4 rounded-md border p-4">
      <h2 className="font-semibold">
        {details.valid ? "Plan valid" : "Plan needs attention"}
      </h2>
      <ChangeList label="Changes" items={details.changes} />
      <ChangeList label="Catalog changes" items={details.catalogChanges} />
      <ChangeList label="Immediate changes" items={details.immediateChanges} />
      <ChangeList label="Draft changes" items={details.draftChanges} />
      {details.warnings.length > 0 && (
        <div className="mt-3 text-sm text-amber-700">
          <h3 className="font-medium">Warnings</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {details.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      )}
      {details.errors.length > 0 && (
        <div className="mt-3 text-sm text-red-700" role="alert">
          <h3 className="font-medium">Errors</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {details.errors.map((error) => (
              <li key={`${error.path}:${error.code}:${error.message}`}>
                {error.path}: {error.message}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function fieldMessages(value: unknown): ValidationMessages {
  const planErrors = planDetails(value).errors;
  if (planErrors.length)
    return Object.fromEntries(
      planErrors.map((issue) => [issue.path, issue.message]),
    );
  const apiError = normalizeApiError(value);
  return Object.fromEntries(
    (apiError.issues ?? []).map((issue) => [issue.path, issue.message]),
  );
}

export function HighLevelEditor<T, F>({
  title,
  queryKey,
  read,
  plan,
  apply,
  publish,
  toForm,
  fromForm,
  renderForm,
}: {
  title: string;
  queryKey: readonly unknown[];
  read: () => Promise<Snapshot<T>>;
  plan: (value: T) => Promise<unknown>;
  apply: (value: T, snapshot: Snapshot<T>) => Promise<unknown>;
  publish?: (snapshot: Snapshot<T>) => Promise<unknown>;
  toForm: (value: T) => F;
  fromForm: (value: F) => T;
  renderForm: (props: {
    value: F;
    onChange: (value: F) => void;
    errors: ValidationMessages;
    localError?: string;
  }) => ReactNode;
}) {
  const query = useQuery({ queryKey, queryFn: read });
  const [form, setForm] = useState<F>();
  useEffect(() => {
    if (query.data) setForm(toForm(query.data.value));
  }, [query.data, toForm]);

  let desired: T | undefined;
  let localError: string | undefined;
  if (form !== undefined) {
    try {
      desired = fromForm(form);
    } catch (error) {
      localError =
        error instanceof Error ? error.message : "Enter valid values";
    }
  }
  const snapshot = query.data;
  const planMutation = useMutation({
    mutationFn: () => {
      if (desired === undefined)
        throw new Error(localError ?? "Complete the form");
      return plan(desired);
    },
  });
  const applyMutation = useMutation({
    mutationFn: () => {
      if (desired === undefined || !snapshot)
        throw new Error(localError ?? "Complete the form");
      if (snapshot.initialized && !snapshot.etag)
        throw new Error(
          "Configuration ETag is missing; reload before applying",
        );
      return apply(desired, snapshot);
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
  const formRef = useRef<HTMLFormElement>(null);
  const validateForm = () => formRef.current?.reportValidity() ?? true;

  if (query.isPending || form === undefined) return <PageLoading />;
  if (query.isError)
    return (
      <PageError
        error={query.error}
        onRetry={() => void query.refetch().catch(() => undefined)}
        title={`${title} could not be loaded`}
      />
    );
  if (!snapshot) return null;

  const dirty =
    desired !== undefined &&
    semanticSerialize(desired) !== semanticSerialize(snapshot.value);
  const busy =
    query.isFetching ||
    planMutation.isPending ||
    applyMutation.isPending ||
    publishMutation.isPending;
  const canApply =
    desired !== undefined && (!snapshot.initialized || Boolean(snapshot.etag));
  const reload = async () => {
    if (dirty && !window.confirm("Discard unsaved changes?")) return;
    planMutation.reset();
    applyMutation.reset();
    publishMutation.reset();
    await query.refetch();
  };
  const planErrors: ValidationMessages = {};
  for (const error of [
    planMutation.data,
    planMutation.error,
    applyMutation.error,
    publishMutation.error,
  ])
    Object.assign(planErrors, fieldMessages(error));
  const handleFormChange = (next: F) => {
    setForm(next);
    planMutation.reset();
    applyMutation.reset();
    publishMutation.reset();
  };
  return (
    <form ref={formRef} onSubmit={(event) => event.preventDefault()}>
      <div className="sticky top-0 z-10 mb-7 border-b bg-background pb-4 pt-1">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
            <p className="mt-1 text-sm text-muted" role="status">
              {!snapshot.initialized
                ? "Not initialized"
                : snapshot.hasDraft
                  ? "Draft changes pending"
                  : "Initialized"}
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
              disabled={desired === undefined || busy}
              loading={planMutation.isPending}
              loadingLabel="Planning…"
              onClick={() => {
                if (validateForm())
                  void planMutation.mutateAsync().catch(() => undefined);
              }}
              variant="outline"
            >
              Plan
            </Button>
            <Button
              disabled={!canApply || busy}
              loading={applyMutation.isPending}
              loadingLabel="Applying…"
              onClick={() => {
                if (validateForm())
                  void applyMutation.mutateAsync().catch(() => undefined);
              }}
            >
              Apply
            </Button>
            {publish && (
              <Button
                disabled={
                  !snapshot.initialized ||
                  !snapshot.publishable ||
                  dirty ||
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
      {renderForm({
        value: form,
        onChange: handleFormChange,
        errors: planErrors,
        localError,
      })}
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
    </form>
  );
}

export function SystemConfigurationEditor() {
  return (
    <HighLevelEditor<
      SystemConfigurationDesired,
      ReturnType<typeof systemFormState>
    >
      title="System Configuration"
      queryKey={["control-plane", "system-configuration"]}
      toForm={systemFormState}
      fromForm={systemDesiredFromForm}
      renderForm={(props) => <SystemConfigurationForm {...props} />}
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
            hasDraft: false,
          };
        } catch (error) {
          return notInitialized(
            error,
            systemDesiredFromForm(emptySystemFormState()),
          );
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
    <HighLevelEditor<
      PlatformConfigurationDesired,
      ReturnType<typeof platformFormState>
    >
      title="Platform Configuration"
      queryKey={["control-plane", "platform-configuration"]}
      toForm={platformFormState}
      fromForm={platformDesiredFromForm}
      renderForm={(props) => <PlatformConfigurationForm {...props} />}
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
            hasDraft: value.status.has_drafts,
          };
        } catch (error) {
          return notInitialized(
            error,
            platformDesiredFromForm(emptyPlatformFormState()),
          );
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
    <HighLevelEditor<
      TenantConfigurationDesired,
      ReturnType<typeof tenantFormState>
    >
      title="Tenant Configuration"
      queryKey={["control-plane", "tenant-configuration", tenantId]}
      toForm={tenantFormState}
      fromForm={tenantDesiredFromForm}
      renderForm={(props) => <TenantConfigurationForm {...props} />}
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
            hasDraft: value.status.has_drafts,
          };
        } catch (error) {
          return notInitialized(
            error,
            tenantDesiredFromForm(emptyTenantFormState()),
          );
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
