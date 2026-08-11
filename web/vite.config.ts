import { configDefaults, defineConfig } from "vitest/config";
import { loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const environment = loadEnv(mode, ".", "");
  const apiProxyTarget = environment.VITE_EOAT_API_PROXY_TARGET;
  return {
    plugins: [react()],
    server: {
      port: 5173,
      // A loopback-only target allows local browser acceptance to retain the
      // same-origin, HttpOnly rehearsal cookie without enabling API CORS.
      proxy: apiProxyTarget ? { "/api": { target: apiProxyTarget, changeOrigin: true } } : undefined,
    },
    test: { environment: "jsdom", exclude: ["tests/e2e/**", ...configDefaults.exclude] },
  };
});
