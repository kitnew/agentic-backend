import type { AgentForm } from "../schemas/agent-form";

export type EditableAgentComponent = {
  business: { name: string; type: string };
  contact?: {
    address?: string | null;
    website?: string | null;
    emails?: string[];
    phones?: string[];
  };
  localization: { default_locale: string; timezone: string };
  agent: { display_name: string; greeting: string; profile: string };
  conversation: { scope: string };
};

export function editableAgentComponent(
  source: Record<string, unknown> | undefined,
): EditableAgentComponent | undefined {
  const candidate = source as Partial<EditableAgentComponent> | undefined;
  if (
    candidate &&
    typeof candidate.agent?.display_name === "string" &&
    typeof candidate.localization?.default_locale === "string" &&
    typeof candidate.business?.name === "string" &&
    typeof candidate.conversation?.scope === "string"
  )
    return candidate as EditableAgentComponent;
}

export function toAgentForm(config: EditableAgentComponent): AgentForm {
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

export function toAgentPayload(
  config: EditableAgentComponent,
  form: AgentForm,
): Record<string, unknown> {
  return {
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
  };
}
