import { fileURLToPath, URL } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const environment = loadEnv(mode, process.cwd(), "");
  const apiProxyTarget =
    environment.EOAT_API_PROXY_TARGET ?? "http://127.0.0.1:8765";

  try {
    const target = new URL(apiProxyTarget);
    if (!["http:", "https:"].includes(target.protocol))
      throw new Error("unsupported protocol");
  } catch {
    throw new Error(
      "EOAT_API_PROXY_TARGET must be an absolute http(s) URL when supplied.",
    );
  }

  return {
    plugins: [react()],
    resolve: {
      alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
    },
    define: {
      __EOAT_WEB_VERSION__: JSON.stringify(
        process.env.npm_package_version ?? "development",
      ),
    },
    server: {
      proxy: {
        "/api": { target: apiProxyTarget, changeOrigin: true },
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: "./src/test/setup.ts",
      globals: true,
      css: true,
      pool: "threads",
      include: ["src/**/*.test.{ts,tsx}"],
    },
  };
});
