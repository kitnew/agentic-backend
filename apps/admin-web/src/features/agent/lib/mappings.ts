import type {
  ActiveTenantConfig,
  ConfigRevisionResponse,
  TenantConfigV3,
  TenantConfigV4,
  TenantConfigV5,
  UpdateDraftRequest,
} from "../../../core/api/generated/models";
import type { AgentForm } from "../schemas/agent-form";

export type EditableTenantConfig =
  | TenantConfigV3
  | TenantConfigV4
  | TenantConfigV5;

export function editableTenantConfig(
  source: ActiveTenantConfig | ConfigRevisionResponse,
): EditableTenantConfig | undefined {
  const config = source.config;
  const candidate = config as { schema_version?: unknown };
  if (
    typeof config === "object" &&
    config !== null &&
    typeof candidate.schema_version === "number" &&
    candidate.schema_version >= 3 &&
    "agent" in config &&
    "localization" in config
  )
    return config as EditableTenantConfig;
}

export function toAgentForm(config: EditableTenantConfig): AgentForm {
  return {
    displayName: config.agent.display_name,
    greeting: config.agent.greeting,
    profile: config.agent.profile,
    address: ("contact" in config && config.contact?.address) || "",
    website: ("contact" in config && config.contact?.website) || "",
    emails: ("contact" in config ? (config.contact?.emails ?? []) : []).join(
      "\n",
    ),
    phones: ("contact" in config ? (config.contact?.phones ?? []) : []).join(
      "\n",
    ),
  };
}

const lines = (value: string) =>
  value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);

export function toUpdateRequest(
  config: EditableTenantConfig,
  form: AgentForm,
): UpdateDraftRequest {
  return {
    schema_version: config.schema_version,
    config: {
      ...config,
      agent: {
        ...config.agent,
        display_name: form.displayName.trim(),
        greeting: form.greeting.trim(),
        profile: form.profile,
      },
      contact: {
        address: form.address.trim() || null,
        website: form.website.trim() || null,
        emails: lines(form.emails),
        phones: lines(form.phones),
      },
    },
  };
}
