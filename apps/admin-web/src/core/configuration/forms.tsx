import { useQuery } from "@tanstack/react-query";
import { PageError } from "../../components/page-states";
import { Button } from "../../components/ui/button";
import { responseData } from "../api/client";
import {
  architecturesManagementV1RegistriesArchitecturesGet,
  type CatalogStatus,
  getConfigurationManagementV1PlatformConfigurationGet,
  type LLMDefaultsReasoningEffort,
  listDeploymentsManagementV1ProvidersDeploymentsGet,
  type ModelDeploymentResponse,
  type PlatformConfiguration,
  type PlatformConfigurationDesired,
  type RealtimeSemanticVADEagerness,
  type RegistryEntryResponse,
  type SystemConfigurationDesired,
  type TenantConfigurationDesired,
} from "../api/control-plane";
import {
  CodeEditor,
  Field,
  FormGrid,
  FormSection,
  Selector,
} from "../ui/foundation";

export type ValidationMessages = Record<string, string>;

function errorAt(errors: ValidationMessages, path: string) {
  return errors[path];
}

type Deployment = ModelDeploymentResponse;

type SystemFormState = {
  stt_defaults: { deployment_ref: string };
  llm_defaults: {
    deployment_ref: string;
    temperature: string;
    reasoning_effort: "" | Exclude<LLMDefaultsReasoningEffort, null>;
    max_completion_tokens: string;
  };
  tts_defaults: { deployment_ref: string; default_voice_id: string };
  realtime_defaults: {
    deployment_ref: string;
    input_transcription: { deployment_ref: string };
    default_voice: string;
    turn_completion: {
      strategy: "" | "server_vad" | "semantic_vad";
      activation_threshold: string;
      silence_duration_ms: string;
      eagerness: "" | RealtimeSemanticVADEagerness;
    };
    interruption: { enabled: boolean };
  };
  policies: {
    cascade: {
      speech_activity: {
        min_speech_seconds: string;
        min_silence_seconds: string;
        activation_threshold: string;
      };
      stt_commit: {
        strategy: "" | "local_vad" | "provider_vad";
        provider_vad: {
          threshold: string;
          silence_threshold_seconds: string;
          min_speech_ms: string;
          min_silence_ms: string;
        };
      };
      endpointing: { min_delay_seconds: string; max_delay_seconds: string };
      interruption: {
        enabled: boolean;
        min_duration_seconds: string;
        min_words: string;
        false_interruption_timeout_seconds: string;
        resume_after_false_interruption: boolean;
      };
      response_scheduling: {
        preemptive_generation: boolean;
        preemptive_tts: boolean;
      };
      tokenizer: { min_sentence_chars: string };
    };
  };
};

type PlatformEntryForm = {
  id?: string;
  key: string;
  name: string;
  description: string;
  status: CatalogStatus;
  prompt: string;
  existing: boolean;
};

type PlatformFormState = {
  system_prompt: string;
  profiles: PlatformEntryForm[];
  interaction_modes: PlatformEntryForm[];
};

export type TenantFormState = {
  identity: string;
  display_name: string;
  greeting: string;
  conversation_scope: "property_only";
  business_name: string;
  business_type: string;
  address: string;
  website: string;
  phones: string;
  emails: string;
  default_locale: string;
  timezone: string;
  tenant_prompt: string;
  knowledge: string;
  architecture_key: string;
  profile_key: string;
  stt_keyterms_override: boolean;
  stt_keyterms: string;
  tts_voice_override: boolean;
  tts_voice_id: string;
  realtime_voice_override: boolean;
  realtime_voice: string;
  actions_definition: string;
  actions_availability: string;
};

const valueOrEmpty = (value: number | null | undefined) =>
  value === null || value === undefined ? "" : String(value);

const numberValue = (value: string) => (value.trim() ? Number(value) : 0);

const optionalNumberValue = (value: string) =>
  value.trim() ? Number(value) : undefined;

export function parseLines(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

export function emptySystemFormState(): SystemFormState {
  return {
    stt_defaults: { deployment_ref: "" },
    llm_defaults: {
      deployment_ref: "",
      temperature: "",
      reasoning_effort: "",
      max_completion_tokens: "",
    },
    tts_defaults: { deployment_ref: "", default_voice_id: "" },
    realtime_defaults: {
      deployment_ref: "",
      input_transcription: { deployment_ref: "" },
      default_voice: "marin",
      turn_completion: {
        strategy: "",
        activation_threshold: "0.5",
        silence_duration_ms: "200",
        eagerness: "auto",
      },
      interruption: { enabled: true },
    },
    policies: {
      cascade: {
        speech_activity: {
          min_speech_seconds: "",
          min_silence_seconds: "",
          activation_threshold: "",
        },
        stt_commit: {
          strategy: "",
          provider_vad: {
            threshold: "",
            silence_threshold_seconds: "",
            min_speech_ms: "",
            min_silence_ms: "",
          },
        },
        endpointing: { min_delay_seconds: "", max_delay_seconds: "" },
        interruption: {
          enabled: false,
          min_duration_seconds: "",
          min_words: "",
          false_interruption_timeout_seconds: "",
          resume_after_false_interruption: false,
        },
        response_scheduling: {
          preemptive_generation: false,
          preemptive_tts: false,
        },
        tokenizer: { min_sentence_chars: "" },
      },
    },
  };
}

export function systemFormState(
  value: SystemConfigurationDesired,
): SystemFormState {
  const turnCompletion = value.realtime_defaults.turn_completion;
  const sttCommit = value.policies.cascade.stt_commit;
  return {
    stt_defaults: { ...value.stt_defaults },
    llm_defaults: {
      deployment_ref: value.llm_defaults.deployment_ref,
      temperature:
        value.llm_defaults.temperature === null
          ? ""
          : valueOrEmpty(value.llm_defaults.temperature),
      reasoning_effort: value.llm_defaults.reasoning_effort ?? "",
      max_completion_tokens: valueOrEmpty(
        value.llm_defaults.max_completion_tokens,
      ),
    },
    tts_defaults: { ...value.tts_defaults },
    realtime_defaults: {
      deployment_ref: value.realtime_defaults.deployment_ref,
      input_transcription: { ...value.realtime_defaults.input_transcription },
      default_voice: value.realtime_defaults.default_voice,
      turn_completion: {
        strategy: turnCompletion.strategy,
        activation_threshold: valueOrEmpty(
          "activation_threshold" in turnCompletion
            ? turnCompletion.activation_threshold
            : undefined,
        ),
        silence_duration_ms: valueOrEmpty(
          "silence_duration_ms" in turnCompletion
            ? turnCompletion.silence_duration_ms
            : undefined,
        ),
        eagerness:
          "eagerness" in turnCompletion ? (turnCompletion.eagerness ?? "") : "",
      },
      interruption: { ...value.realtime_defaults.interruption },
    },
    policies: {
      cascade: {
        speech_activity: {
          min_speech_seconds: String(
            value.policies.cascade.speech_activity.min_speech_seconds,
          ),
          min_silence_seconds: String(
            value.policies.cascade.speech_activity.min_silence_seconds,
          ),
          activation_threshold: String(
            value.policies.cascade.speech_activity.activation_threshold,
          ),
        },
        stt_commit: {
          strategy: sttCommit.strategy,
          provider_vad:
            sttCommit.strategy === "provider_vad"
              ? {
                  threshold: String(sttCommit.provider_vad.threshold),
                  silence_threshold_seconds: String(
                    sttCommit.provider_vad.silence_threshold_seconds,
                  ),
                  min_speech_ms: String(sttCommit.provider_vad.min_speech_ms),
                  min_silence_ms: String(sttCommit.provider_vad.min_silence_ms),
                }
              : emptySystemFormState().policies.cascade.stt_commit.provider_vad,
        },
        endpointing: {
          min_delay_seconds: String(
            value.policies.cascade.endpointing.min_delay_seconds,
          ),
          max_delay_seconds: String(
            value.policies.cascade.endpointing.max_delay_seconds,
          ),
        },
        interruption: {
          enabled: value.policies.cascade.interruption.enabled,
          min_duration_seconds: String(
            value.policies.cascade.interruption.min_duration_seconds,
          ),
          min_words: String(value.policies.cascade.interruption.min_words),
          false_interruption_timeout_seconds: String(
            value.policies.cascade.interruption
              .false_interruption_timeout_seconds,
          ),
          resume_after_false_interruption:
            value.policies.cascade.interruption.resume_after_false_interruption,
        },
        response_scheduling: { ...value.policies.cascade.response_scheduling },
        tokenizer: {
          min_sentence_chars: String(
            value.policies.cascade.tokenizer.min_sentence_chars,
          ),
        },
      },
    },
  };
}

export function systemDesiredFromForm(
  form: SystemFormState,
): SystemConfigurationDesired {
  const turn = form.realtime_defaults.turn_completion;
  const sttCommit = form.policies.cascade.stt_commit;
  return {
    stt_defaults: { ...form.stt_defaults },
    llm_defaults: {
      deployment_ref: form.llm_defaults.deployment_ref.trim(),
      temperature: optionalNumberValue(form.llm_defaults.temperature) ?? null,
      reasoning_effort: form.llm_defaults.reasoning_effort || null,
      max_completion_tokens: numberValue(
        form.llm_defaults.max_completion_tokens,
      ),
    },
    tts_defaults: {
      deployment_ref: form.tts_defaults.deployment_ref.trim(),
      default_voice_id: form.tts_defaults.default_voice_id.trim(),
    },
    realtime_defaults: {
      deployment_ref: form.realtime_defaults.deployment_ref.trim(),
      input_transcription: {
        deployment_ref:
          form.realtime_defaults.input_transcription.deployment_ref.trim(),
      },
      default_voice: form.realtime_defaults.default_voice.trim(),
      turn_completion:
        turn.strategy === "semantic_vad"
          ? { strategy: "semantic_vad", eagerness: turn.eagerness || undefined }
          : turn.strategy === "server_vad"
            ? {
                strategy: "server_vad",
                activation_threshold: optionalNumberValue(
                  turn.activation_threshold,
                ),
                silence_duration_ms: optionalNumberValue(
                  turn.silence_duration_ms,
                ),
              }
            : { strategy: "" as "server_vad" },
      interruption: { ...form.realtime_defaults.interruption },
    },
    policies: {
      cascade: {
        speech_activity: {
          min_speech_seconds: numberValue(
            form.policies.cascade.speech_activity.min_speech_seconds,
          ),
          min_silence_seconds: numberValue(
            form.policies.cascade.speech_activity.min_silence_seconds,
          ),
          activation_threshold: numberValue(
            form.policies.cascade.speech_activity.activation_threshold,
          ),
        },
        stt_commit:
          sttCommit.strategy === "provider_vad"
            ? {
                strategy: "provider_vad",
                provider_vad: {
                  threshold: numberValue(sttCommit.provider_vad.threshold),
                  silence_threshold_seconds: numberValue(
                    sttCommit.provider_vad.silence_threshold_seconds,
                  ),
                  min_speech_ms: numberValue(
                    sttCommit.provider_vad.min_speech_ms,
                  ),
                  min_silence_ms: numberValue(
                    sttCommit.provider_vad.min_silence_ms,
                  ),
                },
              }
            : { strategy: sttCommit.strategy as "local_vad" },
        endpointing: {
          min_delay_seconds: numberValue(
            form.policies.cascade.endpointing.min_delay_seconds,
          ),
          max_delay_seconds: numberValue(
            form.policies.cascade.endpointing.max_delay_seconds,
          ),
        },
        interruption: {
          enabled: form.policies.cascade.interruption.enabled,
          min_duration_seconds: numberValue(
            form.policies.cascade.interruption.min_duration_seconds,
          ),
          min_words: numberValue(form.policies.cascade.interruption.min_words),
          false_interruption_timeout_seconds: numberValue(
            form.policies.cascade.interruption
              .false_interruption_timeout_seconds,
          ),
          resume_after_false_interruption:
            form.policies.cascade.interruption.resume_after_false_interruption,
        },
        response_scheduling: { ...form.policies.cascade.response_scheduling },
        tokenizer: {
          min_sentence_chars: numberValue(
            form.policies.cascade.tokenizer.min_sentence_chars,
          ),
        },
      },
    },
  };
}

export function emptyPlatformFormState(): PlatformFormState {
  return { system_prompt: "", profiles: [], interaction_modes: [] };
}

export function platformFormState(
  value: PlatformConfigurationDesired,
): PlatformFormState {
  return {
    system_prompt: value.system_prompt.content,
    profiles: value.profiles.map((profile) => ({
      id: profile.key,
      key: profile.key,
      name: profile.name,
      description: profile.description,
      status: profile.status,
      prompt: profile.prompt.content,
      existing: true,
    })),
    interaction_modes: value.interaction_modes.map((mode) => ({
      id: mode.key,
      key: mode.key,
      name: mode.name,
      description: mode.description,
      status: mode.status,
      prompt: mode.prompt.content,
      existing: true,
    })),
  };
}

export function platformDesiredFromForm(form: PlatformFormState) {
  return {
    system_prompt: { content: form.system_prompt.trim() },
    profiles: form.profiles.map(
      ({ existing: _existing, id: _id, ...profile }) => ({
        ...profile,
        key: profile.key.trim(),
        name: profile.name.trim(),
        description: profile.description.trim(),
        prompt: { content: profile.prompt },
      }),
    ),
    interaction_modes: form.interaction_modes.map(
      ({ existing: _existing, id: _id, ...mode }) => ({
        ...mode,
        key: mode.key.trim(),
        name: mode.name.trim(),
        description: mode.description.trim(),
        prompt: { content: mode.prompt },
      }),
    ),
  };
}

export function emptyTenantFormState(): TenantFormState {
  return {
    identity: "",
    display_name: "",
    greeting: "",
    conversation_scope: "property_only",
    business_name: "",
    business_type: "",
    address: "",
    website: "",
    phones: "",
    emails: "",
    default_locale: "",
    timezone: "",
    tenant_prompt: "",
    knowledge: "",
    architecture_key: "",
    profile_key: "",
    stt_keyterms_override: false,
    stt_keyterms: "",
    tts_voice_override: false,
    tts_voice_id: "",
    realtime_voice_override: false,
    realtime_voice: "",
    actions_definition: '{"actions": {}}',
    actions_availability: '{"actions": {}}',
  };
}

export function tenantFormState(
  value: TenantConfigurationDesired,
): TenantFormState {
  const stt = value.runtime_overrides.stt;
  const tts = value.runtime_overrides.tts;
  const realtime = value.runtime_overrides.realtime;
  return {
    identity: value.agent_personality.identity,
    display_name: value.agent_personality.display_name,
    greeting: value.agent_personality.greeting,
    conversation_scope: value.agent_personality.conversation_scope,
    business_name: value.business_info.business.name,
    business_type: value.business_info.business.type,
    address: value.business_info.contact.address ?? "",
    website: value.business_info.contact.website ?? "",
    phones: value.business_info.contact.phones.join("\n"),
    emails: value.business_info.contact.emails.join("\n"),
    default_locale: value.business_info.localization.default_locale,
    timezone: value.business_info.localization.timezone,
    tenant_prompt: value.tenant_prompt.content,
    knowledge: value.knowledge.content,
    architecture_key: value.architecture.architecture_key,
    profile_key: value.profile_reference.profile_key,
    stt_keyterms_override: stt !== undefined,
    stt_keyterms: stt?.keyterms?.join("\n") ?? "",
    tts_voice_override: tts !== undefined,
    tts_voice_id: tts?.voice_id ?? "",
    realtime_voice_override: realtime !== undefined,
    realtime_voice: realtime?.voice ?? "",
    actions_definition: JSON.stringify(value.actions_definition, null, 2),
    actions_availability: JSON.stringify(value.actions_availability, null, 2),
  };
}

export function tenantDesiredFromForm(
  form: TenantFormState,
): TenantConfigurationDesired {
  return {
    tenant_prompt: { content: form.tenant_prompt.trim() },
    knowledge: { content: form.knowledge },
    agent_personality: {
      identity: form.identity.trim(),
      display_name: form.display_name.trim(),
      greeting: form.greeting.trim(),
      conversation_scope: form.conversation_scope,
    },
    business_info: {
      business: {
        name: form.business_name.trim(),
        type: form.business_type.trim(),
      },
      contact: {
        address: form.address.trim() || null,
        phones: parseLines(form.phones),
        emails: parseLines(form.emails),
        website: form.website.trim() || null,
      },
      localization: {
        default_locale: form.default_locale.trim(),
        timezone: form.timezone.trim(),
      },
    },
    actions_definition: JSON.parse(
      form.actions_definition,
    ) as TenantConfigurationDesired["actions_definition"],
    architecture: { architecture_key: form.architecture_key.trim() },
    profile_reference: { profile_key: form.profile_key.trim() },
    runtime_overrides: {
      ...(form.stt_keyterms_override
        ? { stt: { keyterms: parseLines(form.stt_keyterms) } }
        : {}),
      ...(form.tts_voice_override
        ? { tts: { voice_id: form.tts_voice_id.trim() } }
        : {}),
      ...(form.realtime_voice_override
        ? { realtime: { voice: form.realtime_voice.trim() } }
        : {}),
    },
    actions_availability: JSON.parse(
      form.actions_availability,
    ) as TenantConfigurationDesired["actions_availability"],
  };
}

function deploymentsForKind(deployments: Deployment[], kind: string) {
  return deployments
    .filter((deployment) => deployment.deployment_kind === kind)
    .sort((left, right) => Number(right.enabled) - Number(left.enabled));
}

function deploymentOptions(deployments: Deployment[], kind: string) {
  return deploymentsForKind(deployments, kind).map((deployment) => ({
    value: deployment.id,
    label: `${deployment.key} (${deployment.deployment_kind})`,
  }));
}

function useDeployments() {
  return useQuery({
    queryKey: ["control-plane", "model-deployments"],
    queryFn: async () =>
      responseData<Deployment[]>(
        await listDeploymentsManagementV1ProvidersDeploymentsGet(),
      ),
  });
}

function NumericField({
  label,
  value,
  onChange,
  min,
  max,
  step = "any",
  error,
  required = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  min?: number;
  max?: number;
  step?: number | "any";
  error?: string;
  required?: boolean;
}) {
  return (
    <Field error={error} label={label}>
      <input
        max={max}
        min={min}
        required={required}
        step={step}
        type="number"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </Field>
  );
}

function CheckField({
  label,
  checked,
  onChange,
  error,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  error?: string;
}) {
  return (
    <div>
      <label className="flex items-center gap-2 text-sm font-medium">
        <input
          checked={checked}
          className="size-4 w-auto"
          type="checkbox"
          onChange={(event) => onChange(event.target.checked)}
        />
        {label}
      </label>
      {error && (
        <p className="mt-1 text-sm text-red-700" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function DeploymentSelect({
  label,
  value,
  onChange,
  deployments,
  kind,
  helperText,
  error,
  required = true,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  deployments: Deployment[];
  kind: string;
  helperText?: string;
  error?: string;
  required?: boolean;
}) {
  return (
    <Selector
      error={error}
      helperText={helperText}
      label={label}
      options={deploymentOptions(deployments, kind)}
      required={required}
      value={value}
      onChange={onChange}
      emptyLabel="No matching deployments"
    />
  );
}

export function SystemConfigurationForm({
  value,
  onChange,
  errors = {},
  localError,
}: {
  value: SystemFormState;
  onChange: (value: SystemFormState) => void;
  errors?: ValidationMessages;
  localError?: string;
}) {
  const deployments = useDeployments();
  const allDeployments = deployments.data ?? [];
  const updateCascade = (
    next: Partial<SystemFormState["policies"]["cascade"]>,
  ) =>
    onChange({
      ...value,
      policies: { cascade: { ...value.policies.cascade, ...next } },
    });
  const cascade = value.policies.cascade;
  return (
    <div className="space-y-1">
      {localError && (
        <p className="mb-4 text-sm text-red-700" role="alert">
          {localError}
        </p>
      )}
      {deployments.isError && (
        <PageError
          compact
          error={deployments.error}
          title="Deployments could not be loaded"
        />
      )}
      <FormSection
        title="Speech to text"
        description="Select the system STT deployment."
      >
        <DeploymentSelect
          label="Deployment"
          value={value.stt_defaults.deployment_ref}
          error={errorAt(errors, "stt_defaults.deployment_ref")}
          onChange={(deployment_ref) =>
            onChange({ ...value, stt_defaults: { deployment_ref } })
          }
          deployments={allDeployments}
          kind="stt"
          required
        />
      </FormSection>
      <FormSection title="Language model">
        <FormGrid>
          <DeploymentSelect
            label="Deployment"
            value={value.llm_defaults.deployment_ref}
            error={errorAt(errors, "llm_defaults.deployment_ref")}
            onChange={(deployment_ref) =>
              onChange({
                ...value,
                llm_defaults: { ...value.llm_defaults, deployment_ref },
              })
            }
            deployments={allDeployments}
            kind="llm"
          />
          <NumericField
            label="Temperature"
            min={0}
            max={2}
            error={errorAt(errors, "llm_defaults.temperature")}
            value={value.llm_defaults.temperature}
            onChange={(temperature) =>
              onChange({
                ...value,
                llm_defaults: { ...value.llm_defaults, temperature },
              })
            }
          />
          <Field label="Reasoning effort">
            <select
              value={value.llm_defaults.reasoning_effort}
              onChange={(event) =>
                onChange({
                  ...value,
                  llm_defaults: {
                    ...value.llm_defaults,
                    reasoning_effort: event.target
                      .value as SystemFormState["llm_defaults"]["reasoning_effort"],
                  },
                })
              }
            >
              <option value="">Provider default</option>
              {(["none", "low", "medium", "high", "xhigh", "max"] as const).map(
                (effort) => (
                  <option key={effort} value={effort}>
                    {effort}
                  </option>
                ),
              )}
            </select>
          </Field>
          <NumericField
            label="Max completion tokens"
            min={1}
            step={1}
            error={errorAt(errors, "llm_defaults.max_completion_tokens")}
            required
            value={value.llm_defaults.max_completion_tokens}
            onChange={(max_completion_tokens) =>
              onChange({
                ...value,
                llm_defaults: { ...value.llm_defaults, max_completion_tokens },
              })
            }
          />
        </FormGrid>
      </FormSection>
      <FormSection title="Text to speech">
        <FormGrid>
          <DeploymentSelect
            label="Deployment"
            value={value.tts_defaults.deployment_ref}
            error={errorAt(errors, "tts_defaults.deployment_ref")}
            onChange={(deployment_ref) =>
              onChange({
                ...value,
                tts_defaults: { ...value.tts_defaults, deployment_ref },
              })
            }
            deployments={allDeployments}
            kind="tts"
          />
          <Field
            error={errorAt(errors, "tts_defaults.default_voice_id")}
            label="Default voice ID"
          >
            <input
              required
              value={value.tts_defaults.default_voice_id}
              onChange={(event) =>
                onChange({
                  ...value,
                  tts_defaults: {
                    ...value.tts_defaults,
                    default_voice_id: event.target.value,
                  },
                })
              }
            />
          </Field>
        </FormGrid>
      </FormSection>
      <FormSection
        title="Realtime"
        description="Only the selected turn-completion strategy is shown."
      >
        <FormGrid>
          <DeploymentSelect
            label="Deployment"
            value={value.realtime_defaults.deployment_ref}
            error={errorAt(errors, "realtime_defaults.deployment_ref")}
            onChange={(deployment_ref) =>
              onChange({
                ...value,
                realtime_defaults: {
                  ...value.realtime_defaults,
                  deployment_ref,
                },
              })
            }
            deployments={allDeployments}
            kind="realtime"
          />
          <DeploymentSelect
            label="Input transcription"
            helperText="Prefer an STT deployment that supports realtime input transcription."
            value={value.realtime_defaults.input_transcription.deployment_ref}
            error={errorAt(
              errors,
              "realtime_defaults.input_transcription.deployment_ref",
            )}
            onChange={(deployment_ref) =>
              onChange({
                ...value,
                realtime_defaults: {
                  ...value.realtime_defaults,
                  input_transcription: { deployment_ref },
                },
              })
            }
            deployments={allDeployments}
            kind="stt"
          />
          <Field
            error={errorAt(errors, "realtime_defaults.default_voice")}
            label="Default voice"
          >
            <input
              required
              value={value.realtime_defaults.default_voice}
              onChange={(event) =>
                onChange({
                  ...value,
                  realtime_defaults: {
                    ...value.realtime_defaults,
                    default_voice: event.target.value,
                  },
                })
              }
            />
          </Field>
          <Field
            error={errorAt(errors, "realtime_defaults.turn_completion")}
            label="Turn completion strategy"
          >
            <select
              required
              value={value.realtime_defaults.turn_completion.strategy}
              onChange={(event) =>
                onChange({
                  ...value,
                  realtime_defaults: {
                    ...value.realtime_defaults,
                    turn_completion: {
                      ...value.realtime_defaults.turn_completion,
                      strategy: event.target
                        .value as SystemFormState["realtime_defaults"]["turn_completion"]["strategy"],
                    },
                  },
                })
              }
            >
              <option value="">Select a strategy</option>
              <option value="server_vad">server_vad</option>
              <option value="semantic_vad">semantic_vad</option>
            </select>
          </Field>
          {value.realtime_defaults.turn_completion.strategy ===
            "server_vad" && (
            <>
              <NumericField
                label="Activation threshold"
                min={0}
                max={1}
                error={errorAt(
                  errors,
                  "realtime_defaults.turn_completion.activation_threshold",
                )}
                value={
                  value.realtime_defaults.turn_completion.activation_threshold
                }
                onChange={(activation_threshold) =>
                  onChange({
                    ...value,
                    realtime_defaults: {
                      ...value.realtime_defaults,
                      turn_completion: {
                        ...value.realtime_defaults.turn_completion,
                        activation_threshold,
                      },
                    },
                  })
                }
              />
              <NumericField
                label="Silence duration (ms)"
                min={1}
                step={1}
                error={errorAt(
                  errors,
                  "realtime_defaults.turn_completion.silence_duration_ms",
                )}
                value={
                  value.realtime_defaults.turn_completion.silence_duration_ms
                }
                onChange={(silence_duration_ms) =>
                  onChange({
                    ...value,
                    realtime_defaults: {
                      ...value.realtime_defaults,
                      turn_completion: {
                        ...value.realtime_defaults.turn_completion,
                        silence_duration_ms,
                      },
                    },
                  })
                }
              />
            </>
          )}
          {value.realtime_defaults.turn_completion.strategy ===
            "semantic_vad" && (
            <Field
              error={errorAt(
                errors,
                "realtime_defaults.turn_completion.eagerness",
              )}
              label="Eagerness"
            >
              <select
                value={value.realtime_defaults.turn_completion.eagerness}
                onChange={(event) =>
                  onChange({
                    ...value,
                    realtime_defaults: {
                      ...value.realtime_defaults,
                      turn_completion: {
                        ...value.realtime_defaults.turn_completion,
                        eagerness: event.target
                          .value as SystemFormState["realtime_defaults"]["turn_completion"]["eagerness"],
                      },
                    },
                  })
                }
              >
                {(["auto", "low", "medium", "high"] as const).map(
                  (eagerness) => (
                    <option key={eagerness} value={eagerness}>
                      {eagerness}
                    </option>
                  ),
                )}
              </select>
            </Field>
          )}
          <div className="sm:col-span-2">
            <CheckField
              label="Interruption enabled"
              error={errorAt(errors, "realtime_defaults.interruption.enabled")}
              checked={value.realtime_defaults.interruption.enabled}
              onChange={(enabled) =>
                onChange({
                  ...value,
                  realtime_defaults: {
                    ...value.realtime_defaults,
                    interruption: { enabled },
                  },
                })
              }
            />
          </div>
        </FormGrid>
      </FormSection>
      <FormSection title="Cascade policies">
        <div className="space-y-6">
          <FormSection title="Speech activity" collapsible={false}>
            <FormGrid>
              <NumericField
                label="Min speech (seconds)"
                min={0.000001}
                max={60}
                required
                error={errorAt(
                  errors,
                  "policies.cascade.speech_activity.min_speech_seconds",
                )}
                value={cascade.speech_activity.min_speech_seconds}
                onChange={(min_speech_seconds) =>
                  updateCascade({
                    speech_activity: {
                      ...cascade.speech_activity,
                      min_speech_seconds,
                    },
                  })
                }
              />
              <NumericField
                label="Min silence (seconds)"
                min={0.000001}
                max={60}
                required
                error={errorAt(
                  errors,
                  "policies.cascade.speech_activity.min_silence_seconds",
                )}
                value={cascade.speech_activity.min_silence_seconds}
                onChange={(min_silence_seconds) =>
                  updateCascade({
                    speech_activity: {
                      ...cascade.speech_activity,
                      min_silence_seconds,
                    },
                  })
                }
              />
              <NumericField
                label="Activation threshold"
                min={0}
                max={1}
                required
                error={errorAt(
                  errors,
                  "policies.cascade.speech_activity.activation_threshold",
                )}
                value={cascade.speech_activity.activation_threshold}
                onChange={(activation_threshold) =>
                  updateCascade({
                    speech_activity: {
                      ...cascade.speech_activity,
                      activation_threshold,
                    },
                  })
                }
              />
            </FormGrid>
          </FormSection>
          <FormSection title="STT commit" collapsible={false}>
            <Field
              error={errorAt(errors, "policies.cascade.stt_commit.strategy")}
              label="Strategy"
            >
              <select
                required
                value={cascade.stt_commit.strategy}
                onChange={(event) =>
                  updateCascade({
                    stt_commit: {
                      ...cascade.stt_commit,
                      strategy: event.target
                        .value as typeof cascade.stt_commit.strategy,
                    },
                  })
                }
              >
                <option value="">Select a strategy</option>
                <option value="local_vad">local_vad</option>
                <option value="provider_vad">provider_vad</option>
              </select>
            </Field>
            {cascade.stt_commit.strategy === "provider_vad" && (
              <FormGrid className="mt-4">
                <NumericField
                  label="Threshold"
                  min={0}
                  max={1}
                  required
                  error={errorAt(
                    errors,
                    "policies.cascade.stt_commit.provider_vad.threshold",
                  )}
                  value={cascade.stt_commit.provider_vad.threshold}
                  onChange={(threshold) =>
                    updateCascade({
                      stt_commit: {
                        ...cascade.stt_commit,
                        provider_vad: {
                          ...cascade.stt_commit.provider_vad,
                          threshold,
                        },
                      },
                    })
                  }
                />
                <NumericField
                  label="Silence threshold (seconds)"
                  min={0.000001}
                  max={60}
                  required
                  error={errorAt(
                    errors,
                    "policies.cascade.stt_commit.provider_vad.silence_threshold_seconds",
                  )}
                  value={
                    cascade.stt_commit.provider_vad.silence_threshold_seconds
                  }
                  onChange={(silence_threshold_seconds) =>
                    updateCascade({
                      stt_commit: {
                        ...cascade.stt_commit,
                        provider_vad: {
                          ...cascade.stt_commit.provider_vad,
                          silence_threshold_seconds,
                        },
                      },
                    })
                  }
                />
                <NumericField
                  label="Min speech (ms)"
                  min={1}
                  max={60000}
                  step={1}
                  required
                  error={errorAt(
                    errors,
                    "policies.cascade.stt_commit.provider_vad.min_speech_ms",
                  )}
                  value={cascade.stt_commit.provider_vad.min_speech_ms}
                  onChange={(min_speech_ms) =>
                    updateCascade({
                      stt_commit: {
                        ...cascade.stt_commit,
                        provider_vad: {
                          ...cascade.stt_commit.provider_vad,
                          min_speech_ms,
                        },
                      },
                    })
                  }
                />
                <NumericField
                  label="Min silence (ms)"
                  min={1}
                  max={60000}
                  step={1}
                  required
                  error={errorAt(
                    errors,
                    "policies.cascade.stt_commit.provider_vad.min_silence_ms",
                  )}
                  value={cascade.stt_commit.provider_vad.min_silence_ms}
                  onChange={(min_silence_ms) =>
                    updateCascade({
                      stt_commit: {
                        ...cascade.stt_commit,
                        provider_vad: {
                          ...cascade.stt_commit.provider_vad,
                          min_silence_ms,
                        },
                      },
                    })
                  }
                />
              </FormGrid>
            )}
          </FormSection>
          <FormSection title="Endpointing" collapsible={false}>
            <FormGrid>
              <NumericField
                label="Min delay (seconds)"
                min={0.000001}
                max={60}
                required
                error={errorAt(
                  errors,
                  "policies.cascade.endpointing.min_delay_seconds",
                )}
                value={cascade.endpointing.min_delay_seconds}
                onChange={(min_delay_seconds) =>
                  updateCascade({
                    endpointing: { ...cascade.endpointing, min_delay_seconds },
                  })
                }
              />
              <NumericField
                label="Max delay (seconds)"
                min={0.000001}
                max={60}
                required
                error={errorAt(
                  errors,
                  "policies.cascade.endpointing.max_delay_seconds",
                )}
                value={cascade.endpointing.max_delay_seconds}
                onChange={(max_delay_seconds) =>
                  updateCascade({
                    endpointing: { ...cascade.endpointing, max_delay_seconds },
                  })
                }
              />
            </FormGrid>
          </FormSection>
          <FormSection title="Interruption" collapsible={false}>
            <FormGrid>
              <div>
                <CheckField
                  label="Enabled"
                  error={errorAt(
                    errors,
                    "policies.cascade.interruption.enabled",
                  )}
                  checked={cascade.interruption.enabled}
                  onChange={(enabled) =>
                    updateCascade({
                      interruption: { ...cascade.interruption, enabled },
                    })
                  }
                />
              </div>
              <NumericField
                label="Min duration (seconds)"
                min={0}
                max={60}
                required
                error={errorAt(
                  errors,
                  "policies.cascade.interruption.min_duration_seconds",
                )}
                value={cascade.interruption.min_duration_seconds}
                onChange={(min_duration_seconds) =>
                  updateCascade({
                    interruption: {
                      ...cascade.interruption,
                      min_duration_seconds,
                    },
                  })
                }
              />
              <NumericField
                label="Min words"
                min={0}
                step={1}
                required
                error={errorAt(
                  errors,
                  "policies.cascade.interruption.min_words",
                )}
                value={cascade.interruption.min_words}
                onChange={(min_words) =>
                  updateCascade({
                    interruption: { ...cascade.interruption, min_words },
                  })
                }
              />
              <NumericField
                label="False interruption timeout (seconds)"
                min={0}
                max={60}
                required
                error={errorAt(
                  errors,
                  "policies.cascade.interruption.false_interruption_timeout_seconds",
                )}
                value={cascade.interruption.false_interruption_timeout_seconds}
                onChange={(false_interruption_timeout_seconds) =>
                  updateCascade({
                    interruption: {
                      ...cascade.interruption,
                      false_interruption_timeout_seconds,
                    },
                  })
                }
              />
              <div>
                <CheckField
                  label="Resume after false interruption"
                  error={errorAt(
                    errors,
                    "policies.cascade.interruption.resume_after_false_interruption",
                  )}
                  checked={cascade.interruption.resume_after_false_interruption}
                  onChange={(resume_after_false_interruption) =>
                    updateCascade({
                      interruption: {
                        ...cascade.interruption,
                        resume_after_false_interruption,
                      },
                    })
                  }
                />
              </div>
            </FormGrid>
          </FormSection>
          <FormSection title="Response scheduling" collapsible={false}>
            <FormGrid>
              <CheckField
                label="Preemptive generation"
                error={errorAt(
                  errors,
                  "policies.cascade.response_scheduling.preemptive_generation",
                )}
                checked={cascade.response_scheduling.preemptive_generation}
                onChange={(preemptive_generation) =>
                  updateCascade({
                    response_scheduling: {
                      ...cascade.response_scheduling,
                      preemptive_generation,
                    },
                  })
                }
              />
              <CheckField
                label="Preemptive TTS"
                error={errorAt(
                  errors,
                  "policies.cascade.response_scheduling.preemptive_tts",
                )}
                checked={cascade.response_scheduling.preemptive_tts}
                onChange={(preemptive_tts) =>
                  updateCascade({
                    response_scheduling: {
                      ...cascade.response_scheduling,
                      preemptive_tts,
                    },
                  })
                }
              />
            </FormGrid>
          </FormSection>
          <FormSection title="Tokenizer" collapsible={false}>
            <NumericField
              label="Min sentence characters"
              min={3}
              max={200}
              step={1}
              required
              error={errorAt(
                errors,
                "policies.cascade.tokenizer.min_sentence_chars",
              )}
              value={cascade.tokenizer.min_sentence_chars}
              onChange={(min_sentence_chars) =>
                updateCascade({ tokenizer: { min_sentence_chars } })
              }
            />
          </FormSection>
        </div>
      </FormSection>
    </div>
  );
}

function PlatformEntry({
  value,
  onChange,
  onRemove,
  title,
  errors,
  path,
}: {
  value: PlatformEntryForm;
  onChange: (value: PlatformEntryForm) => void;
  onRemove?: () => void;
  title: string;
  errors: ValidationMessages;
  path: string;
}) {
  return (
    <section className="space-y-4 rounded-md border p-4">
      <div className="flex items-center justify-between gap-4">
        <h3 className="font-medium">{title}</h3>
        {onRemove && (
          <Button onClick={onRemove} variant="ghost">
            Remove
          </Button>
        )}
      </div>
      <FormGrid>
        <Field error={errorAt(errors, `${path}.key`)} label="Key">
          <input
            readOnly={value.existing}
            required
            value={value.key}
            onChange={(event) =>
              onChange({ ...value, key: event.target.value })
            }
          />
        </Field>
        <Field error={errorAt(errors, `${path}.name`)} label="Name">
          <input
            required
            value={value.name}
            onChange={(event) =>
              onChange({ ...value, name: event.target.value })
            }
          />
        </Field>
        <Field label="Status">
          <select
            value={value.status}
            onChange={(event) =>
              onChange({
                ...value,
                status: event.target.value as CatalogStatus,
              })
            }
          >
            <option value="enabled">enabled</option>
            <option value="disabled">disabled</option>
          </select>
        </Field>
        <Field label="Description" fullWidth>
          <textarea
            value={value.description}
            onChange={(event) =>
              onChange({ ...value, description: event.target.value })
            }
          />
        </Field>
        <Field
          error={errorAt(errors, `${path}.prompt`)}
          label="Prompt"
          fullWidth
        >
          <textarea
            required
            value={value.prompt}
            onChange={(event) =>
              onChange({ ...value, prompt: event.target.value })
            }
          />
        </Field>
      </FormGrid>
    </section>
  );
}

export function PlatformConfigurationForm({
  value,
  onChange,
  errors = {},
  localError,
}: {
  value: PlatformFormState;
  onChange: (value: PlatformFormState) => void;
  errors?: ValidationMessages;
  localError?: string;
}) {
  return (
    <div className="space-y-1">
      {localError && (
        <p className="mb-4 text-sm text-red-700" role="alert">
          {localError}
        </p>
      )}
      <FormSection title="System prompt">
        <Field
          error={errorAt(errors, "system_prompt.content")}
          label="Content"
          fullWidth
        >
          <textarea
            required
            value={value.system_prompt}
            onChange={(event) =>
              onChange({ ...value, system_prompt: event.target.value })
            }
          />
        </Field>
      </FormSection>
      <FormSection
        title="Profiles"
        description="Existing keys stay fixed; new local profiles can be removed before Apply."
      >
        <div className="space-y-4">
          {value.profiles.map((profile, index) => (
            <PlatformEntry
              key={profile.id ?? profile.key}
              title={`Profile ${index + 1}`}
              value={profile}
              errors={errors}
              onChange={(next) =>
                onChange({
                  ...value,
                  profiles: value.profiles.map((item, itemIndex) =>
                    itemIndex === index ? next : item,
                  ),
                })
              }
              onRemove={
                !profile.existing
                  ? () =>
                      onChange({
                        ...value,
                        profiles: value.profiles.filter(
                          (_, itemIndex) => itemIndex !== index,
                        ),
                      })
                  : undefined
              }
              path={`profiles.${index}`}
            />
          ))}
          <Button
            onClick={() =>
              onChange({
                ...value,
                profiles: [
                  ...value.profiles,
                  {
                    id: crypto.randomUUID(),
                    key: "",
                    name: "",
                    description: "",
                    status: "enabled",
                    prompt: "",
                    existing: false,
                  },
                ],
              })
            }
            variant="outline"
          >
            Add profile
          </Button>
        </div>
      </FormSection>
      <FormSection title="Interaction modes">
        <div className="space-y-4">
          {value.interaction_modes.map((mode, index) => (
            <PlatformEntry
              key={mode.id ?? mode.key}
              title={`Interaction mode ${index + 1}`}
              value={mode}
              errors={errors}
              onChange={(next) =>
                onChange({
                  ...value,
                  interaction_modes: value.interaction_modes.map(
                    (item, itemIndex) => (itemIndex === index ? next : item),
                  ),
                })
              }
              onRemove={
                !mode.existing
                  ? () =>
                      onChange({
                        ...value,
                        interaction_modes: value.interaction_modes.filter(
                          (_, itemIndex) => itemIndex !== index,
                        ),
                      })
                  : undefined
              }
              path={`interaction_modes.${index}`}
            />
          ))}
          <Button
            onClick={() =>
              onChange({
                ...value,
                interaction_modes: [
                  ...value.interaction_modes,
                  {
                    id: crypto.randomUUID(),
                    key: "",
                    name: "",
                    description: "",
                    status: "enabled",
                    prompt: "",
                    existing: false,
                  },
                ],
              })
            }
            variant="outline"
          >
            Add interaction mode
          </Button>
        </div>
      </FormSection>
    </div>
  );
}

function registryOptions(
  entries: RegistryEntryResponse[],
  selectedValue: string,
) {
  const options = entries.map((entry) => ({
    value: entry.key,
    label: `${entry.name} (${entry.key})`,
  }));
  if (
    selectedValue &&
    !options.some((option) => option.value === selectedValue)
  )
    options.push({ value: selectedValue, label: `${selectedValue} (current)` });
  return options;
}

function profileOptions(
  value: PlatformConfiguration | undefined,
  selectedValue: string,
) {
  const profiles = value?.profiles ?? [];
  const options = [...profiles]
    .sort(
      (left, right) =>
        Number(right.status === "enabled") - Number(left.status === "enabled"),
    )
    .map((profile) => ({
      value: profile.key,
      label: `${profile.name} (${profile.key})${profile.status === "disabled" ? " — disabled" : ""}`,
    }));
  if (
    selectedValue &&
    !options.some((option) => option.value === selectedValue)
  )
    options.push({ value: selectedValue, label: `${selectedValue} (current)` });
  return options;
}

export function TenantConfigurationForm({
  value,
  onChange,
  errors = {},
  localError,
}: {
  value: TenantFormState;
  onChange: (value: TenantFormState) => void;
  errors?: ValidationMessages;
  localError?: string;
}) {
  const architectures = useQuery({
    queryKey: ["control-plane", "architectures"],
    queryFn: async () =>
      responseData<RegistryEntryResponse[]>(
        await architecturesManagementV1RegistriesArchitecturesGet(),
      ),
  });
  const platform = useQuery({
    queryKey: ["control-plane", "platform-configuration"],
    queryFn: async () =>
      responseData<PlatformConfiguration>(
        await getConfigurationManagementV1PlatformConfigurationGet(),
      ),
  });
  const timezones =
    typeof Intl.supportedValuesOf === "function"
      ? Intl.supportedValuesOf("timeZone")
      : [];
  return (
    <div className="space-y-1">
      {localError && (
        <p className="mb-4 text-sm text-red-700" role="alert">
          {localError}
        </p>
      )}
      {architectures.isError && (
        <PageError
          compact
          error={architectures.error}
          title="Architecture registry could not be loaded"
        />
      )}
      {platform.isError && (
        <PageError
          compact
          error={platform.error}
          title="Platform profiles could not be loaded"
        />
      )}
      <FormSection title="Agent">
        <FormGrid>
          <Field
            error={errorAt(errors, "agent_personality.identity")}
            label="Identity"
          >
            <input
              required
              value={value.identity}
              onChange={(event) =>
                onChange({ ...value, identity: event.target.value })
              }
            />
          </Field>
          <Field
            error={errorAt(errors, "agent_personality.display_name")}
            label="Display name"
          >
            <input
              required
              value={value.display_name}
              onChange={(event) =>
                onChange({ ...value, display_name: event.target.value })
              }
            />
          </Field>
          <Field label="Conversation scope">
            <select
              value={value.conversation_scope}
              onChange={(event) =>
                onChange({
                  ...value,
                  conversation_scope: event.target.value as "property_only",
                })
              }
            >
              <option value="property_only">property_only</option>
            </select>
          </Field>
          <Field
            error={errorAt(errors, "agent_personality.greeting")}
            label="Greeting"
            fullWidth
          >
            <textarea
              required
              value={value.greeting}
              onChange={(event) =>
                onChange({ ...value, greeting: event.target.value })
              }
            />
          </Field>
        </FormGrid>
      </FormSection>
      <FormSection title="Business">
        <FormGrid>
          <Field
            error={errorAt(errors, "business_info.business.name")}
            label="Business name"
          >
            <input
              required
              value={value.business_name}
              onChange={(event) =>
                onChange({ ...value, business_name: event.target.value })
              }
            />
          </Field>
          <Field
            error={errorAt(errors, "business_info.business.type")}
            label="Business type"
          >
            <input
              required
              value={value.business_type}
              onChange={(event) =>
                onChange({ ...value, business_type: event.target.value })
              }
            />
          </Field>
          <Field
            error={errorAt(errors, "business_info.contact.address")}
            label="Address"
          >
            <input
              value={value.address}
              onChange={(event) =>
                onChange({ ...value, address: event.target.value })
              }
            />
          </Field>
          <Field
            error={errorAt(errors, "business_info.contact.website")}
            label="Website"
          >
            <input
              value={value.website}
              onChange={(event) =>
                onChange({ ...value, website: event.target.value })
              }
            />
          </Field>
          <Field
            error={errorAt(errors, "business_info.contact.phones")}
            label="Phone numbers"
            helperText="One value per line."
            fullWidth
          >
            <textarea
              value={value.phones}
              onChange={(event) =>
                onChange({ ...value, phones: event.target.value })
              }
            />
          </Field>
          <Field
            error={errorAt(errors, "business_info.contact.emails")}
            label="Emails"
            helperText="One value per line."
            fullWidth
          >
            <textarea
              value={value.emails}
              onChange={(event) =>
                onChange({ ...value, emails: event.target.value })
              }
            />
          </Field>
          <Field
            error={errorAt(errors, "business_info.localization.default_locale")}
            label="Default locale"
          >
            <input
              required
              placeholder="sk-SK"
              value={value.default_locale}
              onChange={(event) =>
                onChange({ ...value, default_locale: event.target.value })
              }
            />
          </Field>
          <Field
            error={errorAt(errors, "business_info.localization.timezone")}
            label="Timezone"
          >
            <input
              list="time-zone-options"
              required
              value={value.timezone}
              onChange={(event) =>
                onChange({ ...value, timezone: event.target.value })
              }
            />
          </Field>
          <datalist id="time-zone-options">
            {timezones.map((timezone) => (
              <option key={timezone} value={timezone} />
            ))}
          </datalist>
        </FormGrid>
      </FormSection>
      <FormSection title="Prompts and knowledge">
        <FormGrid columns={1}>
          <Field
            error={errorAt(errors, "tenant_prompt.content")}
            label="Tenant prompt"
            fullWidth
          >
            <textarea
              required
              value={value.tenant_prompt}
              onChange={(event) =>
                onChange({ ...value, tenant_prompt: event.target.value })
              }
            />
          </Field>
          <Field
            error={errorAt(errors, "knowledge.content")}
            label="Knowledge"
            fullWidth
          >
            <textarea
              value={value.knowledge}
              onChange={(event) =>
                onChange({ ...value, knowledge: event.target.value })
              }
            />
          </Field>
        </FormGrid>
      </FormSection>
      <FormSection title="Runtime">
        <FormGrid>
          <Selector
            required
            label="Architecture"
            loading={architectures.isPending}
            options={registryOptions(
              architectures.data ?? [],
              value.architecture_key,
            )}
            error={errorAt(errors, "architecture.architecture_key")}
            value={value.architecture_key}
            onChange={(architecture_key) =>
              onChange({ ...value, architecture_key })
            }
            emptyLabel="No architectures available"
          />
          <Selector
            required
            label="Profile"
            helperText="Enabled profiles appear first; a disabled current profile is preserved."
            loading={platform.isPending}
            options={profileOptions(platform.data, value.profile_key)}
            error={errorAt(errors, "profile_reference.profile_key")}
            value={value.profile_key}
            onChange={(profile_key) => onChange({ ...value, profile_key })}
            emptyLabel="No profiles available"
          />
        </FormGrid>
      </FormSection>
      <FormSection
        title="Runtime overrides"
        description="Unchecked controls inherit the corresponding system value."
      >
        <div className="space-y-5">
          <div>
            <CheckField
              label="Override system keyterms"
              checked={value.stt_keyterms_override}
              onChange={(stt_keyterms_override) =>
                onChange({ ...value, stt_keyterms_override })
              }
            />
            {value.stt_keyterms_override && (
              <Field
                error={errorAt(errors, "runtime_overrides.stt.keyterms")}
                label="STT keyterms"
                helperText="One value per line; an empty value means an explicit empty set."
                fullWidth
              >
                <textarea
                  value={value.stt_keyterms}
                  onChange={(event) =>
                    onChange({ ...value, stt_keyterms: event.target.value })
                  }
                />
              </Field>
            )}
          </div>
          <div>
            <CheckField
              label="Override system TTS voice"
              checked={value.tts_voice_override}
              onChange={(tts_voice_override) =>
                onChange({ ...value, tts_voice_override })
              }
            />
            {value.tts_voice_override && (
              <Field
                error={errorAt(errors, "runtime_overrides.tts.voice_id")}
                label="TTS voice ID"
              >
                <input
                  required
                  value={value.tts_voice_id}
                  onChange={(event) =>
                    onChange({ ...value, tts_voice_id: event.target.value })
                  }
                />
              </Field>
            )}
          </div>
          <div>
            <CheckField
              label="Override system realtime voice"
              checked={value.realtime_voice_override}
              onChange={(realtime_voice_override) =>
                onChange({ ...value, realtime_voice_override })
              }
            />
            {value.realtime_voice_override && (
              <Field
                error={errorAt(errors, "runtime_overrides.realtime.voice")}
                label="Realtime voice"
              >
                <input
                  required
                  value={value.realtime_voice}
                  onChange={(event) =>
                    onChange({ ...value, realtime_voice: event.target.value })
                  }
                />
              </Field>
            )}
          </div>
        </div>
      </FormSection>
      <FormSection
        title="Actions"
        description="Leave the default empty maps when the tenant has no actions."
      >
        <FormGrid columns={1}>
          <CodeEditor
            error={errorAt(errors, "actions_definition")}
            label="Actions Definition JSON"
            minHeight={220}
            value={value.actions_definition}
            onChange={(actions_definition) =>
              onChange({ ...value, actions_definition })
            }
          />
          <CodeEditor
            error={errorAt(errors, "actions_availability")}
            label="Actions Availability JSON"
            minHeight={160}
            value={value.actions_availability}
            onChange={(actions_availability) =>
              onChange({ ...value, actions_availability })
            }
          />
        </FormGrid>
      </FormSection>
    </div>
  );
}
