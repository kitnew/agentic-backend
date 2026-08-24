import type {
  LLMRuntimeSettingsReasoningEffort,
  PlatformRuntimePolicy,
} from "../../core/api/generated/models";

type OptionalMode = "omitted" | "null" | "value";

export type PlatformRuntimeForm = {
  llmModel: string;
  reasoningMode: OptionalMode;
  reasoningEffort: LLMRuntimeSettingsReasoningEffort;
  temperatureMode: OptionalMode;
  temperature: string;
  sttModel: string;
  serverSilenceThreshold: string;
  serverActivityThreshold: string;
  serverMinSpeech: string;
  serverMinSilence: string;
  localMinSpeech: string;
  localMinSilence: string;
  localActivationThreshold: string;
  endpointingMinDelay: string;
  endpointingMaxDelay: string;
  ttsModel: string;
  voiceId: string;
};

const optionalMode = (value: unknown): OptionalMode =>
  value === undefined ? "omitted" : value === null ? "null" : "value";

export function toPlatformRuntimeForm(
  policy: PlatformRuntimePolicy,
): PlatformRuntimeForm {
  return {
    llmModel: policy.llm.model,
    reasoningMode: optionalMode(policy.llm.reasoning_effort),
    reasoningEffort: policy.llm.reasoning_effort ?? "none",
    temperatureMode: optionalMode(policy.llm.temperature),
    temperature: policy.llm.temperature?.toString() ?? "",
    sttModel: policy.stt.model,
    serverSilenceThreshold:
      policy.stt.server_vad.silence_threshold_seconds.toString(),
    serverActivityThreshold:
      policy.stt.server_vad.activity_threshold.toString(),
    serverMinSpeech: policy.stt.server_vad.min_speech_ms.toString(),
    serverMinSilence: policy.stt.server_vad.min_silence_ms.toString(),
    localMinSpeech: policy.local_vad.min_speech_seconds.toString(),
    localMinSilence: policy.local_vad.min_silence_seconds.toString(),
    localActivationThreshold: policy.local_vad.activation_threshold.toString(),
    endpointingMinDelay: policy.turn.min_endpointing_delay_seconds.toString(),
    endpointingMaxDelay: policy.turn.max_endpointing_delay_seconds.toString(),
    ttsModel: policy.tts.model,
    voiceId: policy.tts.voice_id,
  };
}

function number(value: string, label: string) {
  const parsed = Number(value);
  if (!value.trim() || !Number.isFinite(parsed))
    throw new Error(`${label} must be a number.`);
  return parsed;
}

function integer(value: string, label: string) {
  const parsed = number(value, label);
  if (!Number.isInteger(parsed))
    throw new Error(`${label} must be an integer.`);
  return parsed;
}

function required(value: string, label: string) {
  if (!value.trim()) throw new Error(`${label} is required.`);
  return value.trim();
}

export function toPlatformRuntimePolicy(
  form: PlatformRuntimeForm,
): PlatformRuntimePolicy {
  const llm: PlatformRuntimePolicy["llm"] = {
    provider: "azure_openai",
    model: required(form.llmModel, "LLM model"),
  };
  if (form.reasoningMode === "null") llm.reasoning_effort = null;
  if (form.reasoningMode === "value")
    llm.reasoning_effort = form.reasoningEffort;
  if (form.temperatureMode === "null") llm.temperature = null;
  if (form.temperatureMode === "value")
    llm.temperature = number(form.temperature, "Temperature");

  return {
    llm,
    stt: {
      provider: "elevenlabs",
      model: required(form.sttModel, "STT model"),
      server_vad: {
        silence_threshold_seconds: number(
          form.serverSilenceThreshold,
          "Server silence threshold",
        ),
        activity_threshold: number(
          form.serverActivityThreshold,
          "Server activity threshold",
        ),
        min_speech_ms: integer(form.serverMinSpeech, "Server minimum speech"),
        min_silence_ms: integer(
          form.serverMinSilence,
          "Server minimum silence",
        ),
      },
    },
    local_vad: {
      min_speech_seconds: number(form.localMinSpeech, "Minimum speech"),
      min_silence_seconds: number(form.localMinSilence, "Minimum silence"),
      activation_threshold: number(
        form.localActivationThreshold,
        "Activation threshold",
      ),
    },
    turn: {
      detection: "stt",
      min_endpointing_delay_seconds: number(
        form.endpointingMinDelay,
        "Minimum endpointing delay",
      ),
      max_endpointing_delay_seconds: number(
        form.endpointingMaxDelay,
        "Maximum endpointing delay",
      ),
    },
    tts: {
      provider: "elevenlabs",
      model: required(form.ttsModel, "TTS model"),
      voice_id: required(form.voiceId, "Voice ID"),
    },
  };
}
