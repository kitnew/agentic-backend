import { describe, expect, it } from "vitest";

import { semanticSerialize } from "../src/core/configuration/authoring";

describe("authoring semantic equality", () => {
  it("ignores object insertion order but preserves arrays and null", () => {
    expect(
      semanticSerialize({ b: 2, nested: { z: null, a: 1 }, a: [2, 1] }),
    ).toBe(semanticSerialize({ a: [2, 1], b: 2, nested: { a: 1, z: null } }));
    expect(semanticSerialize({ value: undefined })).not.toBe(
      semanticSerialize({ value: null }),
    );
    expect(semanticSerialize([1, 2])).not.toBe(semanticSerialize([2, 1]));
  });
});
