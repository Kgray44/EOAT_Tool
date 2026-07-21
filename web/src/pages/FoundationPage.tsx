import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/api/client";
import {
  ErrorState,
  LoadingState,
  StatusValue,
} from "@/components/feedback/StateViews";

export function FoundationPage() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => apiClient.getHealth(),
  });
  return (
    <section className="foundation-page">
      <p className="eyebrow">Phase 0</p>
      <h2>A secure foundation for EOAT Atlas on the web</h2>
      <p className="lede">
        This read-only shell uses the existing EOAT Atlas API. It does not
        replace the desktop client or invent operational data.
      </p>
      <section className="status-card" aria-labelledby="connection-status">
        <h3 id="connection-status">API connection status</h3>
        {health.isPending && <LoadingState />}
        {health.isError && <ErrorState error={health.error} />}
        {health.data && (
          <dl className="status-grid">
            <div>
              <dt>Connection</dt>
              <dd>Confirmed by API response</dd>
            </div>
            <div>
              <dt>API contract</dt>
              <dd>
                <StatusValue value={health.data.api_contract_version} />
              </dd>
            </div>
            <div>
              <dt>Application version</dt>
              <dd>
                <StatusValue value={health.data.application_version} />
              </dd>
            </div>
            <div>
              <dt>Schema compatibility</dt>
              <dd>
                {health.data.compatible ? "Compatible" : "Not compatible"}
              </dd>
            </div>
            <div>
              <dt>Current schema</dt>
              <dd>
                <StatusValue value={health.data.current_schema_revision} />
              </dd>
            </div>
            <div>
              <dt>Writes</dt>
              <dd>
                {health.data.writes_enabled ? "Enabled by API" : "Disabled"}
              </dd>
            </div>
          </dl>
        )}
      </section>
      <p className="foundation-note">
        Profile pages, search, library, and fit checks are registered for direct
        navigation but intentionally deferred to later phases.
      </p>
      <p className="build-note">Web build {__EOAT_WEB_VERSION__}</p>
    </section>
  );
}
