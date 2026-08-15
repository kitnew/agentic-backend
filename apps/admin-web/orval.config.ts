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
});
