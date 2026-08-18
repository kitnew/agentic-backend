import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

const composeEnvDir = fileURLToPath(
	new URL("../../infrastructure/compose", import.meta.url),
);

export default defineConfig(({ mode }) => {
	const { ADMIN_API_TOKEN: adminToken } = loadEnv(mode, composeEnvDir, "");
	return {
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
