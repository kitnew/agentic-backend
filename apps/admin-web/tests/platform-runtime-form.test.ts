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
});
