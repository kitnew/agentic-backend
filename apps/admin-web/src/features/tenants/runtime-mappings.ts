import type {
  TenantLLMRuntimeOverrideReasoningEffort,
  TenantRuntimeAuthoring,
} from "../../core/api/generated/models";

export type RuntimeReasoningEffort = Exclude<
  TenantLLMRuntimeOverrideReasoningEffort,
  null
>;

export type RuntimeKeyterm = { id: string; value: string };

export type RuntimeForm = {
  llmEnabled: boolean;
  llmState: "absent" | "null" | "value";
  llmModel: string;
  llmReasoningEffort: RuntimeReasoningEffort;
  llmReasoningEffortState: "absent" | "null" | "value";
  llmTemperature: string;
  llmTemperaturePresent: boolean;
  sttState: "absent" | "null" | "value";
  sttKeyterms: RuntimeKeyterm[];
  ttsEnabled: boolean;
  ttsState: "absent" | "null" | "value";
  ttsVoiceId: string;
};

export function toRuntimeForm(value: TenantRuntimeAuthoring): RuntimeForm {
  const llmState =
    value.llm === undefined ? "absent" : value.llm === null ? "null" : "value";
  const ttsState =
    value.tts === undefined ? "absent" : value.tts === null ? "null" : "value";
  const sttState =
    value.stt === undefined ? "absent" : value.stt === null ? "null" : "value";
  const llm =
    value.llm && typeof value.llm === "object" ? value.llm : undefined;
  const reasoningPresent = llm && Object.hasOwn(llm, "reasoning_effort");
  const reasoningValue = llm?.reasoning_effort;

  return {
    llmEnabled: llmState === "value",
    llmState,
    llmModel: llm?.model ?? "",
    llmReasoningEffort:
      reasoningValue && reasoningValue !== null ? reasoningValue : "none",
    llmReasoningEffortState: !reasoningPresent
      ? "absent"
      : reasoningValue === null
        ? "null"
        : "value",
    llmTemperature:
      llm?.temperature === undefined || llm?.temperature === null
        ? ""
        : String(llm.temperature),
    llmTemperaturePresent: llm ? Object.hasOwn(llm, "temperature") : false,
    sttState,
    sttKeyterms:
      value.stt && typeof value.stt === "object"
        ? (value.stt.keyterms ?? []).map((term) => ({
            id: crypto.randomUUID(),
            value: term,
          }))
        : [],
    ttsEnabled: ttsState === "value",
    ttsState,
    ttsVoiceId:
      value.tts && typeof value.tts === "object" ? value.tts.voice_id : "",
  };
}

export function toRuntimePayload(form: RuntimeForm): TenantRuntimeAuthoring {
  const payload: TenantRuntimeAuthoring = {};

  if (form.llmEnabled) {
    const llm: NonNullable<TenantRuntimeAuthoring["llm"]> = {
      model: form.llmModel.trim(),
    };
    if (form.llmReasoningEffortState === "value")
      llm.reasoning_effort = form.llmReasoningEffort;
    else if (form.llmReasoningEffortState === "null")
      llm.reasoning_effort = null;
    if (form.llmTemperaturePresent)
      llm.temperature = form.llmTemperature.trim()
        ? Number(form.llmTemperature)
        : null;
    payload.llm = llm;
  } else if (form.llmState === "null") payload.llm = null;

  if (form.sttState === "value")
    payload.stt = {
      keyterms: form.sttKeyterms.map((term) => term.value.trim()),
    };
  else if (form.sttState === "null") payload.stt = null;

  if (form.ttsEnabled) payload.tts = { voice_id: form.ttsVoiceId.trim() };
  else if (form.ttsState === "null") payload.tts = null;

  return payload;
}

export function validateRuntimeForm(form: RuntimeForm): string | null {
  if (form.llmEnabled) {
    const model = form.llmModel.trim();
    if (!model)
      return "LLM model is required when the LLM override is enabled.";
    if (model.length > 255) return "LLM model must be at most 255 characters.";
    if (form.llmTemperature.trim()) {
      const temperature = Number(form.llmTemperature);
      if (!Number.isFinite(temperature) || temperature < 0 || temperature > 2)
        return "Temperature must be a number between 0 and 2.";
    }
  }
  if (form.sttKeyterms.length > 50)
    return "STT keyterms are limited to 50 terms.";
  for (let index = 0; index < form.sttKeyterms.length; index += 1) {
    const error = validateKeyterm(form.sttKeyterms, index);
    if (error) return error;
  }
  if (form.ttsEnabled) {
    const voiceId = form.ttsVoiceId.trim();
    if (!voiceId)
      return "Voice ID is required when the TTS override is enabled.";
    if (voiceId.length > 255) return "Voice ID must be at most 255 characters.";
  }
  return null;
}

export function validateKeyterm(
  keyterms: RuntimeKeyterm[],
  index: number,
): string | null {
  const term = keyterms[index]?.value.trim() ?? "";
  if (!term) return "Keyterms cannot be empty.";
  if (term.length > 20) return "Each keyterm must be at most 20 characters.";
  if (keyterms.findIndex((value) => value.value.trim() === term) !== index)
    return "Keyterms must be unique.";
  return null;
}
