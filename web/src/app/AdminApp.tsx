import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Route, Routes, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { adminApi, AdminApiError, type AdminDiagnostics, type AdminOverview, type AuditCatalog, type AuditEvent, type AuditList } from "../api/admin";
import { AuditDiff } from "../components/AuditDiff";

type Remote<T> = { state: "loading" } | { state: "error"; error: AdminApiError } | { state: "ready"; value: T };

function useRemote<T>(load: (signal: AbortSignal) => Promise<T>, key: string): Remote<T> {
  const [state, setState] = useState<Remote<T>>({ state: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    setState({ state: "loading" });
    load(controller.signal)
      .then((value) => { if (!controller.signal.aborted) setState({ state: "ready", value }); })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setState({ state: "error", error: error instanceof AdminApiError ? error : new AdminApiError("The Administrator request failed.", 0) });
        }
      });
    return () => controller.abort();
  // `load` is intentionally represented by `key`: callers supply a stable
  // request identity so a render-local closure cannot cause a fetch loop.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return state;
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  }).format(new Date(value));
}

function copy(value: string) {
  void navigator.clipboard?.writeText(value);
}

function ErrorState({ error }: { error: AdminApiError }) {
  if (error.status === 401 || error.status === 403) {
    return <section className="state-panel denied" aria-labelledby="denied-title"><h1 id="denied-title">Administrator access required</h1><p>Administrator data was not returned. Sign in through an approved Administrator identity, then try again.</p>{error.requestId ? <p>Request ID: <code>{error.requestId}</code></p> : null}</section>;
  }
  if (error.status === 404) {
    return <section className="state-panel error" aria-labelledby="not-found-title"><h1 id="not-found-title">Audit event not found</h1><p>The requested audit event is not available to this Administrator identity.</p>{error.requestId ? <p>Request ID: <code>{error.requestId}</code></p> : null}</section>;
  }
  return <section className="state-panel error" aria-labelledby="error-title"><h1 id="error-title">Administrator data could not load</h1><p>{error.message}</p>{error.requestId ? <p>Request ID: <code>{error.requestId}</code></p> : null}</section>;
}

function LoadingState() { return <section className="state-panel" aria-live="polite"><h1>Loading Administrator data</h1><p>The current server response is being retrieved.</p></section>; }

function AdminLayout({ children }: { children: React.ReactNode }) {
  return <div className="admin-layout"><a className="skip-link" href="#admin-content">Skip to main content</a><aside className="admin-sidebar"><div className="admin-brand"><span>EOAT Atlas</span><strong>Administration</strong></div><nav aria-label="Administration"><NavLink end to="/admin">Overview</NavLink><NavLink to="/admin/audit">Audit ledger</NavLink><NavLink to="/admin/system">System</NavLink><NavLink to="/admin/diagnostics">Diagnostics</NavLink></nav><a className="return-link" href="/">← Return to EOAT Atlas</a></aside><main id="admin-content" className="admin-main" tabIndex={-1}>{children}</main></div>;
}

function PageTitle({ title, children }: { title: string; children?: React.ReactNode }) {
  return <header className="page-heading"><p className="eyebrow">Administration</p><h1>{title}</h1>{children}</header>;
}

function EventLink({ event }: { event: AuditEvent }) { return <Link to={`/admin/audit/events/${encodeURIComponent(event.event_id)}`}>{event.action} · {event.entity.display_id ?? event.entity.id}</Link>; }

function OverviewPage() {
  const remote = useRemote<AdminOverview>((signal) => adminApi.overview(signal), "overview");
  if (remote.state === "loading") return <LoadingState />;
  if (remote.state === "error") return <ErrorState error={remote.error} />;
  const { value } = remote;
  const metrics = [
    ["Events today (UTC)", value.metrics.events_today], ["Events, last 24 hours", value.metrics.events_last_24_hours],
    ["Successful", value.metrics.successful_events_last_24_hours], ["Failed", value.metrics.failed_events_last_24_hours],
    ["Denied", value.metrics.denied_events_last_24_hours], ["Security", value.metrics.security_events_last_24_hours],
    ["Unique actors", value.metrics.unique_actors_last_24_hours],
  ];
  return <><PageTitle title="Administrative overview"><p>Server-observed {formatTime(value.observation_time_utc)}. Audit activity uses authoritative UTC event timestamps.</p></PageTitle><section className="card-grid status-grid" aria-label="System identity"><StatusCard label="API" value={value.api_status} detail={`Contract ${value.api_version}`} /><StatusCard label="Database" value={value.database_status} detail={`Schema ${value.schema_revision ?? "unknown"}`} /><StatusCard label="Audit" value={value.audit_status} detail={`Schema v${value.audit_schema_version}`} /><StatusCard label="Writes" value={value.writes_enabled ? "enabled" : "controlled / disabled"} detail={`Environment ${value.environment}`} /></section><section aria-labelledby="activity-title"><div className="section-heading"><h2 id="activity-title">Audit activity</h2><Link to="/admin/audit">Open full Audit Ledger</Link></div><div className="card-grid metrics-grid">{metrics.map(([label, metric]) => <article className="metric-card" key={String(label)}><span>{label}</span><strong>{metric}</strong></article>)}</div></section><section aria-labelledby="recent-title"><div className="section-heading"><h2 id="recent-title">Recent activity</h2><Link to="/admin/audit">Investigate all events</Link></div>{value.recent_events.length ? <ol className="recent-list">{value.recent_events.map((event) => <li key={event.event_id}><time dateTime={event.occurred_at_utc}>{formatTime(event.occurred_at_utc)}</time><EventLink event={event} /><span>{event.actor.display_name ?? event.actor.type} · {event.result}</span></li>)}</ol> : <p className="state-note">No audit events have been recorded.</p>}</section><section className="shortcuts" aria-label="Administrator shortcuts"><Link to="/admin/audit">Full Audit Ledger</Link><Link to="/admin/system">System status</Link><Link to="/admin/diagnostics">Diagnostics</Link></section></>;
}

function StatusCard({ label, value, detail }: { label: string; value: string; detail: string }) { return <article className="status-card"><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>; }

const filterNames = ["start", "end", "actor", "action", "action_category", "entity_type", "entity_id", "result", "source", "request_id", "correlation_id", "search", "current_user_changes", "security_events_only", "administrative_events_only", "page", "page_size"];

function validAuditParams(raw: URLSearchParams) {
  const params = new URLSearchParams();
  filterNames.forEach((name) => {
    const value = raw.get(name);
    if (value && value.length <= 255) params.set(name, value);
  });
  const page = Number(params.get("page") ?? "1");
  if (!Number.isInteger(page) || page < 1) params.set("page", "1");
  const size = Number(params.get("page_size") ?? "50");
  if (!Number.isInteger(size) || size < 1 || size > 250) params.set("page_size", "50");
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
  const catalog = useRemote<AuditCatalog>((signal) => adminApi.catalog(signal), "catalog");
  const ledger = useRemote<AuditList>((signal) => adminApi.audit(params, signal), params.toString());
  const update = (name: string, value: string) => setSearchParams(setFilter(params, name, value));
  if (catalog.state === "error") return <ErrorState error={catalog.error} />;
  if (ledger.state === "error") return <ErrorState error={ledger.error} />;
  return <><PageTitle title="Global Audit Ledger"><p>Authoritative immutable evidence. Filters, sorting, and pagination are executed by the server.</p></PageTitle><AuditFilters params={params} update={update} catalog={catalog.state === "ready" ? catalog.value : undefined} /><section aria-live="polite">{ledger.state === "loading" ? <LoadingState /> : <AuditTable result={ledger.value} params={params} setSearchParams={setSearchParams} />}</section></>;
}

function AuditFilters({ params, update, catalog }: { params: URLSearchParams; update: (name: string, value: string) => void; catalog?: AuditCatalog }) {
  const today = new Date();
  today.setUTCHours(0, 0, 0, 0);
  const toggle = (name: "current_user_changes" | "security_events_only" | "administrative_events_only") => update(name, params.get(name) === "true" ? "" : "true");
  return <section className="filters" aria-labelledby="filter-title"><div className="section-heading"><h2 id="filter-title">Investigate events</h2><button type="button" className="link-button" onClick={() => update("search", "")}>Clear search</button></div><div className="filter-grid"><label>Search safe evidence<input value={params.get("search") ?? ""} onChange={(e) => update("search", e.target.value)} placeholder="Event, actor, request, or entity" /></label><label>Start (UTC)<input type="datetime-local" value={params.get("start")?.slice(0, 16) ?? ""} onChange={(e) => update("start", e.target.value ? `${e.target.value}:00Z` : "")} /></label><label>End (UTC)<input type="datetime-local" value={params.get("end")?.slice(0, 16) ?? ""} onChange={(e) => update("end", e.target.value ? `${e.target.value}:00Z` : "")} /></label><Select label="Action" value={params.get("action") ?? ""} values={catalog?.actions} onChange={(value) => update("action", value)} /><Select label="Category" value={params.get("action_category") ?? ""} values={catalog?.action_categories} onChange={(value) => update("action_category", value)} /><Select label="Entity type" value={params.get("entity_type") ?? ""} values={catalog?.entity_types} onChange={(value) => update("entity_type", value)} /><Select label="Result" value={params.get("result") ?? ""} values={catalog?.results} onChange={(value) => update("result", value)} /><Select label="Source" value={params.get("source") ?? ""} values={catalog?.sources} onChange={(value) => update("source", value)} /><label>Actor<input value={params.get("actor") ?? ""} onChange={(e) => update("actor", e.target.value)} /></label><label>Entity ID<input value={params.get("entity_id") ?? ""} onChange={(e) => update("entity_id", e.target.value)} /></label><label>Request ID<input value={params.get("request_id") ?? ""} onChange={(e) => update("request_id", e.target.value)} /></label><label>Correlation ID<input value={params.get("correlation_id") ?? ""} onChange={(e) => update("correlation_id", e.target.value)} /></label><Select label="Page size" value={params.get("page_size") ?? "50"} values={["25", "50", "100", "250"]} onChange={(value) => update("page_size", value || "50")} /></div><div className="preset-row"><button type="button" onClick={() => update("start", today.toISOString())}>Today (UTC)</button><button type="button" onClick={() => update("start", new Date(Date.now() - 3600_000).toISOString())}>Last hour</button><button type="button" onClick={() => update("start", new Date(Date.now() - 86_400_000).toISOString())}>Last 24 hours</button><button type="button" onClick={() => update("start", new Date(Date.now() - 7 * 86_400_000).toISOString())}>Last 7 days</button><button type="button" onClick={() => update("result", "FAILURE")}>Failed</button><button type="button" onClick={() => update("result", "DENIED")}>Denied</button><button type="button" aria-pressed={params.get("current_user_changes") === "true"} onClick={() => toggle("current_user_changes")}>My activity</button><button type="button" aria-pressed={params.get("security_events_only") === "true"} onClick={() => toggle("security_events_only")}>Security / authentication</button><button type="button" aria-pressed={params.get("administrative_events_only") === "true"} onClick={() => toggle("administrative_events_only")}>Administrative operations</button></div></section>;
}

function Select({ label, value, values, onChange }: { label: string; value: string; values?: string[]; onChange: (value: string) => void }) { return <label>{label}<select value={value} onChange={(e) => onChange(e.target.value)}>{label === "Page size" ? null : <option value="">All</option>}{(values ?? []).map((option) => <option key={option} value={option}>{option.replaceAll("_", " ")}</option>)}</select></label>; }

function AuditTable({ result, params, setSearchParams }: { result: AuditList; params: URLSearchParams; setSearchParams: (next: URLSearchParams) => void }) {
  const pages = Math.max(1, Math.ceil(result.total / result.page_size));
  const goTo = (page: number) => { const next = new URLSearchParams(params); next.set("page", String(page)); setSearchParams(next); };
  return <><div className="table-summary"><span>{result.total} matching event{result.total === 1 ? "" : "s"}</span><span>Order: persisted time, then persisted sequence</span></div>{result.items.length ? <div className="audit-table-wrap"><table className="audit-table"><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Entity</th><th>Changed fields</th><th>Result</th><th>Source</th></tr></thead><tbody>{result.items.map((event) => <tr key={event.event_id}><td data-label="Time"><time dateTime={event.occurred_at_utc}>{formatTime(event.occurred_at_utc)}</time></td><td data-label="Actor">{event.actor.display_name ?? event.actor.type}</td><td data-label="Action"><EventLink event={event} /></td><td data-label="Entity">{event.entity.type} · {event.entity.display_id ?? event.entity.id}</td><td data-label="Changed fields">{event.changed_fields.join(", ") || "—"}</td><td data-label="Result"><span className={`result result-${event.result.toLowerCase()}`}>{event.result}</span></td><td data-label="Source">{event.source_client}</td></tr>)}</tbody></table></div> : <p className="state-note">No audit events match these filters.</p>}<nav className="pagination" aria-label="Audit pagination"><button type="button" disabled={result.page <= 1} onClick={() => goTo(result.page - 1)}>Previous</button><span>Page {result.page} of {pages}</span><button type="button" disabled={result.page >= pages} onClick={() => goTo(result.page + 1)}>Next</button></nav></>;
}

function EventDetailPage() {
  const { eventId = "" } = useParams();
  const navigate = useNavigate();
  const remote = useRemote<AuditEvent>((signal) => adminApi.event(eventId, signal), `event:${eventId}`);
  if (remote.state === "loading") return <LoadingState />;
  if (remote.state === "error") return <ErrorState error={remote.error} />;
  const event = remote.value;
  const entityPath = entityLink(event);
  return <><PageTitle title="Audit event detail"><button type="button" className="link-button" onClick={() => navigate(-1)}>← Back to investigation</button></PageTitle><section className="detail-summary"><Detail label="Event ID" value={event.event_id} copyable /><Detail label="Occurred" value={`${formatTime(event.occurred_at_utc)} (UTC: ${event.occurred_at_utc})`} /><Detail label="Action" value={`${event.action} · ${event.action_category}`} /><Detail label="Result" value={event.result} /><Detail label="Source" value={event.source_client} /></section><section className="detail-grid"><article><h2>Actor</h2><Detail label="Display" value={event.actor.display_name ?? "Not recorded"} /><Detail label="Type" value={event.actor.type} /><Detail label="Stable ID" value={event.actor.id ?? "Not recorded"} /><Detail label="Directory identity" value={event.actor.directory_name ?? "Not recorded"} /></article><article><h2>Entity</h2><Detail label="Type" value={event.entity.type} /><Detail label="Stable ID" value={event.entity.id} /><Detail label="Display ID" value={event.entity.display_id ?? "Not recorded"} />{entityPath ? <a href={entityPath}>Open normal profile</a> : <p className="state-note">No canonical normal-profile link is available for this entity type.</p>}</article></section><section><h2>Structured change evidence</h2><AuditDiff changedFields={event.changed_fields} before={event.before} after={event.after} /></section>{event.reason_or_note ? <section><h2>Reason or note</h2><p>{event.reason_or_note}</p></section> : null}<section className="detail-grid"><article><h2>Request context</h2><Detail label="Request ID" value={event.request_id ?? "Not recorded"} copyable link={event.request_id ? `/admin/audit?request_id=${encodeURIComponent(event.request_id)}` : undefined} /><Detail label="Correlation ID" value={event.correlation_id ?? "Not recorded"} copyable link={event.correlation_id ? `/admin/audit?correlation_id=${encodeURIComponent(event.correlation_id)}` : undefined} /><Detail label="Transaction ID" value={event.transaction_id ?? "Not recorded"} /><Detail label="Operation" value={event.operation ?? "Not recorded"} /></article><article><h2>Related activity</h2>{event.correlation_id ? <RelatedEvents correlationId={event.correlation_id} currentEventId={event.event_id} /> : <p className="state-note">This event has no recorded correlation ID.</p>}</article></section></>;
}

function RelatedEvents({ correlationId, currentEventId }: { correlationId: string; currentEventId: string }) {
  const params = useMemo(() => new URLSearchParams({ correlation_id: correlationId, page_size: "10" }), [correlationId]);
  const remote = useRemote<AuditList>((signal) => adminApi.audit(params, signal), `related:${correlationId}`);
  const filtered = remote.state === "ready" ? remote.value.items.filter((item) => item.event_id !== currentEventId) : [];
  return <>{remote.state === "loading" ? <p className="state-note">Loading correlated events…</p> : null}{remote.state === "error" ? <p className="state-note">Related events could not load. Request ID: {remote.error.requestId ?? "not available"}</p> : null}{remote.state === "ready" && filtered.length ? <ol className="related-list">{filtered.map((item) => <li key={item.event_id}><EventLink event={item} /><span>{formatTime(item.occurred_at_utc)} · {item.result}</span></li>)}</ol> : null}{remote.state === "ready" && !filtered.length ? <p className="state-note">No other events share this correlation ID.</p> : null}<Link to={`/admin/audit?correlation_id=${encodeURIComponent(correlationId)}`}>View all events with this correlation ID</Link></>;
}

function entityLink(event: AuditEvent) { const type = event.entity.type.toLowerCase(); if (type === "eoat") return `/eoats/${encodeURIComponent(event.entity.id)}`; if (type === "machine") return `/machines/${encodeURIComponent(event.entity.id)}`; if (type === "tool") return `/tools/${encodeURIComponent(event.entity.id)}`; return undefined; }
function Detail({ label, value, copyable = false, link }: { label: string; value: string; copyable?: boolean; link?: string }) { return <dl className="detail"><dt>{label}</dt><dd>{link ? <Link to={link}>{value}</Link> : <code>{value}</code>}{copyable && value !== "Not recorded" ? <button type="button" className="link-button" onClick={() => copy(value)}>Copy</button> : null}</dd></dl>; }

function DiagnosticsPage({ diagnostics = false }: { diagnostics?: boolean }) { const remote = useRemote<AdminDiagnostics>((signal) => diagnostics ? adminApi.diagnostics(signal) : adminApi.system(signal), diagnostics ? "diagnostics" : "system"); if (remote.state === "loading") return <LoadingState />; if (remote.state === "error") return <ErrorState error={remote.error} />; const value = remote.value; return <><PageTitle title={diagnostics ? "Diagnostics" : "System status"}><p>Safe read-only operational information observed at {formatTime(value.observation_time_utc)}.</p></PageTitle><section className="card-grid status-grid"><StatusCard label="API" value={value.api_status} detail="Server response" /><StatusCard label="Database" value={value.database_status} detail={`Schema ${value.schema_revision ?? "unknown"}`} /><StatusCard label="Audit" value={value.audit_status} detail={value.compatible ? "Schema compatible" : `Expected ${value.expected_schema_revision ?? "unknown"}`} /></section><p className="state-note">Diagnostics do not provide SQL, shell, filesystem, log-browsing, or mutation capabilities.</p></>; }

function NotFound() { return <section className="state-panel"><h1>Administrator page not found</h1><p>The route is not part of the implemented read-only Administration surface.</p><Link to="/admin">Return to overview</Link></section>; }

export function AdminApp() { return <AdminLayout><Routes><Route path="/admin" element={<OverviewPage />} /><Route path="/admin/audit" element={<AuditPage />} /><Route path="/admin/audit/events/:eventId" element={<EventDetailPage />} /><Route path="/admin/system" element={<DiagnosticsPage />} /><Route path="/admin/diagnostics" element={<DiagnosticsPage diagnostics />} /><Route path="*" element={<NotFound />} /></Routes></AdminLayout>; }
