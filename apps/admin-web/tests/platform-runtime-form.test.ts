import { describe, expect, it } from "vitest";

import {
  toPlatformRuntimeForm,
  toPlatformRuntimePolicy,
} from "../src/features/platform/runtime-form";
import { runtimePolicy } from "./platform-fixtures";

describe("Platform Runtime form mapping", () => {
  it("round-trips the complete policy including enum and nullable fields", () => {
    expect(
      toPlatformRuntimePolicy(toPlatformRuntimeForm(runtimePolicy)),
    ).toEqual(runtimePolicy);
  });

  it("preserves omitted optional fields", () => {
    const policy = structuredClone(runtimePolicy);
    delete policy.llm.temperature;
    delete policy.llm.reasoning_effort;
    expect(toPlatformRuntimePolicy(toPlatformRuntimeForm(policy))).toEqual(
      policy,
    );
  });

  it("serializes the low-latency TTS and STT candidates", () => {
    const form = toPlatformRuntimeForm(runtimePolicy);
    form.ttsMinSentenceChars = "12";
    form.serverSilenceThreshold = "0.25";
    form.serverMinSilence = "250";

    const policy = toPlatformRuntimePolicy(form);
    expect(policy.tts.min_sentence_chars).toBe(12);
    expect(policy.stt.server_vad.silence_threshold_seconds).toBe(0.25);
    expect(policy.stt.server_vad.min_silence_ms).toBe(250);
  });

  it("keeps interim preflight disabled by default and serializes experiments", () => {
    const form = toPlatformRuntimeForm(runtimePolicy);
    expect(form.interimPreflightEnabled).toBe("disabled");
    form.interimPreflightEnabled = "enabled";
    form.interimPreflightMinChars = "24";
    form.interimPreflightMinGrowth = "14";
    form.interimPreflightMaxGenerations = "2";

    expect(toPlatformRuntimePolicy(form).stt.interim_preflight).toEqual({
      enabled: true,
      min_transcript_chars: 24,
      min_growth_chars: 14,
      max_generations_per_turn: 2,
    });
  });
});
