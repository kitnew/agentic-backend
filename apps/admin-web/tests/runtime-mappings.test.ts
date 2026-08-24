import { describe, expect, it } from "vitest";
import type {
  TenantLLMRuntimeOverrideReasoningEffort,
  TenantRuntimeAuthoring,
} from "../src/core/api/generated/models";
import {
  toRuntimeForm,
  toRuntimePayload,
  validateRuntimeForm,
} from "../src/features/tenants/runtime-mappings";

describe("runtime authoring mappings", () => {
  it.each([0, 0.5, 2])("round-trips temperature %s", (temperature) => {
    const value = { llm: { model: "gpt-4o", temperature } };
    expect(toRuntimePayload(toRuntimeForm(value))).toEqual(value);
  });

  it("preserves null and absent optional fields", () => {
    expect(
      toRuntimePayload(
        toRuntimeForm({
          llm: { model: "gpt-4o", temperature: null },
          tts: null,
        }),
      ),
    ).toEqual({
      llm: { model: "gpt-4o", temperature: null },
      tts: null,
    });
    expect(toRuntimePayload(toRuntimeForm({}))).toEqual({});
    expect(
      toRuntimePayload(toRuntimeForm({ llm: { model: "gpt-4o" } })),
    ).toEqual({
      llm: { model: "gpt-4o" },
    });
  });

  it.each(["none", "low", "medium", "high", "xhigh", "max"])(
    "round-trips reasoning effort %s",
    (reasoning_effort) => {
      const value = {
        llm: {
          model: "gpt-4o",
          reasoning_effort:
            reasoning_effort as TenantLLMRuntimeOverrideReasoningEffort,
        },
      };
      expect(toRuntimePayload(toRuntimeForm(value))).toEqual(value);
    },
  );

  it.each([
    { llm: { model: "gpt-4o" } },
    { llm: { model: "gpt-4o", reasoning_effort: null } },
    { llm: { model: "gpt-4o", reasoning_effort: "none" } },
  ] satisfies TenantRuntimeAuthoring[])(
    "preserves reasoning effort state %s",
    (value) => {
      expect(toRuntimePayload(toRuntimeForm(value))).toEqual(value);
    },
  );

  it("keeps local validation structural and leaves model semantics to Backend", () => {
    const form = toRuntimeForm({
      llm: { model: "gpt-5.6-terra" },
      tts: { voice_id: "voice" },
    });
    expect(validateRuntimeForm(form)).toBeNull();
    expect(
      validateRuntimeForm({
        ...form,
        llmTemperature: "2.1",
        llmTemperaturePresent: true,
      }),
    ).toContain("between 0 and 2");
    expect(validateRuntimeForm({ ...form, llmModel: "" })).toContain(
      "model is required",
    );
  });
});
