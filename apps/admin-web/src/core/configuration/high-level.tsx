import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { PageError, PageLoading } from "../../components/page-states";
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
  type SystemConfigurationDesired,
  type TenantConfiguration,
  type TenantConfigurationDesired,
} from "../api/control-plane";
import { CodeEditor } from "../ui/foundation";
import { EditorActions } from "./editor";

type Snapshot<T> = { value: T; etag: string | null; hasDraft: boolean };

function selected<T>(state: { active?: T | null; draft?: T | null }): T {
  const value = state.draft ?? state.active;
  if (!value) throw new Error("Configuration is incomplete");
  return value;
}

function platformDesired(
  value: PlatformConfiguration,
): PlatformConfigurationDesired {
  return {
    system_prompt: selected(value.system_prompt),
    profiles: value.profiles.map(({ prompt, ...profile }) => ({
      ...profile,
      prompt: selected(prompt),
    })),
    interaction_modes: value.interaction_modes.map(({ prompt, ...mode }) => ({
      ...mode,
      prompt: selected(prompt),
    })),
  };
}

function tenantDesired(value: TenantConfiguration): TenantConfigurationDesired {
  return {
    ...value.live,
    agent_personality: selected(value.versioned.agent_personality),
    business_info: selected(value.versioned.business_info),
    knowledge: selected(value.versioned.knowledge),
    tenant_prompt: selected(value.versioned.tenant_prompt),
    actions_definition: selected(value.versioned.actions_definition),
  };
}

function HighLevelEditor<T>({
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
  plan: (value: T) => Promise<{ valid: boolean }>;
  apply: (value: T, etag: string) => Promise<unknown>;
  publish?: (etag: string) => Promise<unknown>;
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
  const save = useMutation({
    mutationFn: async () => {
      if (!parsed || !query.data?.etag)
        throw new Error("Invalid configuration");
      const result = await plan(parsed);
      if (!result.valid) throw new Error("Configuration validation failed");
      await apply(parsed, query.data.etag);
    },
    onSuccess: () => query.refetch(),
  });
  const publishMutation = useMutation({
    mutationFn: async () => {
      if (!query.data?.etag || !publish) throw new Error("Nothing to publish");
      await publish(query.data.etag);
    },
    onSuccess: () => query.refetch(),
  });
  if (query.isPending) return <PageLoading />;
  if (query.isError)
    return <PageError title={`${title} could not be loaded`} />;
  const original = JSON.stringify(query.data.value, null, 2);
  return (
    <>
      <EditorActions
        dirty={text !== original}
        hasDraft={query.data.hasDraft}
        onSave={() => save.mutateAsync().then(() => undefined)}
        saveDisabled={!parsed}
        saving={save.isPending}
        title={title}
        onPublish={
          publish
            ? () => publishMutation.mutateAsync().then(() => undefined)
            : undefined
        }
        publishing={publishMutation.isPending}
      />
      <CodeEditor
        label={title}
        minHeight={520}
        onChange={setText}
        value={text}
      />
      {(save.isError || publishMutation.isError) && (
        <PageError compact title={`${title} change failed`} />
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
        const response =
          await getSystemConfigurationManagementV1SystemConfigurationGet();
        return {
          value: responseData(response),
          etag: response.headers.get("etag"),
          hasDraft: false,
        };
      }}
      plan={async (value) =>
        responseData(
          await planSystemConfigurationManagementV1SystemConfigurationPlanPost(
            value,
          ),
        )
      }
      apply={(value, etag) =>
        applySystemConfigurationManagementV1SystemConfigurationPut(
          value,
          managementMutationOptions(etag),
        )
      }
    />
  );
}

export function PlatformConfigurationEditor() {
  return (
    <HighLevelEditor
      title="Platform Configuration"
      queryKey={["control-plane", "platform-configuration"]}
      read={async () => {
        const response =
          await getConfigurationManagementV1PlatformConfigurationGet();
        const value = responseData<PlatformConfiguration>(response);
        return {
          value: platformDesired(value),
          etag: response.headers.get("etag"),
          hasDraft: value.status.has_drafts,
        };
      }}
      plan={async (value) =>
        responseData(
          await planConfigurationManagementV1PlatformConfigurationPlanPost(
            value,
          ),
        )
      }
      apply={(value, etag) =>
        applyConfigurationManagementV1PlatformConfigurationPut(
          value,
          managementMutationOptions(etag),
        )
      }
      publish={(etag) =>
        publishConfigurationManagementV1PlatformConfigurationPublishPost(
          managementMutationOptions(etag),
        )
      }
    />
  );
}

export function TenantConfigurationEditor({ tenantId }: { tenantId: string }) {
  return (
    <HighLevelEditor
      title="Tenant Configuration"
      queryKey={["control-plane", "tenant-configuration", tenantId]}
      read={async () => {
        const response =
          await getConfigurationManagementV1TenantsTenantIdConfigurationGet(
            tenantId,
          );
        const value = responseData<TenantConfiguration>(response);
        return {
          value: tenantDesired(value),
          etag: response.headers.get("etag"),
          hasDraft: value.status.has_drafts,
        };
      }}
      plan={async (value) =>
        responseData(
          await planConfigurationManagementV1TenantsTenantIdConfigurationPlanPost(
            tenantId,
            value,
          ),
        )
      }
      apply={(value, etag) =>
        applyConfigurationManagementV1TenantsTenantIdConfigurationPut(
          tenantId,
          value,
          managementMutationOptions(etag),
        )
      }
      publish={(etag) =>
        publishConfigurationManagementV1TenantsTenantIdConfigurationPublishPost(
          tenantId,
          managementMutationOptions(etag),
        )
      }
    />
  );
}
