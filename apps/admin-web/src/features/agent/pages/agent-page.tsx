import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  EmptyState,
  PageError,
  PageLoading,
} from "../../../components/page-states";
import { responseData } from "../../../core/api/client";
import {
  planConfigAdminV1TenantsTenantIdAuthoringConfigPlanPost,
  saveConfigAdminV1TenantsTenantIdAuthoringConfigPut,
} from "../../../core/api/generated/admin-authoring/admin-authoring";
import { stateAdminV1PlatformComponentsStateGet } from "../../../core/api/generated/admin-platform-components/admin-platform-components";
import type {
  AuthoringPlan,
  PlatformStateResponse,
  TenantConfigAuthoring,
} from "../../../core/api/generated/models";
import {
  AuthoringPlanStatus,
  authoringErrorTitle,
  type TenantAuthoringResource,
  useTenantAuthoringResource,
} from "../../../core/configuration/authoring";
import { EditorActions, Field } from "../../../core/configuration/editor";
import { useTenant } from "../../../core/tenant/use-tenant";
import {
  FormGrid,
  FormSection,
  ProfileSelector,
  RepeatedItem,
  RepeatedList,
} from "../../../core/ui/foundation";
import { toAgentForm, toAgentPayload } from "../lib/mappings";
import { agentQueryKey, getAgentConfiguration } from "../queries/agent-queries";
import type {
  AgentForm,
  AgentHandoffDestinationForm,
} from "../schemas/agent-form";

export function AgentPage() {
  const { tenantId } = useTenant();
  if (!tenantId) return <EmptyState title="Select a tenant" />;
  return <AgentPageContents tenantId={tenantId} />;
}

function AgentPageContents({ tenantId }: { tenantId: string }) {
  const resource = useTenantAuthoringResource<TenantConfigAuthoring>({
    queryKey: agentQueryKey(tenantId),
    read: () => getAgentConfiguration(tenantId),
    plan: async (value) =>
      responseData<AuthoringPlan>(
        await planConfigAdminV1TenantsTenantIdAuthoringConfigPlanPost(
          tenantId,
          value,
        ),
      ),
    save: (value, options) =>
      saveConfigAdminV1TenantsTenantIdAuthoringConfigPut(
        tenantId,
        value,
        options,
      ),
    emptyValue: {
      agent: { display_name: "", greeting: "", profile: "" },
      business: { name: "", type: "" },
      conversation: { scope: "property_only" },
      localization: { default_locale: "en-US", timezone: "UTC" },
    },
  });
  const query = resource.query;
  if (query.isPending) return <PageLoading />;
  if (query.isError)
    return (
      <PageError
        title="Agent configuration could not be loaded"
        onRetry={() => query.refetch()}
      />
    );
  if (!resource.value)
    return <EmptyState title="Agent configuration is not available" />;
  return <AgentEditor resource={resource} />;
}

function AgentEditor({
  resource,
}: {
  resource: TenantAuthoringResource<TenantConfigAuthoring>;
}) {
  const configuration = resource.value as TenantConfigAuthoring;
  const profiles = useQuery({
    queryKey: ["admin", "platform-components", "profiles"],
    queryFn: async () =>
      responseData<PlatformStateResponse>(
        await stateAdminV1PlatformComponentsStateGet(),
      ),
  });
  const profileOptions = useMemo(() => {
    const keys = profiles.data
      ? [
          ...new Set([
            ...Object.keys(profiles.data.active_profile_prompts),
            ...Object.keys(profiles.data.profile_prompt_drafts),
          ]),
        ].sort()
      : [];
    const current = configuration.agent.profile;
    return current && !keys.includes(current)
      ? [
          { value: current, label: `${current} (unavailable)` },
          ...keys.map((value) => ({ value, label: value })),
        ]
      : keys.map((value) => ({ value, label: value }));
  }, [configuration.agent.profile, profiles.data]);
  const initial = toAgentForm(configuration);
  const [form, setForm] = useState(initial);
  const localEdit = useRef(false);
  const wasDirty = useRef(resource.dirty);
  useEffect(() => {
    if (!resource.dirty) {
      if (!localEdit.current || wasDirty.current)
        setForm(toAgentForm(configuration));
      localEdit.current = false;
    }
    wasDirty.current = resource.dirty;
  }, [configuration, resource.dirty]);
  const update = (field: keyof AgentForm, fieldValue: string) => {
    const next = { ...form, [field]: fieldValue };
    localEdit.current = true;
    setForm(next);
    resource.setValue(toAgentPayload(configuration, next));
  };
  const updateDestination = (
    index: number,
    field: keyof AgentHandoffDestinationForm,
    fieldValue: string,
  ) => {
    const next = {
      ...form,
      handoffDestinations: form.handoffDestinations.map(
        (destination, destinationIndex) =>
          destinationIndex === index
            ? { ...destination, [field]: fieldValue }
            : destination,
      ),
    };
    localEdit.current = true;
    setForm(next);
    resource.setValue(toAgentPayload(configuration, next));
  };
  const handoffValidationError = validateHandoffDestinations(
    form.handoffDestinations,
  );
  const saveBlocked =
    Boolean(handoffValidationError) || !resource.validation.canSave;
  return (
    <div className="max-w-3xl">
      <EditorActions
        description="Identity, localization, contact details, and handoff destinations for this tenant agent."
        dirty={resource.dirty}
        hasDraft={resource.hasDraft}
        saving={resource.save.isPending}
        validating={resource.validation.isValidating}
        saveDisabled={saveBlocked}
        remoteChanged={resource.remoteChanged}
        conflict={resource.conflict}
        onReload={resource.reload}
        title="Agent"
        onSave={() => resource.save.mutateAsync().then(() => undefined)}
      />
      <AuthoringPlanStatus validation={resource.validation} />
      <div className="space-y-1">
        <FormSection
          description="How the agent is presented to callers"
          title="Identity"
        >
          <FormGrid>
            <Field label="Display Name">
              <input
                value={form.displayName}
                onChange={(event) => update("displayName", event.target.value)}
              />
            </Field>
            <ProfileSelector
              emptyLabel="No Platform profiles available"
              label="Profile"
              loading={profiles.isPending}
              onChange={(value) => update("profile", value)}
              options={profileOptions}
              value={form.profile}
            />
            <Field fullWidth label="Greeting">
              <textarea
                rows={4}
                value={form.greeting}
                onChange={(event) => update("greeting", event.target.value)}
              />
            </Field>
          </FormGrid>
        </FormSection>
        <FormSection
          defaultExpanded
          description="Locale and time zone used by the tenant"
          title="Localization"
        >
          <FormGrid>
            <Field label="Default locale" detail="Example: en-US">
              <input
                value={form.defaultLocale}
                onChange={(event) =>
                  update("defaultLocale", event.target.value)
                }
              />
            </Field>
            <Field
              label="Timezone"
              detail="IANA timezone, for example Europe/Bratislava"
            >
              <input
                value={form.timezone}
                onChange={(event) => update("timezone", event.target.value)}
              />
            </Field>
          </FormGrid>
        </FormSection>
        <FormSection
          defaultExpanded
          description="Tenant contact details shown to the agent"
          title="Contact"
        >
          <FormGrid>
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
          </FormGrid>
        </FormSection>
        <FormSection
          defaultExpanded
          description="Destinations available for human handoff"
          title="Handoff"
        >
          <RepeatedList
            addLabel="Add destination"
            onAdd={() => {
              const next = {
                ...form,
                handoffDestinations: [
                  ...form.handoffDestinations,
                  {
                    id: crypto.randomUUID(),
                    key: nextHandoffDestinationKey(form.handoffDestinations),
                    description: "",
                    phoneNumber: "",
                  },
                ],
              };
              localEdit.current = true;
              setForm(next);
              resource.setValue(toAgentPayload(configuration, next));
            }}
          >
            {form.handoffDestinations.map((destination, index) => (
              <RepeatedItem
                key={destination.id}
                onRemove={() => {
                  const next = {
                    ...form,
                    handoffDestinations: form.handoffDestinations.filter(
                      (_, destinationIndex) => destinationIndex !== index,
                    ),
                  };
                  localEdit.current = true;
                  setForm(next);
                  resource.setValue(toAgentPayload(configuration, next));
                }}
                title={destination.key || "Destination"}
              >
                <FormGrid>
                  <Field
                    label="Key"
                    detail="Lowercase letters, numbers, and underscores"
                  >
                    <input
                      value={destination.key}
                      onChange={(event) =>
                        updateDestination(index, "key", event.target.value)
                      }
                    />
                  </Field>
                  <Field
                    label="Phone number"
                    detail="E.164 format, for example +421900000001"
                  >
                    <input
                      value={destination.phoneNumber}
                      onChange={(event) =>
                        updateDestination(
                          index,
                          "phoneNumber",
                          event.target.value,
                        )
                      }
                    />
                  </Field>
                  <Field fullWidth label="Description">
                    <textarea
                      rows={3}
                      value={destination.description}
                      onChange={(event) =>
                        updateDestination(
                          index,
                          "description",
                          event.target.value,
                        )
                      }
                    />
                  </Field>
                </FormGrid>
              </RepeatedItem>
            ))}
          </RepeatedList>
        </FormSection>
        <FormSection
          defaultExpanded={false}
          description="Canonical business and conversation fields remain preserved in the payload."
          title="Advanced preserved configuration"
        >
          <p className="text-sm text-muted">
            Business and conversation settings are retained and validated by
            Backend, but are not exposed as ad-hoc fields in this phase.
          </p>
        </FormSection>
        {handoffValidationError && (
          <p className="text-sm text-red-700" role="alert">
            {handoffValidationError}
          </p>
        )}
      </div>
      {resource.save.isError && (
        <PageError
          compact
          title={authoringErrorTitle(
            resource.save.error,
            "Agent change failed",
          )}
        />
      )}
    </div>
  );
}

const handoffKeyPattern = /^[a-z][a-z0-9_]{0,63}$/;

function validateHandoffDestinations(
  destinations: AgentHandoffDestinationForm[],
) {
  if (destinations.length > 20)
    return "Handoff supports at most 20 destinations.";
  const keys = new Set<string>();
  for (const destination of destinations) {
    const key = destination.key.trim();
    if (!handoffKeyPattern.test(key))
      return "Destination keys must start with a lowercase letter and contain only lowercase letters, numbers, or underscores.";
    if (keys.has(key)) return `Destination key ${key} is duplicated.`;
    keys.add(key);
  }
  return null;
}

function nextHandoffDestinationKey(
  destinations: AgentHandoffDestinationForm[],
) {
  const keys = new Set(destinations.map((destination) => destination.key));
  if (!keys.has("destination")) return "destination";
  let suffix = 2;
  while (keys.has(`destination_${suffix}`)) suffix += 1;
  return `destination_${suffix}`;
}
