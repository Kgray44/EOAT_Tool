export type AuditValue = string | number | boolean | null | AuditValue[] | { [key: string]: AuditValue };

export interface AuditEvent {
  event_id: string;
  occurred_at_utc: string;
  actor: { type: string; id?: string | null; display_name?: string | null; directory_name?: string | null };
  action: string;
  action_category: string;
  entity: { type: string; id: string; display_id?: string | null };
  changed_fields: string[];
  before?: Record<string, AuditValue> | null;
  after?: Record<string, AuditValue> | null;
  reason_or_note?: string | null;
  source_client: string;
  request_id?: string | null;
  correlation_id?: string | null;
  transaction_id?: string | null;
  operation?: string | null;
  result: string;
  metadata?: Record<string, AuditValue> | null;
  schema_version: number;
}

export interface AuditCatalog {
  actions: string[];
  action_categories: string[];
  entity_types: string[];
  results: string[];
  sources: string[];
}

export interface AuditList {
  items: AuditEvent[];
  page: number;
  page_size: number;
  total: number;
  sort: string;
}

export interface AdminOverview {
  api_version: string;
  schema_revision?: string | null;
  audit_schema_version: number;
  observation_time_utc: string;
  writes_enabled: boolean;
  environment: string;
  api_status: string;
  database_status: string;
  audit_status: string;
  metrics: Record<string, number>;
  recent_events: AuditEvent[];
}

export interface AdminDiagnostics {
  observation_time_utc: string;
  api_status: string;
  database_status: string;
  audit_status: string;
  schema_revision?: string | null;
  expected_schema_revision?: string | null;
  compatible: boolean;
}

export class AdminApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly requestId?: string,
    readonly code?: string,
  ) {
    super(message);
  }
}

const apiBase = import.meta.env.VITE_EOAT_API_BASE_URL ?? "";

function localRehearsalHeaders(): HeadersInit {
  // This optional value makes local development runnable.  The API treats it
  // only as an input to its server-owned, environment-gated rehearsal mapper.
  const identity = import.meta.env.VITE_EOAT_IDENTITY;
  return identity ? { "X-EOAT-Identity": identity } : {};
}

export async function adminFetch<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    credentials: "include",
    headers: { Accept: "application/json", ...localRehearsalHeaders() },
    signal,
  });
  const body = (await response.json().catch(() => null)) as
    | { message?: string; error_code?: string; request_id?: string }
    | null;
  if (!response.ok) {
    throw new AdminApiError(body?.message ?? "The Administrator request failed.", response.status, body?.request_id, body?.error_code);
  }
  return body as T;
}

export const adminApi = {
  catalog: (signal?: AbortSignal) => adminFetch<AuditCatalog>("/api/v1/admin/audit/catalog", signal),
  overview: (signal?: AbortSignal) => adminFetch<AdminOverview>("/api/v1/admin/overview", signal),
  system: (signal?: AbortSignal) => adminFetch<AdminDiagnostics>("/api/v1/admin/system", signal),
  diagnostics: (signal?: AbortSignal) => adminFetch<AdminDiagnostics>("/api/v1/admin/diagnostics", signal),
  audit: (params: URLSearchParams, signal?: AbortSignal) => adminFetch<AuditList>(`/api/v1/admin/audit/events?${params}`, signal),
  event: (eventId: string, signal?: AbortSignal) => adminFetch<AuditEvent>(`/api/v1/admin/audit/events/${encodeURIComponent(eventId)}`, signal),
};
