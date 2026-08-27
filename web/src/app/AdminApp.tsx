import { createContext, useContext, useEffect, useMemo, useState } from "react";
import {
  Link,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";

import {
  adminApi,
  AdminApiError,
  type AdminDiagnostics,
  type AdminGroupPolicy,
  type AdminMapping,
  type AdminOverview,
  type AdminRecord,
  type AdminSetting,
  type CorporateUserDetail,
  type CorporateUserSummary,
  type CorporateUsersList,
  type AuditCatalog,
  type AuditEvent,
  type AuditList,
  type AuditValue,
} from "../api/admin";
import { ApiError } from "../api/errors";
import { apiClient } from "../api/client";
import { AuditDiff } from "../components/AuditDiff";
import { formatTime } from "../lib/time";

type Remote<T> =
  | { state: "loading" }
  | { state: "error"; error: AdminApiError }
  | { state: "ready"; value: T };

type AdminSessionState = { ready: boolean; setReady: (ready: boolean) => void };
const AdminSessionContext = createContext<AdminSessionState | undefined>(
  undefined,
);

function useAdminSession(): AdminSessionState {
  const value = useContext(AdminSessionContext);
  if (!value) throw new Error("Administrator session state is unavailable.");
  return value;
}

function useRemote<T>(
  load: (signal: AbortSignal) => Promise<T>,
  key: string,
): Remote<T> {
  const [state, setState] = useState<Remote<T>>({ state: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    setState({ state: "loading" });
    load(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setState({ state: "ready", value });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setState({
            state: "error",
            error:
              error instanceof AdminApiError
                ? error
                : new AdminApiError("The Administrator request failed.", 0),
          });
        }
      });
    return () => controller.abort();
    // `load` is intentionally represented by `key`: callers supply a stable
    // request identity so a render-local closure cannot cause a fetch loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return state;
}

function copy(value: string) {
  void navigator.clipboard?.writeText(value);
}

function ErrorState({ error }: { error: AdminApiError }) {
  if (error.status === 401 || error.status === 403) {
    return (
      <section className="state-panel denied" aria-labelledby="denied-title">
        <h1 id="denied-title">Administrator access required</h1>
        <p>
          Administrator data was not returned. Sign in through an approved
          Administrator identity, then try again.
        </p>
        {error.requestId ? (
          <p>
            Request ID: <code>{error.requestId}</code>
          </p>
        ) : null}
      </section>
    );
  }
  if (error.status === 404) {
    return (
      <section className="state-panel error" aria-labelledby="not-found-title">
        <h1 id="not-found-title">Audit event not found</h1>
        <p>
          The requested audit event is not available to this Administrator
          identity.
        </p>
        {error.requestId ? (
          <p>
            Request ID: <code>{error.requestId}</code>
          </p>
        ) : null}
      </section>
    );
  }
  return (
    <section className="state-panel error" aria-labelledby="error-title">
      <h1 id="error-title">Administrator data could not load</h1>
      <p>{error.message}</p>
      {error.requestId ? (
        <p>
          Request ID: <code>{error.requestId}</code>
        </p>
      ) : null}
    </section>
  );
}

function LoadingState() {
  return (
    <section className="state-panel" aria-live="polite">
      <h1>Loading Administrator data</h1>
      <p>The current server response is being retrieved.</p>
    </section>
  );
}

function AdminLayout({ children }: { children: React.ReactNode }) {
  const showTestControls =
    import.meta.env.DEV ||
    import.meta.env.VITE_EOAT_ALLOW_TEST_CONTROLS === "true";
  return (
    <div className="admin-layout">
      <a className="skip-link" href="#admin-content">
        Skip to main content
      </a>
      <aside className="admin-sidebar">
        <div className="admin-brand">
          <span>EOAT Atlas</span>
          <strong>Administration</strong>
        </div>
        <nav aria-label="Administration">
          <NavLink end to="/admin">
            Overview
          </NavLink>
          <NavLink to="/admin/audit">Audit ledger</NavLink>
          <span className="nav-section">Data management</span>
          <NavLink to="/admin/data/relationships">Relationships</NavLink>
          <NavLink to="/admin/data/documents">Documents</NavLink>
          <NavLink to="/admin/data/photos">Photos</NavLink>
          <NavLink to="/admin/data/bulk">Bulk Status Update</NavLink>
          <NavLink to="/admin/settings">Settings</NavLink>
          <NavLink to="/admin/users">Users &amp; Access</NavLink>
          <NavLink to="/admin/group-policies">Group access policies</NavLink>
          <NavLink to="/admin/system">System</NavLink>
          <NavLink to="/admin/integrity">Integrity and evidence</NavLink>
          {showTestControls ? (
            <NavLink to="/admin/danger-zone">Test controls</NavLink>
          ) : null}
          <a className="return-link" href="/">
            ← Return to EOAT Atlas
          </a>
        </nav>
      </aside>
      <main id="admin-content" className="admin-main" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}

function PageTitle({
  title,
  children,
}: {
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <header className="page-heading">
      <p className="eyebrow">Administration</p>
      <h1>{title}</h1>
      {children}
    </header>
  );
}

function recordValue(record: AdminRecord, ...keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (value !== undefined && value !== null && value !== "")
      return String(value);
  }
  return "Not recorded";
}

function humanize(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function statusLabel(value: string) {
  const normalized = value.toLowerCase();
  if (normalized.includes("healthy") || normalized === "enabled")
    return "healthy";
  if (normalized.includes("disabled") || normalized.includes("controlled"))
    return "controlled";
  if (normalized.includes("warning") || normalized.includes("degraded"))
    return "warning";
  return normalized === "unknown" ? "unknown" : "attention";
}

function EventLink({ event }: { event: AuditEvent }) {
  return (
    <Link to={`/admin/audit/events/${encodeURIComponent(event.event_id)}`}>
      {event.action} · {event.entity.display_id ?? event.entity.id}
    </Link>
  );
}

function OverviewPage() {
  const remote = useRemote<AdminOverview>(
    (signal) => adminApi.overview(signal),
    "overview",
  );
  if (remote.state === "loading") return <LoadingState />;
  if (remote.state === "error") return <ErrorState error={remote.error} />;
  const { value } = remote;
  const metrics = [
    ["Events today (UTC)", value.metrics.events_today],
    ["Events, last 24 hours", value.metrics.events_last_24_hours],
    ["Successful", value.metrics.successful_events_last_24_hours],
    ["Failed", value.metrics.failed_events_last_24_hours],
    ["Denied", value.metrics.denied_events_last_24_hours],
    ["Security", value.metrics.security_events_last_24_hours],
    ["Unique actors", value.metrics.unique_actors_last_24_hours],
  ];
  const healthy = [
    value.api_status,
    value.database_status,
    value.audit_status,
  ].every((status) => status.toLowerCase() === "healthy");
  return (
    <>
      <PageTitle title="Administrative overview">
        <p>
          An operational summary from server-observed health and immutable audit
          evidence. Last updated {formatTime(value.observation_time_utc)}.
        </p>
      </PageTitle>
      <section className="heartbeat-banner" aria-label="Application heartbeat">
        <span
          className={`heartbeat-dot ${healthy ? "healthy" : "attention"}`}
          aria-hidden="true"
        />
        <div>
          <strong>
            {healthy ? "EOAT Atlas is healthy" : "EOAT Atlas needs attention"}
          </strong>
          <span>
            Heartbeat observed {formatTime(value.observation_time_utc)}
          </span>
        </div>
        <dl>
          <dt>Release / API</dt>
          <dd>{value.api_version}</dd>
          <dt>Schema</dt>
          <dd>{value.schema_revision ?? "Not reported"}</dd>
        </dl>
      </section>
      <section className="card-grid status-grid" aria-label="System identity">
        <StatusCard
          label="API"
          value={value.api_status}
          detail={`Contract ${value.api_version}`}
        />
        <StatusCard
          label="Database"
          value={value.database_status}
          detail={`Schema ${value.schema_revision ?? "unknown"}`}
        />
        <StatusCard
          label="Audit"
          value={value.audit_status}
          detail={`Schema v${value.audit_schema_version}`}
        />
        <StatusCard
          label="Writes"
          value={
            value.writes_enabled
              ? "healthy — enabled"
              : "healthy — disabled by policy"
          }
          detail={`Environment ${value.environment}; server-owned gate`}
        />
      </section>
      <section aria-labelledby="activity-title">
        <div className="section-heading">
          <h2 id="activity-title">Audit activity</h2>
          <Link to="/admin/audit">Open full Audit Ledger</Link>
        </div>
        <div className="card-grid metrics-grid">
          {metrics.map(([label, metric]) => (
            <article className="metric-card" key={String(label)}>
              <span>{label}</span>
              <strong>{metric}</strong>
            </article>
          ))}
        </div>
      </section>
      <section aria-labelledby="recent-title">
        <div className="section-heading">
          <h2 id="recent-title">Recent activity</h2>
          <Link to="/admin/audit">Investigate all events</Link>
        </div>
        {value.recent_events.length ? (
          <ol className="recent-list">
            {value.recent_events.map((event) => (
              <li key={event.event_id}>
                <time dateTime={event.occurred_at_utc}>
                  {formatTime(event.occurred_at_utc)}
                </time>
                <EventLink event={event} />
                <span>
                  {event.actor.display_name ?? event.actor.type} ·{" "}
                  {event.result}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="state-note">No audit events have been recorded.</p>
        )}
      </section>
      <section className="shortcuts" aria-label="Administrator shortcuts">
        <Link to="/admin/audit">Full Audit Ledger</Link>
        <Link to="/admin/system">System status</Link>
        <Link to="/admin/integrity">Integrity and evidence</Link>
      </section>
    </>
  );
}

function StatusCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <article className={`status-card ${statusLabel(value)}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

const filterNames = [
  "start",
  "end",
  "actor",
  "action",
  "action_category",
  "entity_type",
  "entity_id",
  "result",
  "source",
  "request_id",
  "correlation_id",
  "search",
  "current_user_changes",
  "security_events_only",
  "administrative_events_only",
  "page",
  "page_size",
];

function validAuditParams(raw: URLSearchParams) {
  const params = new URLSearchParams();
  filterNames.forEach((name) => {
    const value = raw.get(name);
    if (value && value.length <= 255) params.set(name, value);
  });
  const page = Number(params.get("page") ?? "1");
  if (!Number.isInteger(page) || page < 1) params.set("page", "1");
  const size = Number(params.get("page_size") ?? "50");
  if (!Number.isInteger(size) || size < 1 || size > 250)
    params.set("page_size", "50");
  return params;
}

function setFilter(params: URLSearchParams, name: string, value: string) {
  const next = new URLSearchParams(params);
  if (value) next.set(name, value);
  else next.delete(name);
  next.set("page", "1");
  return next;
}

function AuditPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const params = useMemo(() => validAuditParams(searchParams), [searchParams]);
  const catalog = useRemote<AuditCatalog>(
    (signal) => adminApi.catalog(signal),
    "catalog",
  );
  const ledger = useRemote<AuditList>(
    (signal) => adminApi.audit(params, signal),
    params.toString(),
  );
  const update = (name: string, value: string) =>
    setSearchParams(setFilter(params, name, value));
  if (catalog.state === "error") return <ErrorState error={catalog.error} />;
  if (ledger.state === "error") return <ErrorState error={ledger.error} />;
  return (
    <>
      <PageTitle title="Global Audit Ledger">
        <p>
          Authoritative immutable evidence. Filters, sorting, and pagination are
          executed by the server.
        </p>
      </PageTitle>
      <AuditFilters
        params={params}
        update={update}
        catalog={catalog.state === "ready" ? catalog.value : undefined}
      />
      <section aria-live="polite">
        {ledger.state === "loading" ? (
          <LoadingState />
        ) : (
          <AuditTable
            result={ledger.value}
            params={params}
            setSearchParams={setSearchParams}
          />
        )}
      </section>
    </>
  );
}

function AuditFilters({
  params,
  update,
  catalog,
}: {
  params: URLSearchParams;
  update: (name: string, value: string) => void;
  catalog?: AuditCatalog;
}) {
  const today = new Date();
  today.setUTCHours(0, 0, 0, 0);
  const toggle = (
    name:
      | "current_user_changes"
      | "security_events_only"
      | "administrative_events_only",
  ) => update(name, params.get(name) === "true" ? "" : "true");
  return (
    <section className="filters" aria-labelledby="filter-title">
      <div className="section-heading">
        <h2 id="filter-title">Investigate events</h2>
        <button
          type="button"
          className="link-button"
          onClick={() => update("search", "")}
        >
          Clear search
        </button>
      </div>
      <div className="filter-grid">
        <label>
          Search safe evidence
          <input
            value={params.get("search") ?? ""}
            onChange={(e) => update("search", e.target.value)}
            placeholder="Event, actor, request, or entity"
          />
        </label>
        <label>
          Start (UTC)
          <input
            type="datetime-local"
            value={params.get("start")?.slice(0, 16) ?? ""}
            onChange={(e) =>
              update("start", e.target.value ? `${e.target.value}:00Z` : "")
            }
          />
        </label>
        <label>
          End (UTC)
          <input
            type="datetime-local"
            value={params.get("end")?.slice(0, 16) ?? ""}
            onChange={(e) =>
              update("end", e.target.value ? `${e.target.value}:00Z` : "")
            }
          />
        </label>
        <Select
          label="Action"
          value={params.get("action") ?? ""}
          values={catalog?.actions}
          onChange={(value) => update("action", value)}
        />
        <Select
          label="Category"
          value={params.get("action_category") ?? ""}
          values={catalog?.action_categories}
          onChange={(value) => update("action_category", value)}
        />
        <Select
          label="Entity type"
          value={params.get("entity_type") ?? ""}
          values={catalog?.entity_types}
          onChange={(value) => update("entity_type", value)}
        />
        <Select
          label="Result"
          value={params.get("result") ?? ""}
          values={catalog?.results}
          onChange={(value) => update("result", value)}
        />
        <Select
          label="Source"
          value={params.get("source") ?? ""}
          values={catalog?.sources}
          onChange={(value) => update("source", value)}
        />
        <label>
          Actor
          <input
            value={params.get("actor") ?? ""}
            onChange={(e) => update("actor", e.target.value)}
          />
        </label>
        <label>
          Entity ID
          <input
            value={params.get("entity_id") ?? ""}
            onChange={(e) => update("entity_id", e.target.value)}
          />
        </label>
        <label>
          Request ID
          <input
            value={params.get("request_id") ?? ""}
            onChange={(e) => update("request_id", e.target.value)}
          />
        </label>
        <label>
          Correlation ID
          <input
            value={params.get("correlation_id") ?? ""}
            onChange={(e) => update("correlation_id", e.target.value)}
          />
        </label>
        <Select
          label="Page size"
          value={params.get("page_size") ?? "50"}
          values={["25", "50", "100", "250"]}
          onChange={(value) => update("page_size", value || "50")}
        />
      </div>
      <div className="preset-row">
        <button
          type="button"
          onClick={() => update("start", today.toISOString())}
        >
          Today (UTC)
        </button>
        <button
          type="button"
          onClick={() =>
            update("start", new Date(Date.now() - 3600_000).toISOString())
          }
        >
          Last hour
        </button>
        <button
          type="button"
          onClick={() =>
            update("start", new Date(Date.now() - 86_400_000).toISOString())
          }
        >
          Last 24 hours
        </button>
        <button
          type="button"
          onClick={() =>
            update("start", new Date(Date.now() - 7 * 86_400_000).toISOString())
          }
        >
          Last 7 days
        </button>
        <button type="button" onClick={() => update("result", "FAILURE")}>
          Failed
        </button>
        <button type="button" onClick={() => update("result", "DENIED")}>
          Denied
        </button>
        <button
          type="button"
          aria-pressed={params.get("current_user_changes") === "true"}
          onClick={() => toggle("current_user_changes")}
        >
          My activity
        </button>
        <button
          type="button"
          aria-pressed={params.get("security_events_only") === "true"}
          onClick={() => toggle("security_events_only")}
        >
          Security / authentication
        </button>
        <button
          type="button"
          aria-pressed={params.get("administrative_events_only") === "true"}
          onClick={() => toggle("administrative_events_only")}
        >
          Administrative operations
        </button>
      </div>
    </section>
  );
}

function Select({
  label,
  value,
  values,
  onChange,
}: {
  label: string;
  value: string;
  values?: string[];
  onChange: (value: string) => void;
}) {
  return (
    <label>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {label === "Page size" ? null : <option value="">All</option>}
        {(values ?? []).map((option) => (
          <option key={option} value={option}>
            {option.replaceAll("_", " ")}
          </option>
        ))}
      </select>
    </label>
  );
}

function AuditTable({
  result,
  params,
  setSearchParams,
}: {
  result: AuditList;
  params: URLSearchParams;
  setSearchParams: (next: URLSearchParams) => void;
}) {
  const pages = Math.max(1, Math.ceil(result.total / result.page_size));
  const goTo = (page: number) => {
    const next = new URLSearchParams(params);
    next.set("page", String(page));
    setSearchParams(next);
  };
  return (
    <>
      <div className="table-summary">
        <span>
          {result.total} matching event{result.total === 1 ? "" : "s"}
        </span>
        <span>Order: persisted time, then persisted sequence</span>
      </div>
      {result.items.length ? (
        <div className="audit-table-wrap">
          <table className="audit-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Entity</th>
                <th>Changed fields</th>
                <th>Result</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {result.items.map((event) => (
                <tr key={event.event_id}>
                  <td data-label="Time">
                    <time dateTime={event.occurred_at_utc}>
                      {formatTime(event.occurred_at_utc)}
                    </time>
                  </td>
                  <td data-label="Actor">
                    {event.actor.display_name ?? event.actor.type}
                  </td>
                  <td data-label="Action">
                    <EventLink event={event} />
                  </td>
                  <td data-label="Entity">
                    {event.entity.type} ·{" "}
                    {event.entity.display_id ?? event.entity.id}
                  </td>
                  <td data-label="Changed fields">
                    {event.changed_fields.join(", ") || "—"}
                  </td>
                  <td data-label="Result">
                    <span
                      className={`result result-${event.result.toLowerCase()}`}
                    >
                      {event.result}
                    </span>
                  </td>
                  <td data-label="Source">{event.source_client}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="state-note">No audit events match these filters.</p>
      )}
      <nav className="pagination" aria-label="Audit pagination">
        <button
          type="button"
          disabled={result.page <= 1}
          onClick={() => goTo(result.page - 1)}
        >
          Previous
        </button>
        <span>
          Page {result.page} of {pages}
        </span>
        <button
          type="button"
          disabled={result.page >= pages}
          onClick={() => goTo(result.page + 1)}
        >
          Next
        </button>
      </nav>
    </>
  );
}

function EventDetailPage() {
  const { eventId = "" } = useParams();
  const navigate = useNavigate();
  const remote = useRemote<AuditEvent>(
    (signal) => adminApi.event(eventId, signal),
    `event:${eventId}`,
  );
  if (remote.state === "loading") return <LoadingState />;
  if (remote.state === "error") return <ErrorState error={remote.error} />;
  const event = remote.value;
  const entityPath = entityLink(event);
  const summary = auditEventSummary(event);
  return (
    <>
      <PageTitle title="Audit event detail">
        <button
          type="button"
          className="link-button"
          onClick={() => navigate(-1)}
        >
          ← Back to investigation
        </button>
      </PageTitle>
      <section className="event-summary-card" aria-label="Event summary">
        <div>
          <span className={`result result-${event.result.toLowerCase()}`}>
            {event.result}
          </span>
          <h2>Event summary</h2>
        </div>
        <p>
          <strong>{summary.sentence}</strong>
        </p>
        {summary.changes.length ? <p>{summary.changes.join(" · ")}</p> : null}
        <dl className="event-summary-facts">
          <div>
            <dt>Actor</dt>
            <dd>{event.actor.display_name ?? event.actor.type}</dd>
          </div>
          <div>
            <dt>Occurred</dt>
            <dd>{formatTime(event.occurred_at_utc)}</dd>
          </div>
          {event.reason_or_note ? (
            <div>
              <dt>Reason</dt>
              <dd>{event.reason_or_note}</dd>
            </div>
          ) : null}
        </dl>
      </section>
      <section className="detail-summary">
        <Detail label="Event ID" value={event.event_id} copyable />
        <Detail
          label="Occurred"
          value={`${formatTime(event.occurred_at_utc)} (UTC: ${event.occurred_at_utc})`}
        />
        <Detail
          label="Action"
          value={`${event.action} · ${event.action_category}`}
        />
        <Detail label="Result" value={event.result} />
        <Detail label="Source" value={event.source_client} />
      </section>
      <section className="detail-grid">
        <article>
          <h2>Actor</h2>
          <Detail
            label="Display"
            value={event.actor.display_name ?? "Not recorded"}
          />
          <Detail label="Type" value={event.actor.type} />
          <Detail label="Stable ID" value={event.actor.id ?? "Not recorded"} />
          <Detail
            label="Directory identity"
            value={event.actor.directory_name ?? "Not recorded"}
          />
        </article>
        <article>
          <h2>Entity</h2>
          <Detail label="Type" value={event.entity.type} />
          <Detail label="Stable ID" value={event.entity.id} />
          <Detail
            label="Display ID"
            value={event.entity.display_id ?? "Not recorded"}
          />
          {entityPath ? (
            <Link to={entityPath}>Open normal profile</Link>
          ) : (
            <p className="state-note">
              No canonical normal-profile link is available for this entity
              type.
            </p>
          )}
        </article>
      </section>
      <section>
        <h2>Structured change evidence</h2>
        <AuditDiff
          changedFields={event.changed_fields}
          before={event.before}
          after={event.after}
        />
      </section>
      {event.reason_or_note ? (
        <section>
          <h2>Reason or note</h2>
          <p>{event.reason_or_note}</p>
        </section>
      ) : null}
      <section className="detail-grid">
        <article>
          <h2>Request context</h2>
          <Detail
            label="Request ID"
            value={event.request_id ?? "Not recorded"}
            copyable
            link={
              event.request_id
                ? `/admin/audit?request_id=${encodeURIComponent(event.request_id)}`
                : undefined
            }
          />
          <Detail
            label="Correlation ID"
            value={event.correlation_id ?? "Not recorded"}
            copyable
            link={
              event.correlation_id
                ? `/admin/audit?correlation_id=${encodeURIComponent(event.correlation_id)}`
                : undefined
            }
          />
          <Detail
            label="Transaction ID"
            value={event.transaction_id ?? "Not recorded"}
          />
          <Detail label="Operation" value={event.operation ?? "Not recorded"} />
        </article>
        <article>
          <h2>Related activity</h2>
          {event.correlation_id ? (
            <RelatedEvents
              correlationId={event.correlation_id}
              currentEventId={event.event_id}
            />
          ) : (
            <p className="state-note">
              This event has no recorded correlation ID.
            </p>
          )}
        </article>
      </section>
    </>
  );
}

function auditEventSummary(event: AuditEvent) {
  const actor = event.actor.display_name ?? event.actor.type;
  const entity =
    event.entity.display_id || `${event.entity.type} ${event.entity.id}`;
  const operation = event.operation || event.action;
  const verbs: Record<string, string> = {
    "admin.group-policy.create": "created corporate group policy",
    "admin.group-policy.update": "changed corporate group policy",
    "admin.group-policy.deactivate": "deactivated corporate group policy",
    "admin.relationship.unlink": "unlinked relationship",
    "admin.setting.update": "changed setting",
    "admin.document.metadata.update": "changed document metadata",
    "admin.photo.metadata.update": "changed photo metadata",
    "admin.bulk-status.commit": "updated status for",
  };
  const sentence = `${actor} ${verbs[operation] || `performed ${event.action}`} on ${entity}.`;
  const labels: Record<string, string> = {
    role_code: "EOAT Atlas role",
    is_active: "Active",
    provider: "Authentication provider",
    value: "Value",
  };
  const sensitive = /(secret|password|token|credential|key)/i;
  const changes = event.changed_fields
    .filter((field) => !sensitive.test(field))
    .slice(0, 3)
    .map(
      (field) =>
        `${labels[field] || field.replaceAll("_", " ")}: ${auditSummaryValue(event.before?.[field])} → ${auditSummaryValue(event.after?.[field])}`,
    );
  return { sentence, changes };
}

function auditSummaryValue(value: AuditValue | undefined) {
  if (value === undefined) return "Not recorded";
  if (value === null) return "None";
  if (typeof value === "object") return "Updated";
  return String(value);
}

function RelatedEvents({
  correlationId,
  currentEventId,
}: {
  correlationId: string;
  currentEventId: string;
}) {
  const params = useMemo(
    () =>
      new URLSearchParams({ correlation_id: correlationId, page_size: "10" }),
    [correlationId],
  );
  const remote = useRemote<AuditList>(
    (signal) => adminApi.audit(params, signal),
    `related:${correlationId}`,
  );
  const filtered =
    remote.state === "ready"
      ? remote.value.items.filter((item) => item.event_id !== currentEventId)
      : [];
  return (
    <>
      {remote.state === "loading" ? (
        <p className="state-note">Loading correlated events…</p>
      ) : null}
      {remote.state === "error" ? (
        <p className="state-note">
          Related events could not load. Request ID:{" "}
          {remote.error.requestId ?? "not available"}
        </p>
      ) : null}
      {remote.state === "ready" && filtered.length ? (
        <ol className="related-list">
          {filtered.map((item) => (
            <li key={item.event_id}>
              <EventLink event={item} />
              <span>
                {formatTime(item.occurred_at_utc)} · {item.result}
              </span>
            </li>
          ))}
        </ol>
      ) : null}
      {remote.state === "ready" && !filtered.length ? (
        <p className="state-note">No other events share this correlation ID.</p>
      ) : null}
      <Link
        to={`/admin/audit?correlation_id=${encodeURIComponent(correlationId)}`}
      >
        View all events with this correlation ID
      </Link>
    </>
  );
}

function entityLink(event: AuditEvent) {
  const identifier = event.entity.display_id?.trim();
  if (!identifier) return undefined;
  const prefix = { eoat: "/eoats/", machine: "/machines/", tool: "/tools/" }[
    event.entity.type.toLowerCase()
  ];
  return prefix ? `${prefix}${encodeURIComponent(identifier)}` : undefined;
}
function Detail({
  label,
  value,
  copyable = false,
  link,
}: {
  label: string;
  value: string;
  copyable?: boolean;
  link?: string;
}) {
  return (
    <dl className="detail">
      <dt>{label}</dt>
      <dd>
        {link ? <Link to={link}>{value}</Link> : <code>{value}</code>}
        {copyable && value !== "Not recorded" ? (
          <button
            type="button"
            className="link-button"
            onClick={() => copy(value)}
          >
            Copy
          </button>
        ) : null}
      </dd>
    </dl>
  );
}

function SystemPage() {
  const remote = useRemote<AdminDiagnostics>(
    (signal) => adminApi.system(signal),
    "system",
  );
  if (remote.state === "loading") return <LoadingState />;
  if (remote.state === "error") return <ErrorState error={remote.error} />;
  const value = remote.value;
  return (
    <>
      <PageTitle title="System health">
        <p>
          Server-owned operational evidence, last checked{" "}
          {formatTime(value.observation_time_utc)}. A deliberately disabled
          capability can be healthy when policy controls it.
        </p>
      </PageTitle>
      <section className="settings-list">
        {value.checks.map((check) => (
          <article
            className={`editor-card health-check ${statusLabel(check.state)}`}
            key={check.check_id}
          >
            <div className="section-heading">
              <h2>{humanize(check.subsystem)}</h2>
              <strong>
                {check.state === "DISABLED"
                  ? "HEALTHY — Disabled by policy"
                  : check.state}
              </strong>
            </div>
            <p>{check.safe_detail}</p>
            <p className="state-note">
              {check.remediation_hint} · Source: {check.source} ·{" "}
              {formatTime(check.observed_at_utc)} · timeout{" "}
              {check.timeout_seconds ?? 5}s
            </p>
            {check.request_id ? (
              <p className="state-note">
                Request ID: <code>{check.request_id}</code>
              </p>
            ) : null}
          </article>
        ))}
      </section>
      <p className="state-note">
        System health does not provide SQL, shell, filesystem, log-browsing, or
        arbitrary mutation capabilities.
      </p>
    </>
  );
}

function SessionGate({ onReady }: { onReady: () => void }) {
  const corporate = useRemote(
    () => adminApi.corporateStatus(),
    "corporate-auth-status",
  );
  const [corporateSession, setCorporateSession] = useState<
    | { state: "loading" }
    | { state: "anonymous" }
    | { state: "authorized" }
    | { state: "denied" }
    | { state: "error"; error: AdminApiError }
  >({ state: "loading" });
  const [identity, setIdentity] = useState("");
  const [rehearsalSecret, setRehearsalSecret] = useState("");
  const [corporatePassword, setCorporatePassword] = useState("");
  const [error, setError] = useState<AdminApiError | undefined>();
  const [busy, setBusy] = useState(false);
  const corporateEnabled =
    corporate.state === "ready" && corporate.value.provider === "kerberos_form";
  const configuredDevelopmentIdentity =
    import.meta.env.VITE_EOAT_IDENTITY ?? "dev.admin";

  useEffect(() => {
    if (corporate.state !== "ready") return;
    if (!corporateEnabled) {
      setCorporateSession({ state: "anonymous" });
      return;
    }
    let active = true;
    void adminApi
      .corporateSession()
      .then((session) => {
        if (!active) return;
        setCorporateSession(
          session.authenticated && session.roles?.includes("ADMINISTRATOR")
            ? { state: "authorized" }
            : { state: "denied" },
        );
      })
      .catch((value: unknown) => {
        if (!active) return;
        if (value instanceof ApiError && value.status === 401) {
          setCorporateSession({ state: "anonymous" });
          return;
        }
        setCorporateSession({
          state: "error",
          error:
            value instanceof ApiError
              ? new AdminApiError(
                  value.message,
                  value.status ?? 0,
                  value.requestId,
                )
              : new AdminApiError(
                  "The corporate session could not be verified.",
                  0,
                ),
        });
      });
    return () => {
      active = false;
    };
  }, [corporate.state, corporateEnabled]);

  useEffect(() => {
    if (corporateSession.state === "authorized") onReady();
  }, [corporateSession.state, onReady]);

  const start = () => {
    setBusy(true);
    setError(undefined);
    const action = corporateEnabled
      ? adminApi.corporateLogin(identity, corporatePassword)
      : adminApi.startRehearsal(
          identity.trim() || configuredDevelopmentIdentity,
          rehearsalSecret,
        );
    action
      .then(() => {
        setRehearsalSecret("");
        setCorporatePassword("");
        onReady();
      })
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError(
                "The development/test session could not start.",
                0,
              ),
        ),
      )
      .finally(() => setBusy(false));
  };
  if (corporate.state === "loading") return <LoadingState />;
  if (corporate.state === "error")
    return <ErrorState error={corporate.error} />;
  if (corporateSession.state === "loading") return <LoadingState />;
  if (corporateSession.state === "authorized") return <LoadingState />;
  if (corporateSession.state === "denied") {
    return (
      <ErrorState
        error={
          new AdminApiError(
            "The active corporate session is not authorized for Administration.",
            403,
          )
        }
      />
    );
  }
  if (corporateSession.state === "error") {
    return <ErrorState error={corporateSession.error} />;
  }
  return (
    <section className="state-panel">
      <h1>
        {corporateEnabled
          ? "Corporate Administrator sign-in"
          : "Start development/test Administrator session"}
      </h1>
      <p>
        {corporateEnabled
          ? "Sign-in uses the approved Kerberos-form provider. The password is used only for the protected server-side Kerberos exchange and is never retained by this browser or EOAT Atlas."
          : "This local rehearsal session is separate from production corporate authentication. Its CSRF proof remains only in this browser memory; the actor is resolved from the HttpOnly server session for every governed mutation."}
      </p>
      <label>
        {corporateEnabled
          ? "Corporate username"
          : "Configured development/test identity"}
        <input
          value={identity}
          onChange={(event) => setIdentity(event.target.value)}
          autoComplete={corporateEnabled ? "username" : "off"}
          placeholder={
            corporateEnabled
              ? "jdoe or GWP\\jdoe"
              : configuredDevelopmentIdentity
          }
        />
      </label>
      {corporateEnabled ? (
        <label>
          Corporate password
          <input
            type="password"
            value={corporatePassword}
            onChange={(event) => setCorporatePassword(event.target.value)}
            autoComplete="current-password"
          />
        </label>
      ) : (
        <label>
          Development/test rehearsal secret
          <input
            type="password"
            value={rehearsalSecret}
            onChange={(event) => setRehearsalSecret(event.target.value)}
            autoComplete="current-password"
          />
        </label>
      )}
      <button
        className="primary-button"
        type="button"
        disabled={
          busy ||
          (corporateEnabled
            ? identity.trim().length < 1 || corporatePassword.length < 1
            : rehearsalSecret.length < 16)
        }
        onClick={start}
      >
        {busy
          ? "Starting…"
          : corporateEnabled
            ? "Sign in"
            : "Start governed session"}
      </button>
      {error ? (
        <p className="inline-error">
          {error.message}
          {error.requestId ? ` Request ID: ${error.requestId}` : ""}
        </p>
      ) : null}
    </section>
  );
}

const editorFields: Record<string, Array<[string, string]>> = {
  eoats: [
    ["display_name", "Display name"],
    ["description", "Description"],
    ["revision", "Revision"],
    ["manufacturer", "Manufacturer"],
    ["number_of_parts_picked", "Parts picked"],
    ["number_of_vacuum_cups", "Vacuum cups"],
    ["number_of_grippers", "Grippers"],
    ["notes", "Notes"],
  ],
  machines: [
    ["machine_name", "Machine name"],
    ["manufacturer", "Manufacturer"],
    ["model", "Model"],
    ["serial_number", "Serial number"],
    ["machine_type", "Machine type"],
    ["press_capacity_tons", "Press capacity (tons)"],
    ["controller_type", "Controller type"],
    ["notes", "Notes"],
  ],
  tools: [
    ["tool_number", "Tool number"],
    ["mold_number", "Mold number"],
    ["display_name", "Display name"],
    ["description", "Description"],
    ["cavity_count", "Cavity count"],
    ["tool_type", "Tool type"],
    ["customer", "Customer"],
    ["program_name", "Program"],
    ["notes", "Notes"],
  ],
};

function AuditSuccess({ eventId }: { eventId?: string }) {
  return eventId ? (
    <p className="success-note">
      Committed with immutable evidence.{" "}
      <Link to={`/admin/audit/events/${encodeURIComponent(eventId)}`}>
        View Audit Event
      </Link>
    </p>
  ) : null;
}

function AssetEditor({
  kind,
  record,
  onCommitted,
}: {
  kind: "eoats" | "machines" | "tools";
  record: AdminRecord;
  onCommitted: (auditEventId: string) => void;
}) {
  const identifier = String(
    record[kind === "machines" ? "machine_number" : "business_identifier"] ??
      "",
  );
  const [values, setValues] = useState<Record<string, AuditValue>>({});
  const [reason, setReason] = useState("");
  const [correction, setCorrection] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [preview, setPreview] = useState<
    | {
        changed_fields: string[];
        before: Record<string, AuditValue>;
        after: Record<string, AuditValue>;
      }
    | undefined
  >();
  const [error, setError] = useState<AdminApiError | undefined>();
  const [busy, setBusy] = useState(false);
  const [audit, setAudit] = useState<string>();
  useEffect(() => {
    setValues(
      Object.fromEntries(
        editorFields[kind].map(([field]) => [field, record[field] ?? ""]),
      ),
    );
    setPreview(undefined);
    setError(undefined);
    setAudit(undefined);
    setReason("");
    setCorrection(false);
    setConfirmation("");
  }, [kind, record]);
  const payload = (): Record<string, AuditValue> => {
    const changed = Object.fromEntries(
      Object.entries(values).filter(
        ([field, value]) => String(value ?? "") !== String(record[field] ?? ""),
      ),
    );
    return {
      ...changed,
      expected_row_version: Number(record.row_version ?? 0),
      ...(correction ? { reason } : {}),
    };
  };
  const previewChange = () => {
    setBusy(true);
    setError(undefined);
    adminApi
      .previewAsset(kind, identifier, payload())
      .then(setPreview)
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Preview failed.", 0),
        ),
      )
      .finally(() => setBusy(false));
  };
  const commit = () => {
    if (!preview?.changed_fields.length) return;
    setBusy(true);
    setError(undefined);
    adminApi
      .updateAsset(kind, identifier, payload(), correction)
      .then((result) => {
        setAudit(result.audit_event_id);
        onCommitted(result.audit_event_id);
      })
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Commit failed.", 0),
        ),
      )
      .finally(() => setBusy(false));
  };
  const lifecycle = (action: "archive" | "restore") => {
    setBusy(true);
    setError(undefined);
    adminApi
      .lifecycleAsset(kind, identifier, action, {
        expected_row_version: Number(record.row_version ?? 0),
        reason:
          reason ||
          `${action} requested through governed Administrator workflow`,
        confirmation,
      })
      .then((result) => {
        setAudit(result.audit_event_id);
        onCommitted(result.audit_event_id);
      })
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Lifecycle action failed.", 0),
        ),
      )
      .finally(() => setBusy(false));
  };
  return (
    <section className="editor-card">
      <div className="section-heading">
        <h2>{identifier}</h2>
        <a href={`/${kind}/${encodeURIComponent(identifier)}`}>
          Open normal profile
        </a>
      </div>
      <p className="state-note">
        Stable identity, database ID, audit fields, timestamps, and row version
        are read-only. Current revision:{" "}
        {String(record.row_version ?? "unknown")}.
      </p>
      <div className="editor-grid">
        {editorFields[kind].map(([field, label]) => (
          <label key={field}>
            {label}
            <input
              type={
                field.includes("count") ||
                field.includes("capacity") ||
                field.includes("picked") ||
                field.includes("cups") ||
                field.includes("grippers")
                  ? "number"
                  : "text"
              }
              value={String(values[field] ?? "")}
              onChange={(event) =>
                setValues({
                  ...values,
                  [field]:
                    event.target.value === ""
                      ? null
                      : event.target.type === "number"
                        ? Number(event.target.value)
                        : event.target.value,
                })
              }
            />
          </label>
        ))}
      </div>
      <label className="check-row">
        <input
          type="checkbox"
          checked={correction}
          onChange={(event) => setCorrection(event.target.checked)}
        />{" "}
        Record this as a correction that preserves the prior evidence
      </label>
      {correction ? (
        <label>
          Correction reason
          <input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            required
          />
        </label>
      ) : null}
      <div className="editor-actions">
        <button type="button" onClick={previewChange} disabled={busy}>
          Preview material change
        </button>
        <button
          className="primary-button"
          type="button"
          onClick={commit}
          disabled={
            busy ||
            !preview?.changed_fields.length ||
            (correction && reason.trim().length < 3)
          }
        >
          {busy ? "Submitting…" : "Commit governed edit"}
        </button>
      </div>
      {preview ? (
        <section className="preview-panel" aria-live="polite">
          <h3>Material change preview</h3>
          {preview.changed_fields.length ? (
            <ul>
              {preview.changed_fields.map((field) => (
                <li key={field}>
                  <strong>{field}</strong>:{" "}
                  {String(preview.before[field] ?? "unknown")} →{" "}
                  {String(preview.after[field] ?? "unknown")}
                </li>
              ))}
            </ul>
          ) : (
            <p>No material changes are ready to commit.</p>
          )}
        </section>
      ) : null}
      <section className="lifecycle-panel">
        <h3>Archive or restore</h3>
        <p>
          Archive is reversible and subject to domain constraints. Type{" "}
          <code>ARCHIVE {identifier}</code> or <code>RESTORE {identifier}</code>{" "}
          before continuing.
        </p>
        <label>
          Typed confirmation
          <input
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
          />
        </label>
        <div className="editor-actions">
          <button
            type="button"
            disabled={busy || confirmation !== `ARCHIVE ${identifier}`}
            onClick={() => lifecycle("archive")}
          >
            Archive record
          </button>
          <button
            type="button"
            disabled={busy || confirmation !== `RESTORE ${identifier}`}
            onClick={() => lifecycle("restore")}
          >
            Restore record
          </button>
        </div>
      </section>
      {error ? (
        <p className="inline-error">
          {error.message}
          {error.code === "STALE_RECORD_VERSION"
            ? " This record changed after you opened it; reload the latest values and reapply manually."
            : ""}
        </p>
      ) : null}
      <AuditSuccess eventId={audit} />
    </section>
  );
}

function DataIntegritySummary() {
  const remote = useRemote(
    (signal) => adminApi.latestIntegrity(signal),
    "latest-integrity-summary",
  );
  if (remote.state === "loading") {
    return (
      <p className="state-note">
        Loading the latest explicit integrity scan summary.
      </p>
    );
  }
  if (remote.state === "error") {
    return (
      <p className="inline-error">
        Integrity summary is unavailable: {remote.error.message}
      </p>
    );
  }
  const value = remote.value;
  return (
    <section className="editor-card" aria-labelledby="data-integrity-summary">
      <div className="section-heading">
        <h2 id="data-integrity-summary">Integrity summary</h2>
        <strong>{value.status}</strong>
      </div>
      <p>
        {value.finding_count == null
          ? "The latest integrity result is unavailable."
          : `${value.finding_count} finding(s) from the latest explicit scan.`}
      </p>
      {value.completed_at ? (
        <p className="state-note">
          Completed {formatTime(value.completed_at)}.
        </p>
      ) : null}
      <p className="state-note">
        By severity:{" "}
        {Object.entries(value.by_severity)
          .map(([key, count]) => `${key} ${count}`)
          .join(", ") || "none"}
        .
      </p>
      <Link to="/admin/integrity">
        Open integrity details and run a new scan
      </Link>
    </section>
  );
}

function DataPage({
  initialKind = "eoats",
}: {
  initialKind?: "eoats" | "machines" | "tools";
}) {
  const { ready, setReady } = useAdminSession();
  const [kind, setKind] = useState<"eoats" | "machines" | "tools">(initialKind);
  const [search, setSearch] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [selected, setSelected] = useState<AdminRecord>();
  const [refresh, setRefresh] = useState(0);
  const [lastAuditEvent, setLastAuditEvent] = useState<string>();
  useEffect(() => {
    setKind(initialKind);
    setSelected(undefined);
  }, [initialKind]);
  const remote = useRemote<{ items: AdminRecord[] }>(
    () => adminApi.assets(kind, search, includeArchived),
    `assets:${ready}:${kind}:${search}:${includeArchived}:${refresh}`,
  );
  if (!ready) return <SessionGate onReady={() => setReady(true)} />;
  if (remote.state === "error") return <ErrorState error={remote.error} />;
  return (
    <>
      <PageTitle title="Governed data management">
        <p>
          Use authoritative records and domain-aware fields. Preview first, then
          commit only a material, capability-authorized change with immutable
          Audit evidence.
        </p>
      </PageTitle>
      <AuditSuccess eventId={lastAuditEvent} />
      <DataIntegritySummary />
      <section className="filters">
        <div className="filter-grid">
          <Select
            label="Record type"
            value={kind}
            values={["eoats", "machines", "tools"]}
            onChange={(value) => {
              setKind(value as typeof kind);
              setSelected(undefined);
            }}
          />
          <label>
            Server-backed search
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Identifier, name, or description"
            />
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={(event) => {
                setIncludeArchived(event.target.checked);
                setSelected(undefined);
              }}
            />{" "}
            Include archived records for governed restore
          </label>
        </div>
      </section>
      {remote.state === "loading" ? (
        <LoadingState />
      ) : (
        <div className="management-grid">
          <section className="record-list" aria-label="Authoritative records">
            {remote.value.items.map((item) => {
              const id = String(
                item[
                  kind === "machines" ? "machine_number" : "business_identifier"
                ] ?? "",
              );
              return (
                <button
                  type="button"
                  key={id}
                  className={selected === item ? "selected" : ""}
                  onClick={() => setSelected(item)}
                >
                  <strong>{id}</strong>
                  <span>
                    {String(
                      item.display_name ??
                        item.machine_name ??
                        item.tool_number ??
                        "Unnamed",
                    )}
                  </span>
                </button>
              );
            })}
            {!remote.value.items.length ? (
              <p className="state-note">No records match the current search.</p>
            ) : null}
          </section>
          {selected ? (
            <AssetEditor
              kind={kind}
              record={selected}
              onCommitted={(auditEventId) => {
                setLastAuditEvent(auditEventId);
                setSelected(undefined);
                setRefresh(refresh + 1);
              }}
            />
          ) : (
            <p className="state-note">
              Select one record to inspect, preview, correct, archive, or
              restore.
            </p>
          )}
        </div>
      )}
    </>
  );
}

function DocumentsPage() {
  const { ready, setReady } = useAdminSession();
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<AdminRecord>();
  const [refresh, setRefresh] = useState(0);
  const [lastAuditEvent, setLastAuditEvent] = useState<string>();
  const remote = useRemote<{ items: AdminRecord[] }>(
    () => adminApi.documents(search),
    `documents:${ready}:${search}:${refresh}`,
  );
  if (!ready) return <SessionGate onReady={() => setReady(true)} />;
  if (remote.state === "error") return <ErrorState error={remote.error} />;
  if (remote.state === "loading") return <LoadingState />;
  return (
    <>
      <PageTitle title="Documents">
        <p>
          Review document records, open safe content, and make a focused,
          audited metadata change. Storage locations and checksums are never
          shown in Administration.
        </p>
      </PageTitle>
      <AuditSuccess eventId={lastAuditEvent} />
      <section className="filters">
        <label>
          Search documents
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Title, document number, or description"
          />
        </label>
      </section>
      {remote.value.items.length ? (
        <div className="audit-table-wrap">
          <table className="audit-table document-table">
            <thead>
              <tr>
                <th>Document</th>
                <th>Type / revision</th>
                <th>Status</th>
                <th>Effective / updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {remote.value.items.map((record) => {
                const uuid = recordValue(record, "document_uuid");
                const contentUrl =
                  uuid === "Not recorded"
                    ? undefined
                    : apiClient.documentContentUrl(uuid);
                return (
                  <tr key={String(record.id)}>
                    <td data-label="Document">
                      <strong>
                        {recordValue(record, "document_number", "title")}
                      </strong>
                      <span className="table-subtitle">
                        {recordValue(record, "title", "description")}
                      </span>
                    </td>
                    <td data-label="Type / revision">
                      {recordValue(record, "document_type", "document_type_id")}
                      <span className="table-subtitle">
                        Revision {recordValue(record, "revision")}
                      </span>
                    </td>
                    <td data-label="Status">
                      {recordValue(record, "status", "status_id")}
                    </td>
                    <td data-label="Effective / updated">
                      {recordValue(record, "effective_from", "updated_at")}
                    </td>
                    <td data-label="Actions" className="row-actions">
                      {contentUrl ? (
                        <a href={contentUrl} target="_blank" rel="noreferrer">
                          View
                        </a>
                      ) : null}
                      {contentUrl ? (
                        <a href={contentUrl} download>
                          Download
                        </a>
                      ) : null}
                      <button
                        type="button"
                        className="link-button"
                        onClick={() => setSelected(record)}
                      >
                        Edit metadata
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="state-note">No active documents match this search.</p>
      )}
      {selected ? (
        <section className="focused-editor" aria-label="Edit document metadata">
          <div className="section-heading">
            <h2>Edit metadata</h2>
            <button
              type="button"
              className="link-button"
              onClick={() => setSelected(undefined)}
            >
              Close
            </button>
          </div>
          <DocumentEditor
            record={selected}
            onDone={(auditEventId) => {
              setLastAuditEvent(auditEventId);
              setSelected(undefined);
              setRefresh((value) => value + 1);
            }}
          />
        </section>
      ) : null}
    </>
  );
}
function DocumentEditor({
  record,
  onDone,
}: {
  record: AdminRecord;
  onDone: (auditEventId: string) => void;
}) {
  const documentId = Number(record.id);
  const [title, setTitle] = useState(String(record.title ?? ""));
  const [reason, setReason] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [audit, setAudit] = useState<string>();
  const [error, setError] = useState<AdminApiError>();
  const update = () =>
    adminApi
      .updateDocument(documentId, {
        title,
        expected_row_version: Number(record.row_version),
        reason: reason || null,
      })
      .then((value) => {
        setAudit(value.audit_event_id);
        onDone(value.audit_event_id);
      })
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Document update failed.", 0),
        ),
      );
  const archive = () =>
    adminApi
      .archiveDocument(documentId, {
        expected_row_version: Number(record.row_version),
        reason,
        confirmation,
      })
      .then((value) => {
        setAudit(value.audit_event_id);
        onDone(value.audit_event_id);
      })
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Document archive failed.", 0),
        ),
      );
  return (
    <section className="editor-card">
      <h2>
        {String(
          record.document_number ?? record.title ?? `Document ${documentId}`,
        )}
      </h2>
      <p>
        Revision {String(record.revision ?? "not recorded")} · row version{" "}
        {String(record.row_version)}
      </p>
      <label>
        Title
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
      </label>
      <label>
        Reason (optional for metadata)
        <input
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <button className="primary-button" type="button" onClick={update}>
        Save metadata
      </button>
      <label>
        To archive, type <code>ARCHIVE DOCUMENT {documentId}</code>
        <input
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
        />
      </label>
      <button
        type="button"
        disabled={
          reason.trim().length < 3 ||
          confirmation !== `ARCHIVE DOCUMENT ${documentId}`
        }
        onClick={archive}
      >
        Archive document
      </button>
      {error ? <p className="inline-error">{error.message}</p> : null}
      <AuditSuccess eventId={audit} />
    </section>
  );
}

function PhotosPage() {
  const { ready, setReady } = useAdminSession();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<"newest" | "caption">("newest");
  const remote = useRemote<{
    items: Array<{
      photo: AdminRecord;
      document: AdminRecord;
      row_version: number;
    }>;
  }>(() => adminApi.photos(), `photos:${ready}`);
  if (!ready) return <SessionGate onReady={() => setReady(true)} />;
  if (remote.state === "error") return <ErrorState error={remote.error} />;
  if (remote.state === "loading") return <LoadingState />;
  return (
    <>
      <PageTitle title="Photos">
        <p>
          Browse managed images and open their Administration detail pages.
          Image content is served only through the safe managed-media APIs.
        </p>
      </PageTitle>
      <section className="filters">
        <div className="filter-grid">
          <label>
            Search photos
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Caption, photo type, or document"
            />
          </label>
          <label>
            Sort
            <select
              value={sort}
              onChange={(event) => setSort(event.target.value as typeof sort)}
            >
              <option value="newest">Newest first</option>
              <option value="caption">Caption</option>
            </select>
          </label>
        </div>
      </section>
      <div className="photo-grid">
        {remote.value.items
          .filter(({ photo, document }) =>
            `${recordValue(photo, "caption", "photo_view_type")} ${recordValue(document, "title", "document_number")}`
              .toLowerCase()
              .includes(search.toLowerCase()),
          )
          .sort((a, b) =>
            sort === "caption"
              ? recordValue(a.photo, "caption").localeCompare(
                  recordValue(b.photo, "caption"),
                )
              : Number(b.photo.id) - Number(a.photo.id),
          )
          .map((value) => {
            const uuid = recordValue(value.document, "document_uuid");
            const title = recordValue(
              value.document,
              "title",
              "document_number",
            );
            return (
              <Link
                className="photo-card"
                key={String(value.photo.id)}
                to={`/admin/data/photos/${encodeURIComponent(uuid)}`}
              >
                {uuid !== "Not recorded" ? (
                  <img
                    src={apiClient.photoThumbnailUrl(uuid)}
                    alt={recordValue(
                      value.photo,
                      "caption",
                      "photo_view_type",
                      "Photo",
                    )}
                  />
                ) : (
                  <div className="photo-placeholder">Image unavailable</div>
                )}
                <strong>{title}</strong>
                <span>
                  {recordValue(value.photo, "caption", "photo_view_type")}
                </span>
                {value.photo.is_profile_photo ? <em>Profile photo</em> : null}
              </Link>
            );
          })}
      </div>
      {!remote.value.items.length ? (
        <p className="state-note">
          No active photos are available in this environment.
        </p>
      ) : null}
    </>
  );
}
function PhotoEditor({
  value,
  onDone,
}: {
  value: { photo: AdminRecord; document: AdminRecord; row_version: number };
  onDone: (auditEventId: string) => void;
}) {
  const photoId = Number(value.photo.id);
  const [caption, setCaption] = useState(String(value.photo.caption ?? ""));
  const [reason, setReason] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [audit, setAudit] = useState<string>();
  const [error, setError] = useState<AdminApiError>();
  const update = () =>
    adminApi
      .updatePhoto(photoId, {
        caption,
        expected_row_version: value.row_version,
        reason: reason || null,
      })
      .then((result) => {
        setAudit(result.audit_event_id);
        onDone(result.audit_event_id);
      })
      .catch((result: unknown) =>
        setError(
          result instanceof AdminApiError
            ? result
            : new AdminApiError("Photo update failed.", 0),
        ),
      );
  const archive = () =>
    adminApi
      .archivePhoto(photoId, {
        expected_row_version: value.row_version,
        reason,
        confirmation,
      })
      .then((result) => {
        setAudit(result.audit_event_id);
        onDone(result.audit_event_id);
      })
      .catch((result: unknown) =>
        setError(
          result instanceof AdminApiError
            ? result
            : new AdminApiError("Photo archive failed.", 0),
        ),
      );
  return (
    <section className="editor-card">
      <h2>{String(value.document.title ?? `Photo ${photoId}`)}</h2>
      <label>
        Caption
        <input
          value={caption}
          onChange={(event) => setCaption(event.target.value)}
        />
      </label>
      <label>
        Reason
        <input
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <button className="primary-button" type="button" onClick={update}>
        Save photo metadata
      </button>
      <label>
        To archive, type <code>ARCHIVE PHOTO {photoId}</code>
        <input
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
        />
      </label>
      <button
        type="button"
        disabled={
          reason.trim().length < 3 ||
          confirmation !== `ARCHIVE PHOTO ${photoId}`
        }
        onClick={archive}
      >
        Archive photo
      </button>
      {error ? <p className="inline-error">{error.message}</p> : null}
      <AuditSuccess eventId={audit} />
    </section>
  );
}

function PhotoDetailPage() {
  const { ready, setReady } = useAdminSession();
  const { documentUuid = "" } = useParams();
  const [refresh, setRefresh] = useState(0);
  const remote = useRemote<{
    items: Array<{
      photo: AdminRecord;
      document: AdminRecord;
      row_version: number;
    }>;
  }>(
    () => adminApi.photos(),
    `photo-detail:${ready}:${documentUuid}:${refresh}`,
  );
  if (!ready) return <SessionGate onReady={() => setReady(true)} />;
  if (remote.state === "error") return <ErrorState error={remote.error} />;
  if (remote.state === "loading") return <LoadingState />;
  const value = remote.value.items.find(
    (item) => String(item.document.document_uuid) === documentUuid,
  );
  if (!value) return <NotFound />;
  const contentUrl = apiClient.photoContentUrl(documentUuid);
  return (
    <>
      <PageTitle
        title={recordValue(value.document, "title", "document_number")}
      >
        <p>
          Managed photo details and supported metadata. Filesystem paths are
          never displayed.
        </p>
      </PageTitle>
      <Link to="/admin/data/photos">← Back to Photos</Link>
      <section className="photo-detail">
        <img
          src={contentUrl}
          alt={recordValue(value.photo, "caption", "photo_view_type", "Photo")}
        />
        <div className="detail-grid">
          <article>
            <h2>Photo information</h2>
            <dl className="detail">
              <dt>Caption</dt>
              <dd>{recordValue(value.photo, "caption")}</dd>
              <dt>Photo type</dt>
              <dd>{recordValue(value.photo, "photo_view_type")}</dd>
              <dt>Captured</dt>
              <dd>{recordValue(value.photo, "captured_at")}</dd>
              <dt>Profile photo</dt>
              <dd>{value.photo.is_profile_photo ? "Yes" : "No"}</dd>
            </dl>
            <a href={contentUrl} download>
              Download full image
            </a>
          </article>
          <article>
            <h2>Edit or archive</h2>
            <PhotoEditor
              value={value}
              onDone={() => setRefresh((current) => current + 1)}
            />
          </article>
        </div>
      </section>
    </>
  );
}

function RelationshipsPage() {
  const { ready, setReady } = useAdminSession();
  const [relationshipType, setRelationshipType] = useState("eoat-machine");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [eoat, setEoat] = useState("");
  const [machine, setMachine] = useState("");
  const [tool, setTool] = useState("");
  const [status, setStatus] = useState("");
  const [reason, setReason] = useState("");
  const [audit, setAudit] = useState<string>();
  const [error, setError] = useState<AdminApiError>();
  const catalog = useRemote<{
    eoats: AdminRecord[];
    machines: AdminRecord[];
    tools: AdminRecord[];
    statuses: Array<{ code: string; display_name: string }>;
  }>(async () => {
    const [eoats, machines, tools, statuses] = await Promise.all([
      adminApi.assets("eoats"),
      adminApi.assets("machines"),
      adminApi.assets("tools"),
      adminApi.lookup("compatibility_statuses"),
    ]);
    return {
      eoats: eoats.items,
      machines: machines.items,
      tools: tools.items,
      statuses,
    };
  }, `relationship-selectors:${ready}`);
  const relations = useRemote<{ items: AdminRecord[] }>(
    () => adminApi.relationships(relationshipType),
    `relationships:${ready}:${relationshipType}:${audit ?? ""}`,
  );
  const targetIdentifiers =
    relationshipType === "eoat-machine"
      ? { eoat_identifier: eoat, machine_number: machine }
      : relationshipType === "eoat-tool"
        ? { eoat_identifier: eoat, tool_identifier: tool }
        : { tool_identifier: tool, machine_number: machine };
  const commit = () =>
    adminApi
      .linkRelationship(relationshipType, {
        ...targetIdentifiers,
        compatibility_status: status,
        verification_source: "user_verified",
        effective_from: new Date().toISOString(),
        reason: reason || null,
        confirmation: `LINK ${relationshipType}`,
      })
      .then((value) => setAudit(value.audit_event_id))
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Relationship update failed.", 0),
        ),
      );
  if (!ready) return <SessionGate onReady={() => setReady(true)} />;
  if (catalog.state === "error") return <ErrorState error={catalog.error} />;
  if (catalog.state === "loading" || relations.state === "loading")
    return <LoadingState />;
  if (relations.state === "error")
    return <ErrorState error={relations.error} />;
  const showEoat = relationshipType !== "tool-machine";
  const showMachine = relationshipType !== "eoat-tool";
  const showTool = relationshipType !== "eoat-machine";
  return (
    <>
      <PageTitle title="Relationships">
        <p>
          Search and review validated EOAT, Machine, and Tool links. Additions
          are resolved and validated by the server before they are committed.
        </p>
      </PageTitle>
      <section className="relationship-toolbar">
        <div
          className="relationship-tabs"
          role="tablist"
          aria-label="Relationship type"
        >
          {["eoat-machine", "eoat-tool", "tool-machine"].map((type) => (
            <button
              type="button"
              role="tab"
              aria-selected={relationshipType === type}
              className={relationshipType === type ? "selected" : ""}
              key={type}
              onClick={() => setRelationshipType(type)}
            >
              {type === "eoat-machine"
                ? "EOAT ↔ Machine"
                : type === "eoat-tool"
                  ? "EOAT ↔ Tool"
                  : "Tool ↔ Machine"}
            </button>
          ))}
        </div>
        <button
          className="primary-button"
          type="button"
          onClick={() => setShowAdd((visible) => !visible)}
        >
          {showAdd ? "Close" : "+ Add relationship"}
        </button>
      </section>
      <section className="filters">
        <div className="filter-grid">
          <label>
            Search relationships
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Source or target identifier"
            />
          </label>
          <label>
            Compatibility status
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
            >
              <option value="">All statuses</option>
              {catalog.value.statuses.map((item) => (
                <option key={item.code} value={item.code}>
                  {item.display_name}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>
      {showAdd ? (
        <section className="focused-editor">
          <h2>Add relationship</h2>
          {showEoat ? (
            <label>
              EOAT
              <select
                value={eoat}
                onChange={(event) => setEoat(event.target.value)}
              >
                <option value="">Select an EOAT</option>
                {catalog.value.eoats.map((row) => (
                  <option
                    key={String(row.business_identifier)}
                    value={String(row.business_identifier)}
                  >
                    {String(row.business_identifier)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {showMachine ? (
            <label>
              Machine
              <select
                value={machine}
                onChange={(event) => setMachine(event.target.value)}
              >
                <option value="">Select a Machine</option>
                {catalog.value.machines.map((row) => (
                  <option
                    key={String(row.machine_number)}
                    value={String(row.machine_number)}
                  >
                    {String(row.machine_number)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {showTool ? (
            <label>
              Tool
              <select
                value={tool}
                onChange={(event) => setTool(event.target.value)}
              >
                <option value="">Select a Tool</option>
                {catalog.value.tools.map((row) => (
                  <option
                    key={String(row.business_identifier)}
                    value={String(row.business_identifier)}
                  >
                    {String(row.business_identifier)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <label>
            Compatibility status
            <select
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              <option value="">
                Select an authoritative compatibility status
              </option>
              {catalog.value.statuses.map((value) => (
                <option key={value.code} value={value.code}>
                  {value.display_name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Reason (optional)
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          <p className="state-note">
            Typed confirmation is server-derived:{" "}
            <code>LINK {relationshipType}</code>.
          </p>
          <button
            className="primary-button"
            type="button"
            disabled={
              (showEoat && !eoat) ||
              (showMachine && !machine) ||
              (showTool && !tool) ||
              !status
            }
            onClick={commit}
          >
            Validate and add relationship
          </button>
          {error ? <p className="inline-error">{error.message}</p> : null}
          <AuditSuccess eventId={audit} />
        </section>
      ) : null}
      <section className="editor-card relationship-list">
        <h2>Current relationships</h2>
        <div className="audit-table-wrap">
          <table className="audit-table">
            <thead>
              <tr>
                <th>Source</th>
                <th>Target</th>
                <th>Compatibility</th>
                <th>Revision</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {relations.value.items
                .filter(
                  (row) =>
                    `${row.left ?? ""} ${row.right ?? ""}`
                      .toLowerCase()
                      .includes(search.toLowerCase()) &&
                    (!statusFilter ||
                      String(row.compatibility_status) === statusFilter),
                )
                .map((row) => (
                  <tr key={String(row.id)}>
                    <td>{String(row.left ?? "Not recorded")}</td>
                    <td>{String(row.right ?? "Not recorded")}</td>
                    <td>
                      {recordValue(
                        row,
                        "compatibility_status",
                        "compatibility_status_id",
                      )}
                    </td>
                    <td>{String(row.row_version)}</td>
                    <td>
                      <RelationshipUnlinkEditor
                        relationshipType={relationshipType}
                        row={row}
                        onDone={(auditEventId) => setAudit(auditEventId)}
                      />
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
        {!relations.value.items.length ? (
          <p className="state-note">No current relationships of this type.</p>
        ) : null}
      </section>
    </>
  );
}
function RelationshipUnlinkEditor({
  relationshipType,
  row,
  onDone,
}: {
  relationshipType: string;
  row: AdminRecord;
  onDone: (auditEventId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<AdminApiError>();
  const preview = useRemote(
    () => adminApi.relationshipUnlinkPreview(relationshipType, Number(row.id)),
    `unlink-preview:${relationshipType}:${String(row.id)}:${open}`,
  );
  const expected =
    preview.state === "ready" ? preview.value.confirmation_phrase : "";
  const unlink = () =>
    adminApi
      .unlinkRelationship(relationshipType, Number(row.id), {
        expected_row_version:
          preview.state === "ready"
            ? preview.value.row_version
            : Number(row.row_version),
        reason,
        confirmation,
      })
      .then((value) => {
        setOpen(false);
        onDone(value.audit_event_id);
      })
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Relationship unlink failed.", 0),
        ),
      );
  return (
    <div>
      <button
        className="destructive-button"
        type="button"
        onClick={() => setOpen(true)}
      >
        Unlink
      </button>
      {open ? (
        <div
          className="lifecycle-panel"
          role="dialog"
          aria-label="Unlink relationship"
        >
          <h3>Unlink relationship</h3>
          {preview.state === "loading" ? (
            <p>Resolving the current relationship…</p>
          ) : null}
          {preview.state === "ready" ? (
            <>
              <p>
                <strong>{preview.value.left}</strong> →{" "}
                <strong>{preview.value.right}</strong>
              </p>
              <p>
                Compatibility: {preview.value.compatibility_status}. Source:{" "}
                {preview.value.verification_source || "Not recorded"}.
              </p>
              <label>
                Unlink reason
                <input
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                />
              </label>
              <label>
                Type the exact confirmation: <code>{expected}</code>
                <input
                  value={confirmation}
                  onChange={(event) => setConfirmation(event.target.value)}
                />
              </label>
              <button
                type="button"
                className="destructive-button"
                disabled={reason.trim().length < 3 || confirmation !== expected}
                onClick={unlink}
              >
                Unlink relationship
              </button>
            </>
          ) : null}
          {preview.state === "error" ? (
            <p className="inline-error">
              The relationship is no longer available; refresh the list.
            </p>
          ) : null}
          {error ? <p className="inline-error">{error.message}</p> : null}
          <button
            className="secondary-button"
            type="button"
            onClick={() => setOpen(false)}
          >
            Cancel
          </button>
        </div>
      ) : null}
    </div>
  );
}

function BulkStatusPage() {
  const { ready, setReady } = useAdminSession();
  const [identifiersText, setIdentifiersText] = useState("");
  const [status, setStatus] = useState("active");
  const [reason, setReason] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [preview, setPreview] = useState<{
    count: number;
    records: AdminRecord[];
    atomic: boolean;
  }>();
  const [audit, setAudit] = useState<string>();
  const [error, setError] = useState<AdminApiError>();
  const assets = useRemote<{ items: AdminRecord[] }>(
    () => adminApi.assets("eoats"),
    `bulk-assets:${ready}`,
  );
  const identifiers = identifiersText
    .split(/[\s,]+/)
    .map((value) => value.trim())
    .filter(Boolean);
  const expectedVersions = Object.fromEntries(
    (assets.state === "ready" ? assets.value.items : [])
      .filter((row) => identifiers.includes(String(row.business_identifier)))
      .map((row) => [String(row.business_identifier), Number(row.row_version)]),
  );
  const previewChange = () =>
    adminApi
      .previewBulkStatus({
        identifiers,
        status,
        expected_versions: expectedVersions,
      })
      .then(setPreview)
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Bulk preview failed.", 0),
        ),
      );
  const commit = () =>
    adminApi
      .commitBulkStatus({
        identifiers,
        status,
        expected_versions: expectedVersions,
        reason,
        confirmation,
      })
      .then((value) => setAudit(value.audit_event_id))
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Bulk commit failed.", 0),
        ),
      );
  if (!ready) return <SessionGate onReady={() => setReady(true)} />;
  if (assets.state === "error") return <ErrorState error={assets.error} />;
  if (assets.state === "loading") return <LoadingState />;
  return (
    <>
      <PageTitle title="Bulk Status Update">
        <p>
          Change the status of multiple EOAT records in one audited atomic
          operation. Preview validates every row version before any write.
        </p>
      </PageTitle>
      <ol className="workflow-steps" aria-label="Bulk Status Update steps">
        <li className="active">1. Select EOATs</li>
        <li>2. Choose new status</li>
        <li>3. Enter reason</li>
        <li>4. Preview</li>
        <li>5. Apply</li>
      </ol>
      <section className="editor-card">
        <label>
          1. Select EOAT identifiers (comma or line separated)
          <textarea
            value={identifiersText}
            onChange={(event) => setIdentifiersText(event.target.value)}
          />
        </label>
        <label>
          2. New status code
          <input
            value={status}
            onChange={(event) => setStatus(event.target.value)}
          />
        </label>
        <button
          type="button"
          disabled={
            !identifiers.length ||
            Object.keys(expectedVersions).length !== identifiers.length
          }
          onClick={previewChange}
        >
          4. Preview affected EOATs
        </button>
        {preview ? (
          <p className="state-note">
            Preview covers {preview.count} record(s) atomically. No status has
            changed.
          </p>
        ) : null}
        <label>
          3. Reason
          <input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
        <label>
          5. Confirm the reviewed change: type{" "}
          <code>BULK STATUS {identifiers.length}</code>
          <input
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
          />
        </label>
        <button
          className="primary-button"
          type="button"
          disabled={
            !preview ||
            reason.trim().length < 3 ||
            confirmation !== `BULK STATUS ${identifiers.length}`
          }
          onClick={commit}
        >
          Apply audited atomic update
        </button>
        {error ? <p className="inline-error">{error.message}</p> : null}
        <AuditSuccess eventId={audit} />
      </section>
    </>
  );
}

function SettingsPage() {
  const { ready, setReady } = useAdminSession();
  const [refresh, setRefresh] = useState(0);
  const [lastAuditEvent, setLastAuditEvent] = useState<string>();
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const remote = useRemote<{ items: AdminSetting[] }>(
    () => adminApi.settings(),
    `settings:${ready}:${refresh}`,
  );
  if (!ready) return <SessionGate onReady={() => setReady(true)} />;
  if (remote.state === "error") return <ErrorState error={remote.error} />;
  if (remote.state === "loading") return <LoadingState />;
  const categories = [
    ...new Set(
      remote.value.items.map((setting) => setting.presentation.category),
    ),
  ];
  const activeCategory = category || categories[0] || "";
  const settings = remote.value.items.filter((setting) => {
    const haystack =
      `${setting.presentation.label} ${setting.presentation.description} ${setting.key}`.toLowerCase();
    return (
      setting.presentation.category === activeCategory &&
      haystack.includes(search.toLowerCase())
    );
  });
  return (
    <>
      <PageTitle title="Administrator Settings">
        <p>
          Only persisted, server-declared configuration is shown. Secrets are
          write-only and never returned to the browser or Audit payload.
        </p>
      </PageTitle>
      <AuditSuccess eventId={lastAuditEvent} />
      <div className="admin-settings-workspace">
        <nav className="admin-settings-nav" aria-label="Settings categories">
          {categories.map((value) => (
            <button
              className={value === activeCategory ? "is-active" : ""}
              key={value}
              type="button"
              onClick={() => setCategory(value)}
            >
              {value}
            </button>
          ))}
        </nav>
        <section className="admin-settings-panel">
          <div className="section-heading">
            <h2>{activeCategory}</h2>
            <label className="settings-search">
              Search settings
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search this category"
              />
            </label>
          </div>
          {activeCategory === "Test / Development" ? (
            <p className="test-only-note">
              TEST ONLY — these controls are separated from production
              Administration Settings.
            </p>
          ) : null}
          {settings.map((setting) => (
            <SettingEditor
              key={setting.key}
              setting={setting}
              onDone={(auditEventId) => {
                setLastAuditEvent(auditEventId);
                setRefresh((value) => value + 1);
              }}
            />
          ))}
          {!settings.length ? (
            <p className="state-note">
              No settings match this category and search.
            </p>
          ) : null}
        </section>
        {!remote.value.items.length ? (
          <p className="state-note">
            No persisted Administrator settings are configured in this
            environment.
          </p>
        ) : null}
      </div>
    </>
  );
}

function SettingEditor({
  setting,
  onDone,
}: {
  setting: AdminSetting;
  onDone: (auditEventId: string) => void;
}) {
  const secret = setting.secret_configured != null;
  const [value, setValue] = useState(String(setting.value ?? ""));
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<AdminApiError>();
  const save = () =>
    adminApi
      .updateSetting(setting.key, {
        value: secret
          ? value
          : setting.value_type === "boolean"
            ? value === "true"
            : setting.value_type === "integer"
              ? Number(value)
              : value,
        expected_row_version: setting.row_version,
        reason,
      })
      .then((result) => onDone(result.audit_event_id))
      .catch((reason: unknown) =>
        setError(
          reason instanceof AdminApiError
            ? reason
            : new AdminApiError("Setting update failed.", 0),
        ),
      );
  return (
    <section className="admin-setting-row">
      <div>
        <h3>{setting.presentation.label}</h3>
        <p>
          {setting.presentation.description}
          {setting.restart_required ? " Restart required after commit." : ""}
        </p>
        {setting.presentation.sensitivity === "secret" ? (
          <p className="table-subtitle">
            Existing secret values are never displayed.
          </p>
        ) : null}
      </div>
      <div className="admin-setting-control">
        <label>
          {secret ? "Replacement secret" : "Value"}
          {setting.presentation.control_type === "select" &&
          setting.presentation.allowed_values ? (
            <select
              value={value}
              onChange={(event) => setValue(event.target.value)}
            >
              {setting.presentation.allowed_values.map((option) => (
                <option key={String(option)} value={String(option)}>
                  {String(option)}
                </option>
              ))}
            </select>
          ) : setting.value_type === "boolean" && !secret ? (
            <select
              value={value}
              onChange={(event) => setValue(event.target.value)}
            >
              <option value="true">true</option>
              <option value="false">false</option>
            </select>
          ) : (
            <input
              type={
                secret
                  ? "password"
                  : setting.value_type === "integer"
                    ? "number"
                    : "text"
              }
              value={value}
              onChange={(event) => setValue(event.target.value)}
              autoComplete="off"
            />
          )}
        </label>
        <button
          className="primary-button"
          type="button"
          disabled={
            setting.value_type === "integer" && !Number.isInteger(Number(value))
          }
          onClick={() => setConfirming(true)}
        >
          Save setting
        </button>
      </div>
      {confirming ? (
        <div
          className="settings-confirmation"
          role="dialog"
          aria-label={`Confirm ${setting.presentation.label}`}
        >
          <strong>Record a reason before saving</strong>
          <label>
            Reason
            <input
              autoFocus
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          <button
            className="secondary-button"
            type="button"
            onClick={() => setConfirming(false)}
          >
            Cancel
          </button>
          <button
            className="primary-button"
            type="button"
            disabled={reason.trim().length < 3}
            onClick={save}
          >
            Confirm save
          </button>
        </div>
      ) : null}
      {error ? <p className="inline-error">{error.message}</p> : null}
    </section>
  );
}

function UsersPage() {
  const { ready, setReady } = useAdminSession();
  const [params, setParams] = useSearchParams();
  const search = params.get("search") ?? "";
  const role = params.get("role") ?? "";
  const status = params.get("status") ?? "";
  const source = params.get("access_source") ?? "";
  const sort = params.get("sort") ?? "last_sign_in";
  const direction = params.get("direction") ?? "desc";
  const page = Number(params.get("page") ?? "1");
  const remote = useRemote<CorporateUsersList>(
    (signal) => adminApi.users(params, signal),
    `users:${ready}:${params.toString()}`,
  );
  if (!ready) return <SessionGate onReady={() => setReady(true)} />;
  if (remote.state === "error") return <ErrorState error={remote.error} />;
  if (remote.state === "loading") return <LoadingState />;
  const update = (updates: Record<string, string>) => {
    const next = new URLSearchParams(params);
    Object.entries(updates).forEach(([key, value]) => {
      if (value) next.set(key, value);
      else next.delete(key);
    });
    if (!Object.hasOwn(updates, "page")) next.set("page", "1");
    setParams(next);
  };
  return (
    <>
      <PageTitle title="Users & Access">
        <p>
          Corporate users are registered only after successful sign-in.
          Effective application access is resolved server-side; external group
          membership remains externally managed.
        </p>
      </PageTitle>
      <section className="filters" aria-label="User directory filters">
        <div className="filter-grid">
          <label>
            Search name or identity
            <input
              value={search}
              onChange={(event) => update({ search: event.target.value })}
            />
          </label>
          <label>
            Role
            <select
              value={role}
              onChange={(event) => update({ role: event.target.value })}
            >
              <option value="">All roles</option>
              {[
                "VIEWER",
                "ADMIN_AUDITOR",
                "ADMIN_DATA_MANAGER",
                "ADMIN_SETTINGS_MANAGER",
                "ADMIN_ACCESS_MANAGER",
                "ADMINISTRATOR",
              ].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
          <label>
            Status
            <select
              value={status}
              onChange={(event) => update({ status: event.target.value })}
            >
              <option value="">All statuses</option>
              <option value="active">Active</option>
              <option value="disabled">Disabled</option>
            </select>
          </label>
          <label>
            Access source
            <select
              value={source}
              onChange={(event) =>
                update({ access_source: event.target.value })
              }
            >
              <option value="">All sources</option>
              <option value="explicit_user_assignment">
                Explicit assignment
              </option>
              <option value="corporate_group">Corporate group</option>
              <option value="default">Default</option>
              <option value="explicit_deny">Explicit deny</option>
            </select>
          </label>
          <label>
            Sort
            <select
              value={sort}
              onChange={(event) => update({ sort: event.target.value })}
            >
              <option value="name">Name</option>
              <option value="role">Role</option>
              <option value="first_sign_in">First sign-in</option>
              <option value="last_sign_in">Last sign-in</option>
              <option value="status">Status</option>
            </select>
          </label>
          <label>
            Direction
            <select
              value={direction}
              onChange={(event) => update({ direction: event.target.value })}
            >
              <option value="asc">Ascending</option>
              <option value="desc">Descending</option>
            </select>
          </label>
        </div>
      </section>
      {!remote.value.items.length ? (
        <p className="state-note">
          No corporate users match the current filters.
        </p>
      ) : (
        <div className="audit-table-wrap">
          <table className="audit-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Corporate identity</th>
                <th>Effective role</th>
                <th>Source</th>
                <th>Status</th>
                <th>Last sign-in</th>
                <th>First sign-in</th>
                <th>Sessions</th>
              </tr>
            </thead>
            <tbody>
              {remote.value.items.map((user) => (
                <tr key={user.user_id}>
                  <td data-label="Name">
                    <Link
                      to={`/admin/users/${encodeURIComponent(user.user_id)}${params.toString() ? `?${params}` : ""}`}
                    >
                      {user.name}
                    </Link>
                  </td>
                  <td data-label="Corporate identity">
                    {user.corporate_identity}
                  </td>
                  <td data-label="Effective role">{user.effective_role}</td>
                  <td data-label="Source">
                    {user.access_source.replaceAll("_", " ")}
                  </td>
                  <td data-label="Status">{user.status}</td>
                  <td data-label="Last sign-in">
                    {formatTime(user.last_sign_in)}
                  </td>
                  <td data-label="First sign-in">
                    {formatTime(user.first_sign_in)}
                  </td>
                  <td data-label="Sessions">
                    {user.active_sessions
                      ? `${user.active_sessions} active`
                      : "None"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="pagination">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => update({ page: String(page - 1) })}
        >
          Previous
        </button>
        <span>
          Page {page} · {remote.value.total} users
        </span>
        <button
          type="button"
          disabled={remote.value.items.length < remote.value.page_size}
          onClick={() => update({ page: String(page + 1) })}
        >
          Next
        </button>
      </div>
    </>
  );
}

function UserDetailPage() {
  const { ready, setReady } = useAdminSession();
  const { userId = "" } = useParams();
  const location = useLocation();
  const [refresh, setRefresh] = useState(0);
  const remote = useRemote<CorporateUserDetail>(
    (signal) => adminApi.user(userId, signal),
    `user:${userId}:${ready}:${refresh}`,
  );
  if (!ready) return <SessionGate onReady={() => setReady(true)} />;
  if (remote.state === "error") return <ErrorState error={remote.error} />;
  if (remote.state === "loading") return <LoadingState />;
  const user = remote.value;
  return (
    <>
      <PageTitle title={user.name}>
        <Link className="return-link" to={`/admin/users${location.search}`}>
          ← Back to Users &amp; Access
        </Link>
        <p>
          {user.corporate_identity} · {user.provider}
        </p>
      </PageTitle>
      <div className="detail-summary">
        <div>
          <strong>Effective role</strong>
          <span>{user.effective_role}</span>
        </div>
        <div>
          <strong>Access source</strong>
          <span>{user.access_source.replaceAll("_", " ")}</span>
        </div>
        <div>
          <strong>Status</strong>
          <span>{user.status}</span>
        </div>
        <div>
          <strong>Sign-ins</strong>
          <span>{user.sign_in_count}</span>
        </div>
      </div>
      <div className="detail-grid">
        <article>
          <h2>Identity</h2>
          <dl className="detail">
            <dt>First seen</dt>
            <dd>{formatTime(user.first_sign_in)}</dd>
            <dt>Last sign-in</dt>
            <dd>{formatTime(user.last_sign_in)}</dd>
            <dt>Explicit assignment</dt>
            <dd>{user.explicit_role ?? "None"}</dd>
            <dt>Explicit deny</dt>
            <dd>{user.explicit_denied ? "Yes" : "No"}</dd>
          </dl>
        </article>
        <article>
          <h2>Governed access</h2>
          <CorporateAccessEditor
            user={user}
            onDone={() => setRefresh((value) => value + 1)}
          />
        </article>
      </div>
      <section className="editor-card">
        <h2>Safe session references</h2>
        <p>Session tokens, cookies, and CSRF proofs are never displayed.</p>
        {user.sessions.map((session) => (
          <CorporateSessionEditor
            key={session.session_reference}
            userId={user.user_id}
            session={session}
            onDone={() => setRefresh((value) => value + 1)}
          />
        ))}
        {!user.sessions.length ? (
          <p className="state-note">No corporate sessions are recorded.</p>
        ) : null}
      </section>
      <section className="editor-card">
        <h2>Access history</h2>
        {user.access_history.map((event) => (
          <p key={event.event_id}>
            <Link
              to={`/admin/audit/events/${encodeURIComponent(event.event_id)}`}
            >
              {event.action}
            </Link>{" "}
            · {event.actor ?? "Unknown actor"} · {formatTime(event.occurred_at)}
            {event.reason ? ` · ${event.reason}` : ""}
          </p>
        ))}
        {!user.access_history.length ? (
          <p className="state-note">No governed access changes are recorded.</p>
        ) : null}
      </section>
    </>
  );
}

function CorporateAccessEditor({
  user,
  onDone,
}: {
  user: CorporateUserSummary;
  onDone: () => void;
}) {
  const [action, setAction] = useState("assign");
  const [role, setRole] = useState("VIEWER");
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<{ confirmation: string }>();
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<AdminApiError>();
  const payload = {
    action,
    ...(action === "assign" ? { role_code: role } : {}),
    reason,
    expected_row_version: user.row_version,
  };
  const previewChange = () => {
    setError(undefined);
    adminApi
      .previewUserAccess(user.user_id, payload)
      .then((value) => {
        setPreview(value);
        setConfirmed(false);
      })
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Access preview failed.", 0),
        ),
      );
  };
  const commit = () => {
    setError(undefined);
    adminApi
      .commitUserAccess(user.user_id, {
        ...payload,
        confirmation: preview?.confirmation ?? "",
      })
      .then(() => {
        setPreview(undefined);
        setConfirmed(false);
        onDone();
      })
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Access change failed.", 0),
        ),
      );
  };
  return (
    <div className="editor-grid">
      <label>
        Action
        <select
          value={action}
          onChange={(event) => {
            setAction(event.target.value);
            setPreview(undefined);
          }}
        >
          <option value="assign">Assign or change role</option>
          <option value="revoke">Revoke application access</option>
          <option value="restore">Restore access</option>
          <option value="remove">Remove explicit assignment</option>
        </select>
      </label>
      {action === "assign" ? (
        <label>
          Role
          <select
            value={role}
            onChange={(event) => setRole(event.target.value)}
          >
            {[
              "VIEWER",
              "ADMIN_AUDITOR",
              "ADMIN_DATA_MANAGER",
              "ADMIN_SETTINGS_MANAGER",
              "ADMIN_ACCESS_MANAGER",
              "ADMINISTRATOR",
            ].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
      ) : null}
      <label>
        Reason
        <input
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <button
        className="primary-button"
        type="button"
        disabled={reason.trim().length < 3}
        onClick={previewChange}
      >
        Preview change
      </button>
      {preview ? (
        <>
          <p className="preview-panel">
            Review the proposed role and access source above. This change will
            be audited and active sessions may be revoked.
          </p>
          <label className="check-row">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />{" "}
            I understand and confirm this governed access change.
          </label>
          <button
            className="primary-button"
            type="button"
            disabled={!confirmed}
            onClick={commit}
          >
            Confirm governed change
          </button>
        </>
      ) : null}
      {error ? <p className="inline-error">{error.message}</p> : null}
    </div>
  );
}

function CorporateSessionEditor({
  userId,
  session,
  onDone,
}: {
  userId: string;
  session: {
    session_reference: string;
    issued_at: string;
    expires_at: string;
    state: string;
    provider: string;
  };
  onDone: () => void;
}) {
  const [reason, setReason] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<AdminApiError>();
  const expected = `REVOKE ${session.session_reference}`;
  const revoke = () =>
    adminApi
      .revokeCorporateSession(userId, session.session_reference, {
        reason,
        confirmation,
      })
      .then(onDone)
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Session revocation failed.", 0),
        ),
      );
  return (
    <div className="lifecycle-panel">
      <strong>{session.session_reference}</strong>
      <span>
        {" "}
        · {session.provider} · {session.state} · expires{" "}
        {formatTime(session.expires_at)}
      </span>
      {session.state === "active" ? (
        <>
          <label>
            Reason
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          <label>
            Type <code>{expected}</code>
            <input
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={reason.trim().length < 3 || confirmation !== expected}
            onClick={revoke}
          >
            Revoke session
          </button>
        </>
      ) : null}
      {error ? <p className="inline-error">{error.message}</p> : null}
    </div>
  );
}

const GROUP_POLICY_ROLES = [
  "VIEWER",
  "TECHNICIAN",
  "ENGINEER",
  "ADMIN_AUDITOR",
  "ADMIN_DATA_MANAGER",
  "ADMIN_SETTINGS_MANAGER",
  "ADMIN_ACCESS_MANAGER",
];

const GROUP_POLICY_CAPABILITIES = [
  ["DATA EDITING", "eoat.edit", "Edit EOAT records"],
  ["DATA EDITING", "machine.edit", "Edit Machine records"],
  ["DATA EDITING", "tool.edit", "Edit Tool records"],
  [
    "RELATIONSHIPS",
    "relationship.edit",
    "Create/edit relationships and compatibility",
  ],
  ["RELATIONSHIPS", "relationship.delete", "Remove relationships"],
  ["OPERATIONS", "assignment.edit", "Update assignments and locations"],
  ["OPERATIONS", "location.record", "Record location observations"],
  ["OPERATIONS", "audit.create", "Record audits and observations"],
  ["FILES", "document.create", "Add documents"],
  ["FILES", "document.edit", "Edit document metadata"],
  ["FILES", "document.remove", "Archive documents"],
  ["FILES", "photo.create", "Add photos"],
  ["FILES", "photo.edit", "Edit photo metadata/profile photo"],
  ["FILES", "photo.remove", "Archive photos"],
  ["OPERATIONS", "bulk_status.execute", "Bulk Status Update"],
] as const;

function GroupPolicyCapabilities({
  value,
  onChange,
}: {
  value: string[];
  onChange: (value: string[]) => void;
}) {
  const sections = [
    ...new Set(GROUP_POLICY_CAPABILITIES.map(([section]) => section)),
  ];
  return (
    <fieldset className="group-policy-capabilities">
      <legend>Operational editing capabilities</legend>
      {sections.map((section) => (
        <div key={section}>
          <strong>{section}</strong>
          {GROUP_POLICY_CAPABILITIES.filter(
            ([candidate]) => candidate === section,
          ).map(([, permission, label]) => (
            <label key={permission} className="check-row">
              <input
                type="checkbox"
                checked={value.includes(permission)}
                onChange={(event) =>
                  onChange(
                    event.target.checked
                      ? [...value, permission]
                      : value.filter((item) => item !== permission),
                  )
                }
              />
              {label}
            </label>
          ))}
        </div>
      ))}
      <small>
        Administration, access, system, integrity, and release permissions
        remain Administrator-only.
      </small>
    </fieldset>
  );
}

function GroupPolicyPage() {
  const { ready, setReady } = useAdminSession();
  const [refresh, setRefresh] = useState(0);
  const [adding, setAdding] = useState(false);
  const [showInactive, setShowInactive] = useState(false);
  const [lastAuditEvent, setLastAuditEvent] = useState<string>();
  const remote = useRemote<{ items: AdminGroupPolicy[] }>(
    () => adminApi.groupPolicies(showInactive),
    `group-policies:${ready}:${showInactive}:${refresh}`,
  );
  if (!ready) return <SessionGate onReady={() => setReady(true)} />;
  if (remote.state === "error") return <ErrorState error={remote.error} />;
  if (remote.state === "loading") return <LoadingState />;
  const done = (auditEventId: string) => {
    setLastAuditEvent(auditEventId);
    setRefresh((value) => value + 1);
    setAdding(false);
  };
  return (
    <>
      <PageTitle title="Group Access Policies">
        <p>
          Group policies map approved corporate directory groups to EOAT Atlas
          roles. Users receive access according to their resolved corporate
          group memberships and explicitly supported user-level rules.
        </p>
      </PageTitle>
      <AuditSuccess eventId={lastAuditEvent} />
      <div className="page-actions">
        <button
          className="primary-button"
          type="button"
          onClick={() => setAdding(true)}
        >
          + Add group policy
        </button>
        <label className="check-row">
          <input
            type="checkbox"
            checked={showInactive}
            onChange={(event) => setShowInactive(event.target.checked)}
          />{" "}
          Show inactive policies
        </label>
      </div>
      {adding ? (
        <GroupPolicyCreateForm
          onDone={done}
          onCancel={() => setAdding(false)}
        />
      ) : null}
      <section
        className="audit-table-wrap"
        aria-label="Corporate group policies"
      >
        <table className="audit-table">
          <thead>
            <tr>
              <th>Corporate group</th>
              <th>EOAT Atlas role</th>
              <th>Status</th>
              <th>Updated</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {remote.value.items.map((policy) => (
              <GroupPolicyRow key={policy.id} policy={policy} onDone={done} />
            ))}
          </tbody>
        </table>
        {!remote.value.items.length ? (
          <p className="state-note">
            No corporate group policies are configured.
          </p>
        ) : null}
      </section>
      <p className="table-subtitle">
        Policies are resolved by the server. This view does not enumerate
        directory membership or expose directory credentials.
      </p>
    </>
  );
}

function GroupPolicyCreateForm({
  onDone,
  onCancel,
}: {
  onDone: (auditEventId: string) => void;
  onCancel: () => void;
}) {
  const [corporateGroup, setCorporateGroup] = useState("");
  const [role, setRole] = useState("VIEWER");
  const [reason, setReason] = useState("");
  const [permissions, setPermissions] = useState<string[]>([]);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<AdminApiError>();
  const changed = () => setConfirming(false);
  const create = () =>
    adminApi
      .createGroupPolicy({
        corporate_group: corporateGroup.trim(),
        role_code: role,
        reason,
        permissions,
      })
      .then((result) => onDone(result.audit_event_id))
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Group policy creation failed.", 0),
        ),
      );
  return (
    <section className="editor-card focused-editor">
      <h2>Add group policy</h2>
      <p>
        Enter the exact corporate group identifier used by the configured
        corporate provider.
      </p>
      <div className="editor-grid">
        <label>
          Corporate group
          <input
            value={corporateGroup}
            onChange={(event) => {
              setCorporateGroup(event.target.value);
              changed();
            }}
          />
        </label>
        <label>
          EOAT Atlas role
          <select
            value={role}
            onChange={(event) => {
              setRole(event.target.value);
              changed();
            }}
          >
            {GROUP_POLICY_ROLES.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          Reason
          <input
            value={reason}
            onChange={(event) => {
              setReason(event.target.value);
              changed();
            }}
          />
        </label>
      </div>
      <GroupPolicyCapabilities
        value={permissions}
        onChange={(value) => {
          setPermissions(value);
          changed();
        }}
      />
      <div className="preview-panel">
        <strong>Preview</strong>
        <p>
          {corporateGroup.trim() || "Corporate group"} → {role}
        </p>
      </div>
      {!confirming ? (
        <button
          type="button"
          disabled={
            corporateGroup.trim().length < 3 || reason.trim().length < 3
          }
          onClick={() => setConfirming(true)}
        >
          Review change
        </button>
      ) : (
        <button className="primary-button" type="button" onClick={create}>
          Confirm and create policy
        </button>
      )}
      <button type="button" onClick={onCancel}>
        Cancel
      </button>
      {error ? <p className="inline-error">{error.message}</p> : null}
    </section>
  );
}

function GroupPolicyRow({
  policy,
  onDone,
}: {
  policy: AdminGroupPolicy;
  onDone: (auditEventId: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [role, setRole] = useState(policy.role_code);
  const [reason, setReason] = useState("");
  const [permissions, setPermissions] = useState(policy.permissions ?? []);
  const [confirming, setConfirming] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState<AdminApiError>();
  const commit = (isActive = policy.is_active) =>
    adminApi
      .updateGroupPolicy(policy.id, {
        role_code: role,
        is_active: isActive,
        expected_row_version: policy.row_version,
        reason,
        permissions,
      })
      .then((result) => onDone(result.audit_event_id))
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Group policy update failed.", 0),
        ),
      );
  const remove = () =>
    adminApi
      .deactivateGroupPolicy(policy.id, {
        expected_row_version: policy.row_version,
        reason,
        confirmed: true,
      })
      .then((result) => onDone(result.audit_event_id))
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Group policy removal failed.", 0),
        ),
      );
  return (
    <>
      <tr>
        <td data-label="Corporate group">
          <strong>{policy.corporate_group}</strong>
          <span className="table-subtitle">
            {policy.provider} · revision {policy.row_version}
          </span>
        </td>
        <td data-label="EOAT Atlas role">{policy.role_code}</td>
        <td data-label="Status">{policy.status}</td>
        <td data-label="Updated">{formatTime(policy.updated_at)}</td>
        <td data-label="Actions">
          <button
            className="secondary-button"
            type="button"
            onClick={() => setEditing((value) => !value)}
          >
            View / edit
          </button>
          {policy.is_protected_system_policy ? (
            <span className="protected-policy-note">
              Required Administrator recovery policy
            </span>
          ) : policy.is_active ? (
            <button
              className="destructive-button"
              type="button"
              onClick={() => {
                setRemoving(true);
                setEditing(false);
              }}
            >
              Remove policy
            </button>
          ) : null}
        </td>
      </tr>
      {editing ? (
        <tr>
          <td colSpan={5}>
            <div className="lifecycle-panel">
              <div className="editor-grid">
                <label>
                  Mapped role
                  <select
                    value={role}
                    onChange={(event) => {
                      setRole(event.target.value);
                      setConfirming(false);
                    }}
                  >
                    {GROUP_POLICY_ROLES.map((value) => (
                      <option key={value}>{value}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Reason
                  <input
                    value={reason}
                    onChange={(event) => {
                      setReason(event.target.value);
                      setConfirming(false);
                    }}
                  />
                </label>
              </div>
              <GroupPolicyCapabilities
                value={permissions}
                onChange={(value) => {
                  setPermissions(value);
                  setConfirming(false);
                }}
              />
              <p>
                Preview: {policy.corporate_group} → {role};{" "}
                {policy.is_active ? "active" : "inactive"}.
              </p>
              {!confirming ? (
                <button
                  type="button"
                  disabled={reason.trim().length < 3}
                  onClick={() => setConfirming(true)}
                >
                  Review change
                </button>
              ) : (
                <>
                  <button
                    className="primary-button"
                    type="button"
                    onClick={() => commit()}
                  >
                    Confirm and apply
                  </button>
                  <button
                    type="button"
                    onClick={() => commit(!policy.is_active)}
                  >
                    Confirm and {policy.is_active ? "deactivate" : "activate"}
                  </button>
                </>
              )}
              <button type="button" onClick={() => setEditing(false)}>
                Close
              </button>
              {error ? <p className="inline-error">{error.message}</p> : null}
            </div>
          </td>
        </tr>
      ) : null}
      {removing ? (
        <tr>
          <td colSpan={5}>
            <div
              className="lifecycle-panel"
              role="dialog"
              aria-label={`Remove ${policy.corporate_group} policy`}
            >
              <h3>Remove policy</h3>
              <p>
                <strong>{policy.corporate_group}</strong> → {policy.role_code}.
                This deactivates the policy, stops it granting access, preserves
                audit history, and may invalidate affected active sessions.
              </p>
              <label>
                Reason
                <input
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                />
              </label>
              <div className="editor-actions">
                <button
                  className="secondary-button"
                  type="button"
                  onClick={() => setRemoving(false)}
                >
                  Cancel
                </button>
                <button
                  className="destructive-button"
                  type="button"
                  disabled={reason.trim().length < 3}
                  onClick={remove}
                >
                  Confirm remove policy
                </button>
              </div>
              {error ? <p className="inline-error">{error.message}</p> : null}
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}

export function SessionRevokeEditor({
  session,
  onDone,
}: {
  session: AdminRecord;
  onDone: (auditEventId: string) => void;
}) {
  const reference = String(session.session_reference);
  const [reason, setReason] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [audit, setAudit] = useState<string>();
  const [error, setError] = useState<AdminApiError>();
  const revoke = () =>
    adminApi
      .revokeSession(reference, { reason, confirmation })
      .then((value) => {
        setAudit(value.audit_event_id);
        onDone(value.audit_event_id);
      })
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Session revocation failed.", 0),
        ),
      );
  return (
    <div className="lifecycle-panel">
      <strong>{reference}</strong>
      <span>
        {" "}
        Issued {String(session.issued_at ?? "unknown")};{" "}
        {session.revoked_at ? "revoked" : "active"}
      </span>
      {!session.revoked_at ? (
        <>
          <label>
            Revocation reason
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          <label>
            Type <code>REVOKE {reference}</code>
            <input
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={
              reason.trim().length < 3 || confirmation !== `REVOKE ${reference}`
            }
            onClick={revoke}
          >
            Revoke session
          </button>
        </>
      ) : null}
      {error ? <p className="inline-error">{error.message}</p> : null}
      <AuditSuccess eventId={audit} />
    </div>
  );
}
export function MappingEditor({
  mapping,
  onDone,
}: {
  mapping: AdminMapping;
  onDone: (auditEventId: string) => void;
}) {
  const [role, setRole] = useState(mapping.role_code);
  const [reason, setReason] = useState("");
  const [audit, setAudit] = useState<string>();
  const [error, setError] = useState<AdminApiError>();
  const save = () =>
    adminApi
      .updateMapping(mapping.identity, {
        role_code: role,
        expected_row_version: mapping.row_version,
        reason,
      })
      .then((result) => {
        setAudit(result.audit_event_id);
        onDone(result.audit_event_id);
      })
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Mapping update failed.", 0),
        ),
      );
  return (
    <section className="editor-card">
      <h2>{mapping.identity}</h2>
      <p>Environment: {mapping.environment}</p>
      <label>
        Application role
        <select value={role} onChange={(event) => setRole(event.target.value)}>
          {[
            "ADMIN_AUDITOR",
            "ADMIN_DATA_MANAGER",
            "ADMIN_SETTINGS_MANAGER",
            "ADMIN_ACCESS_MANAGER",
            "ADMINISTRATOR",
          ].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </select>
      </label>
      <label>
        Reason
        <input
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <button
        className="primary-button"
        type="button"
        disabled={reason.trim().length < 3}
        onClick={save}
      >
        Save local role mapping
      </button>
      {error ? <p className="inline-error">{error.message}</p> : null}
      <AuditSuccess eventId={audit} />
    </section>
  );
}

function downloadEvidence(result: { blob: Blob; filename: string }) {
  const href = URL.createObjectURL(result.blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = result.filename;
  link.click();
  URL.revokeObjectURL(href);
}
function IntegrityEvidencePage() {
  const { ready, setReady } = useAdminSession();
  const [supportRequestId, setSupportRequestId] = useState("");
  const [scan, setScan] = useState<{
    operation_id: string;
    finding_count: number;
    findings: Array<Record<string, AuditValue>>;
    audit_event_id: string;
  }>();
  const latest = useRemote(
    (signal) => adminApi.latestIntegrity(signal),
    `latest-integrity:${ready}:${scan?.operation_id ?? "initial"}`,
  );
  const [error, setError] = useState<AdminApiError>();
  const run = () =>
    adminApi
      .integrityScan()
      .then(setScan)
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Integrity scan failed.", 0),
        ),
      );
  const evidence = (kind: "csv" | "json" | "support") => {
    const call =
      kind === "support"
        ? adminApi.supportBundle(
            supportRequestId.trim()
              ? ["health", "integrity", "release", "request"]
              : ["health", "integrity", "release"],
            supportRequestId.trim() || undefined,
          )
        : adminApi.auditExport(kind, {});
    call
      .then(downloadEvidence)
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Evidence generation failed.", 0),
        ),
      );
  };
  if (!ready) return <SessionGate onReady={() => setReady(true)} />;
  return (
    <>
      <PageTitle title="Integrity and support evidence">
        <p>
          Integrity scans are explicit, read-only, and never guess an automatic
          repair. Exports are generated server-side from authorized data and
          redacted again at serialization.
        </p>
      </PageTitle>
      <section className="editor-card">
        <h2>Integrity scan</h2>
        {latest.state === "ready" ? (
          <div className="integrity-summary">
            <strong>Integrity status: {latest.value.status}</strong>
            <span>{latest.value.by_severity?.PASS ?? 0} checks passed</span>
            <span>{latest.value.by_severity?.WARNING ?? 0} warnings</span>
            <span>{latest.value.by_severity?.ERROR ?? 0} errors</span>
            <small>
              {latest.value.completed_at
                ? `Last run ${formatTime(latest.value.completed_at)}`
                : "No completed scan is reported."}
            </small>
          </div>
        ) : null}
        <button className="primary-button" type="button" onClick={run}>
          Run integrity scan
        </button>
        {scan ? (
          <>
            <p className="success-note">
              Completed {scan.finding_count} controlled finding(s).{" "}
              <Link
                to={`/admin/audit/events/${encodeURIComponent(scan.audit_event_id)}`}
              >
                View Audit Event
              </Link>
            </p>
            {scan.findings.map((finding) => (
              <article
                className="lifecycle-panel"
                key={String(finding.finding_id)}
              >
                <strong>
                  {String(finding.severity)} · {String(finding.category)}
                </strong>
                <p>{String(finding.explanation)}</p>
                <p className="state-note">
                  {String(finding.recommended_next_step)}
                </p>
              </article>
            ))}
          </>
        ) : null}
      </section>
      <section className="editor-card">
        <h2>Authorized evidence exports</h2>
        <label>
          Request ID for safe support context (optional)
          <input
            value={supportRequestId}
            onChange={(event) => setSupportRequestId(event.target.value)}
            maxLength={64}
            autoComplete="off"
          />
        </label>
        <div className="editor-actions">
          <button type="button" onClick={() => evidence("csv")}>
            Download Audit CSV
          </button>
          <button type="button" onClick={() => evidence("json")}>
            Download Audit JSON
          </button>
          <button type="button" onClick={() => evidence("support")}>
            Download safe support evidence
          </button>
        </div>
        <p className="state-note">
          No secret, cookie, token, credential, path, raw log, or environment
          dump is included. When supplied, the request ID retrieves only its
          matching safe Audit context; it is not a log-search capability.
        </p>
      </section>
      {error ? <p className="inline-error">{error.message}</p> : null}
    </>
  );
}

function DangerZonePage() {
  const { ready, setReady } = useAdminSession();
  const corporate = useRemote(
    () => adminApi.corporateStatus(),
    "corporate-auth-status",
  );
  const [namespace, setNamespace] = useState("phase4-");
  const [stepUpSecret, setStepUpSecret] = useState("");
  const [steppedUp, setSteppedUp] = useState<string>();
  const [preview, setPreview] = useState<{
    preview_reference: string;
    typed_confirmation: string;
    target: { fixture_namespace: string; target_count: number };
    preconditions: Array<{ name: string; state: string; detail: string }>;
  }>();
  const [confirmation, setConfirmation] = useState("");
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<{
    status: string;
    audit_event_id: string;
    message?: string;
    removed_count?: number;
  }>();
  const [error, setError] = useState<AdminApiError>();
  const corporateEnabled =
    corporate.state === "ready" && corporate.value.provider === "kerberos_form";
  const stepUp = () =>
    adminApi
      .dangerStepUp(
        corporateEnabled
          ? { password: stepUpSecret }
          : { rehearsal_step_up_secret: stepUpSecret },
      )
      .then((value) => {
        setSteppedUp(value.expires_at);
        setStepUpSecret("");
      })
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Step-up failed.", 0),
        ),
      );
  const makePreview = () =>
    adminApi
      .dangerPreview(namespace)
      .then((value) => {
        setPreview(value);
        setConfirmation("");
      })
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Danger preview failed.", 0),
        ),
      );
  const commit = () =>
    preview &&
    adminApi
      .dangerCommit({
        preview_reference: preview.preview_reference,
        confirmation,
        reason,
      })
      .then(setResult)
      .catch((value: unknown) =>
        setError(
          value instanceof AdminApiError
            ? value
            : new AdminApiError("Danger operation failed.", 0),
        ),
      );
  if (!ready) return <SessionGate onReady={() => setReady(true)} />;
  if (corporate.state === "loading") return <LoadingState />;
  if (corporate.state === "error")
    return <ErrorState error={corporate.error} />;
  return (
    <>
      <PageTitle title="Danger Zone">
        <p>
          Test-rehearsal controls are isolated from routine Administration.
          Production factory reset, purge, overwrite restore, destructive
          repair, and security-mapping reset are unavailable pending
          project-owner, IT, and Quality decisions.
        </p>
      </PageTitle>
      <section className="editor-card">
        <h2>Test-only fixture recovery rehearsal</h2>
        <p>
          This bounded high-risk operation can remove only non-authoritative
          Phase 4 acceptance fixtures in <code>eoat_atlas_test</code>. It cannot
          target business data, development, or production databases.
        </p>
        <label>
          Phase 4 fixture namespace
          <input
            value={namespace}
            onChange={(event) => setNamespace(event.target.value)}
            autoComplete="off"
          />
        </label>
        <label>
          {corporateEnabled
            ? "Re-enter corporate password for fresh authentication"
            : "Development/test step-up secret"}
          <input
            type="password"
            value={stepUpSecret}
            onChange={(event) => setStepUpSecret(event.target.value)}
            autoComplete={corporateEnabled ? "current-password" : "off"}
          />
        </label>
        <button
          type="button"
          disabled={stepUpSecret.length < (corporateEnabled ? 1 : 16)}
          onClick={stepUp}
        >
          {corporateEnabled
            ? "Verify fresh corporate authentication"
            : "Verify fresh rehearsal step-up"}
        </button>
        {steppedUp ? (
          <p className="success-note">
            Step-up proof is server controlled and expires at{" "}
            {formatTime(steppedUp)}.
          </p>
        ) : null}
        <button className="primary-button" type="button" onClick={makePreview}>
          Preview exact test fixture impact
        </button>
        {preview ? (
          <section className="preview-panel">
            <h3>Server preview</h3>
            <p>
              Target: <code>{preview.target.fixture_namespace}</code> ·{" "}
              {preview.target.target_count} fixture record(s).
            </p>
            <ul>
              {preview.preconditions.map((item) => (
                <li key={item.name}>
                  <strong>{item.state}</strong> {item.name}: {item.detail}
                </li>
              ))}
            </ul>
            <p>
              To commit, type <code>{preview.typed_confirmation}</code>; provide
              an operational reason. The default focus remains the text field,
              never the destructive action.
            </p>
            <label>
              Typed confirmation
              <input
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
                autoComplete="off"
                autoFocus
              />
            </label>
            <label>
              Reason
              <input
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </label>
            <button
              className="danger-button"
              type="button"
              disabled={
                confirmation !== preview.typed_confirmation ||
                reason.trim().length < 3
              }
              onClick={commit}
            >
              Execute test-only fixture recovery
            </button>
          </section>
        ) : null}
        {result ? (
          <p
            className={
              result.status === "COMPLETED" ? "success-note" : "inline-error"
            }
          >
            {result.status}
            {result.message
              ? `: ${result.message}`
              : result.removed_count != null
                ? `: removed ${result.removed_count} fixture record(s).`
                : ""}{" "}
            <Link
              to={`/admin/audit/events/${encodeURIComponent(result.audit_event_id)}`}
            >
              View Audit Event
            </Link>
          </p>
        ) : null}
        {error ? <p className="inline-error">{error.message}</p> : null}
      </section>
    </>
  );
}

function NotFound() {
  return (
    <section className="state-panel">
      <h1>Administrator page not found</h1>
      <p>
        The route is not part of the implemented read-only Administration
        surface.
      </p>
      <Link to="/admin">Return to overview</Link>
    </section>
  );
}

export function AdminApp() {
  const [ready, setReady] = useState(false);
  const showTestControls =
    import.meta.env.DEV ||
    import.meta.env.VITE_EOAT_ALLOW_TEST_CONTROLS === "true";
  return (
    <AdminSessionContext.Provider value={{ ready, setReady }}>
      <AdminLayout>
        <Routes>
          <Route index element={<OverviewPage />} />
          <Route path="audit" element={<AuditPage />} />
          <Route path="audit/events/:eventId" element={<EventDetailPage />} />
          <Route path="data" element={<DataPage />} />
          <Route path="data/eoats" element={<DataPage initialKind="eoats" />} />
          <Route
            path="data/machines"
            element={<DataPage initialKind="machines" />}
          />
          <Route path="data/tools" element={<DataPage initialKind="tools" />} />
          <Route path="data/relationships" element={<RelationshipsPage />} />
          <Route path="relationships" element={<RelationshipsPage />} />
          <Route path="data/documents" element={<DocumentsPage />} />
          <Route path="documents" element={<DocumentsPage />} />
          <Route path="data/photos" element={<PhotosPage />} />
          <Route
            path="data/photos/:documentUuid"
            element={<PhotoDetailPage />}
          />
          <Route path="photos" element={<PhotosPage />} />
          <Route path="photos/:documentUuid" element={<PhotoDetailPage />} />
          <Route path="data/bulk" element={<BulkStatusPage />} />
          <Route path="bulk" element={<BulkStatusPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="users" element={<UsersPage />} />
          <Route path="users/:userId" element={<UserDetailPage />} />
          <Route path="group-policies" element={<GroupPolicyPage />} />
          <Route path="system" element={<SystemPage />} />
          <Route path="integrity" element={<IntegrityEvidencePage />} />
          {showTestControls ? (
            <Route path="danger-zone" element={<DangerZonePage />} />
          ) : null}
          <Route path="*" element={<NotFound />} />
        </Routes>
      </AdminLayout>
    </AdminSessionContext.Provider>
  );
}
