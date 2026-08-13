import { readFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const environment = loadEnv(mode, process.cwd(), "");
  const releaseVersion = JSON.parse(
    readFileSync(new URL("../app/atlas/version.json", import.meta.url), "utf8"),
  ).version as string;
  let releaseIdentity: Record<string, string> | null = null;
  try {
    releaseIdentity = JSON.parse(
      readFileSync(
        new URL("../release_metadata.json", import.meta.url),
        "utf8",
      ),
    ) as Record<string, string>;
  } catch {
    // Local development has no generated immutable candidate metadata.
  }
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
      __EOAT_WEB_VERSION__: JSON.stringify(releaseVersion),
      __EOAT_WEB_RELEASE_IDENTITY__: JSON.stringify(
        releaseIdentity
          ? {
              product_version:
                releaseIdentity.app_version ??
                releaseIdentity.application_version ??
                releaseVersion,
              release_id: releaseIdentity.release_id,
              build_id: releaseIdentity.build_id,
              candidate_id: releaseIdentity.candidate_id ?? null,
              source_commit: releaseIdentity.source_git_commit ?? null,
              source_tree: releaseIdentity.source_tree ?? null,
              release_set_digest: releaseIdentity.release_set_digest ?? null,
            }
          : null,
      ),
      __EOAT_REQUIRE_RELEASE_PARITY__: JSON.stringify(Boolean(releaseIdentity)),
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
