import type {
  HandoffDestination,
  TenantConfigAuthoring,
} from "../../../core/api/generated/models";
import type { AgentForm } from "../schemas/agent-form";

export function toAgentForm(config: TenantConfigAuthoring): AgentForm {
  return {
    displayName: config.agent.display_name,
    greeting: config.agent.greeting,
    profile: config.agent.profile,
    defaultLocale: config.localization?.default_locale ?? "",
    timezone: config.localization?.timezone ?? "",
    address: ("contact" in config && config.contact?.address) || "",
    website: ("contact" in config && config.contact?.website) || "",
    emails: ("contact" in config ? (config.contact?.emails ?? []) : []).join(
      "\n",
    ),
    phones: ("contact" in config ? (config.contact?.phones ?? []) : []).join(
      "\n",
    ),
    handoffDestinations: Object.entries(config.handoff?.destinations ?? {}).map(
      ([key, destination]) => {
        const value = destination as HandoffDestination;
        return {
          id: key,
          key,
          description: value.description,
          phoneNumber: value.phone_number,
        };
      },
    ),
  };
}

const lines = (value: string) =>
  value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);

export function toAgentPayload(
  config: TenantConfigAuthoring,
  form: AgentForm,
): TenantConfigAuthoring {
  return {
    ...config,
    agent: {
      ...config.agent,
      display_name: form.displayName.trim(),
      greeting: form.greeting.trim(),
      profile: form.profile,
    },
    localization: {
      ...config.localization,
      default_locale: form.defaultLocale.trim(),
      timezone: form.timezone.trim(),
    },
    contact: {
      address: form.address.trim() || null,
      website: form.website.trim() || null,
      emails: lines(form.emails),
      phones: lines(form.phones),
    },
    handoff: {
      ...config.handoff,
      destinations: Object.fromEntries(
        form.handoffDestinations.map((destination) => [
          destination.key.trim(),
          {
            description: destination.description.trim(),
            phone_number: destination.phoneNumber.trim(),
          },
        ]),
      ),
    },
  };
}
