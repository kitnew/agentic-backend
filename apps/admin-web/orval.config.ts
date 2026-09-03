import { defineConfig } from "orval";

export default defineConfig({
  admin: {
    input: "../../packages/admin-client/openapi/admin.openapi.json",
    output: {
      client: "fetch",
      mode: "tags-split",
      target: "src/core/api/generated/admin.ts",
      schemas: "src/core/api/generated/models",
      clean: true,
    },
  },
  controlPlane: {
    input:
      "../../packages/admin-client/openapi/control-plane-browser.openapi.json",
    output: {
      client: "fetch",
      mode: "tags-split",
      target: "src/core/api/control-plane/generated/control-plane.ts",
      schemas: "src/core/api/control-plane/generated/models",
      clean: true,
    },
  },
});
