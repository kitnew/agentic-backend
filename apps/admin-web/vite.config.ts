import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

const composeEnvDir = fileURLToPath(
  new URL("../../infrastructure/compose", import.meta.url),
);

export default defineConfig(({ mode }) => {
  const composeMode = mode === "production" ? "production" : "dev";
  const composeEnv = loadEnv(composeMode, composeEnvDir, "");
  const adminToken = composeEnv.ADMIN_API_TOKEN;
  const controlPlaneToken = composeEnv.CONTROL_PLANE_MANAGEMENT_TOKEN;
  const controlPlanePort = composeEnv.CONTROL_PLANE_PORT || "8001";
  const grafanaUrl =
    composeEnv.ADMIN_WEB_GRAFANA_URL || process.env.VITE_GRAFANA_URL;
  return {
    define: grafanaUrl
      ? { "import.meta.env.VITE_GRAFANA_URL": JSON.stringify(grafanaUrl) }
      : {},
    plugins: [react(), tailwindcss()],
    server: {
      proxy: {
        "/admin": {
          target: "http://localhost:8000",
          configure(proxy) {
            if (!adminToken) return;
            proxy.on("proxyReq", (request) => {
              request.setHeader("Authorization", `Bearer ${adminToken}`);
            });
          },
        },
        "/control-plane": {
          target: `http://localhost:${controlPlanePort}`,
          rewrite: (path) => path.replace(/^\/control-plane/, "/v1"),
          configure(proxy) {
            proxy.on("proxyReq", (request) => {
              request.removeHeader("Authorization");
              if (controlPlaneToken)
                request.setHeader(
                  "Authorization",
                  `Bearer ${controlPlaneToken}`,
                );
            });
          },
        },
      },
    },
    test: {
      include: ["tests/**/*.test.ts?(x)"],
      environment: "jsdom",
      setupFiles: ["./tests/setup.ts"],
      globals: true,
      css: true,
    },
  };
});
