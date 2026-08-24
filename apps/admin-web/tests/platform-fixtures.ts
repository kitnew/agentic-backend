import type { PlatformRuntimePolicy } from "../src/core/api/generated/models";

export const runtimePolicy: PlatformRuntimePolicy = {
  llm: {
    provider: "azure_openai",
    model: "gpt-platform",
    reasoning_effort: null,
    temperature: 0.4,
  },
  stt: {
    provider: "elevenlabs",
    model: "scribe",
    server_vad: {
      silence_threshold_seconds: 0.8,
      activity_threshold: 0.5,
      min_speech_ms: 120,
      min_silence_ms: 300,
    },
  },
  local_vad: {
    min_speech_seconds: 0.1,
    min_silence_seconds: 0.4,
    activation_threshold: 0.6,
  },
  turn: {
    detection: "stt",
    min_endpointing_delay_seconds: 0.4,
    max_endpointing_delay_seconds: 2,
  },
  tts: { provider: "elevenlabs", model: "flash", voice_id: "voice-1" },
};
