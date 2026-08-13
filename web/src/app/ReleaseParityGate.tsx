import { useEffect, useState, type PropsWithChildren } from "react";

export type ReleaseIdentity = {
  product_version: string;
  release_id: string;
  build_id: string;
  candidate_id?: string | null;
  source_commit?: string | null;
  source_tree?: string | null;
  release_set_digest?: string | null;
};

declare const __EOAT_WEB_RELEASE_IDENTITY__: ReleaseIdentity | null;
declare const __EOAT_REQUIRE_RELEASE_PARITY__: boolean;

const configuredIdentity =
  typeof __EOAT_WEB_RELEASE_IDENTITY__ === "undefined"
    ? null
    : __EOAT_WEB_RELEASE_IDENTITY__;
const parityRequired =
  typeof __EOAT_REQUIRE_RELEASE_PARITY__ === "undefined"
    ? false
    : __EOAT_REQUIRE_RELEASE_PARITY__;

function equalIdentity(web: ReleaseIdentity, api: ReleaseIdentity) {
  return (
    web.product_version === api.product_version &&
    web.release_id === api.release_id &&
    web.build_id === api.build_id &&
    (!web.release_set_digest ||
      web.release_set_digest === api.release_set_digest)
  );
}

export function ReleaseParityGate({ children }: PropsWithChildren) {
  const [state, setState] = useState<"checking" | "ready" | "blocked">(
    parityRequired ? "checking" : "ready",
  );
  const [detail, setDetail] = useState(
    "Checking active EOAT Atlas release identity.",
  );

  useEffect(() => {
    if (!parityRequired || !configuredIdentity) return;
    let cancelled = false;
    const guardKey = `eoat-release-parity-reload:${configuredIdentity.release_id}:${configuredIdentity.build_id}`;
    const check = async () => {
      try {
        const response = await fetch("/api/v1/release-status", {
          cache: "no-store",
        });
        if (!response.ok)
          throw new Error(`Release status returned ${response.status}`);
        const api = (await response.json()) as ReleaseIdentity;
        if (equalIdentity(configuredIdentity, api)) {
          if (!cancelled) setState("ready");
          return;
        }
        if (!sessionStorage.getItem(guardKey)) {
          sessionStorage.setItem(guardKey, "1");
          window.location.reload();
          return;
        }
        if (!cancelled) {
          setDetail(
            "The web release does not match the active API. Reload after the coordinated release is healthy.",
          );
          setState("blocked");
        }
      } catch {
        if (!cancelled) {
          setDetail(
            "The active API release identity is unavailable. Normal operations remain blocked.",
          );
          setState("blocked");
        }
      }
    };
    void check();
    const recheck = () => void check();
    window.addEventListener("focus", recheck);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", recheck);
    };
  }, []);

  if (state === "ready") return <>{children}</>;
  return (
    <main aria-live="polite" role="status">
      <h1>{state === "checking" ? "Checking release" : "Update required"}</h1>
      <p>{detail}</p>
      {state === "blocked" && (
        <button onClick={() => window.location.reload()}>
          Retry release check
        </button>
      )}
    </main>
  );
}
