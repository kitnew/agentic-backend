import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("Admin Web ownership boundary", () => {
  it("has no active legacy Backend authoring imports", () => {
    const sourceRoot = resolve(import.meta.dirname, "../src/features");
    const files = readdirSync(sourceRoot, { recursive: true })
      .map(String)
      .filter((file) => /\.(ts|tsx)$/.test(file))
      .map((file) => resolve(sourceRoot, file));
    const source = files.map((file) => readFileSync(file, "utf8")).join("\n");
    expect(source).not.toMatch(
      /core\/api\/generated\/admin-(authoring|platform-components|tenant-components|integrations)/,
    );
    expect(source).not.toMatch(
      /\/admin\/v1\/.*(authoring|components|integrations)/,
    );
  });
});
