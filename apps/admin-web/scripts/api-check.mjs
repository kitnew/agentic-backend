import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  cpSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(fileURLToPath(new URL(".", import.meta.url)), "..");
const generatedRoot = resolve(projectRoot, "src/core/api/generated");

function snapshot(root) {
  const hash = createHash("sha256");
  const visit = (directory, prefix = "") => {
    for (const entry of readdirSync(directory, { withFileTypes: true }).sort(
      (left, right) => left.name.localeCompare(right.name),
    )) {
      const relativePath = `${prefix}${entry.name}`;
      if (entry.isDirectory())
        visit(resolve(directory, entry.name), `${relativePath}/`);
      else
        hash
          .update(relativePath)
          .update(readFileSync(resolve(directory, entry.name)));
    }
  };
  visit(root);
  return hash.digest("hex");
}

const tempRoot = mkdtempSync(resolve(tmpdir(), "admin-web-api-check-"));
const beforeRoot = resolve(tempRoot, "before");
cpSync(generatedRoot, beforeRoot, { recursive: true });

try {
  const before = snapshot(beforeRoot);
  execFileSync(
    process.platform === "win32" ? "pnpm.cmd" : "pnpm",
    ["api:generate"],
    {
      cwd: projectRoot,
      stdio: "inherit",
    },
  );
  const after = snapshot(generatedRoot);

  if (before !== after) {
    console.error(
      "Generated Admin API is not deterministic; run pnpm api:generate and inspect the diff.",
    );
    process.exitCode = 1;
  } else console.log("Generated Admin API is deterministic.");
} finally {
  rmSync(tempRoot, { recursive: true, force: true });
}
