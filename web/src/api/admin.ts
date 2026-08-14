export type AuditValue =
  | string
  | number
  | boolean
  | null
  | AuditValue[]
  | { [key: string]: AuditValue };

export interface AuditEvent {
  event_id: string;
  occurred_at_utc: string;
  actor: {
    type: string;
    id?: string | null;
    display_name?: string | null;
    directory_name?: string | null;
  };
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
  checks: Array<{
    check_id: string;
    subsystem: string;
    state: string;
    severity?: string;
    read_only?: boolean;
    timeout_seconds?: number;
    safe_detail: string;
    remediation_hint: string;
    source: string;
    observed_at_utc: string;
    request_id?: string | null;
  }>;
  by_subsystem: Record<
    string,
    {
      check_id: string;
      subsystem: string;
      state: string;
      severity?: string;
      read_only?: boolean;
      timeout_seconds?: number;
      safe_detail: string;
      remediation_hint: string;
      source: string;
      observed_at_utc: string;
      request_id?: string | null;
    }
  >;
}

export interface AdminOperation {
  operation_id: string;
  operation_type: string;
  risk_class: string;
  status: string;
  target: Record<string, AuditValue>;
  correlation_id?: string | null;
  result: Record<string, AuditValue>;
  error_code?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export type AdminRecord = Record<string, AuditValue | undefined>;
export interface AdminMutationSuccess {
  record?: AdminRecord;
  audit_event_id: string;
  correlation_id: string;
  request_id: string;
  idempotent_replay?: boolean;
}
export interface AdminSession {
  session_reference: string;
  expires_at: string;
  csrf_token: string;
  actor: { display_name: string; role: string };
  environment: string;
}
export interface AdminSetting {
  key: string;
  value: AuditValue | null;
  secret_configured?: boolean | null;
  value_type: string;
  description?: string | null;
  row_version: number;
  restart_required: boolean;
}
export interface AdminMapping {
  identity: string;
  environment: string;
  role_code: string;
  row_version: number;
}

let csrfToken: string | undefined;
let rehearsalIdentity: string | undefined;

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

function cookieValue(name: string): string | undefined {
  const prefix = `${encodeURIComponent(name)}=`;
  return document.cookie
    .split(";")
    .map((value) => value.trim())
    .find((value) => value.startsWith(prefix))
    ?.slice(prefix.length);
}

function localRehearsalHeaders(): HeadersInit {
  // This optional value makes local development runnable.  The API treats it
  // only as an input to its server-owned, environment-gated rehearsal mapper.
  const identity = rehearsalIdentity ?? import.meta.env.VITE_EOAT_IDENTITY;
  return identity ? { "X-EOAT-Identity": identity } : {};
}

export async function adminFetch<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    credentials: "include",
    headers: { Accept: "application/json", ...localRehearsalHeaders() },
    signal,
  });
  const body = (await response.json().catch(() => null)) as {
    message?: string;
    error_code?: string;
    request_id?: string;
  } | null;
  if (!response.ok) {
    throw new AdminApiError(
      body?.message ?? "The Administrator request failed.",
      response.status,
      body?.request_id,
      body?.error_code,
    );
  }
  return body as T;
}

async function adminWrite<T>(
  path: string,
  payload: unknown,
  idempotencyKey = crypto.randomUUID(),
): Promise<T> {
  if (!csrfToken)
    throw new AdminApiError(
      "Start a development/test Administrator session before changing data.",
      401,
      undefined,
      "ADMIN_SESSION_REQUIRED",
    );
  const response = await fetch(`${apiBase}${path}`, {
    method: "PATCH",
    credentials: "include",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-EOAT-CSRF-Token": csrfToken,
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify(payload),
  });
  const body = (await response.json().catch(() => null)) as {
    message?: string;
    error_code?: string;
    request_id?: string;
  } | null;
  if (!response.ok)
    throw new AdminApiError(
      body?.message ?? "The governed Administrator change failed.",
      response.status,
      body?.request_id,
      body?.error_code,
    );
  return body as T;
}

async function adminPost<T>(
  path: string,
  payload: unknown,
  idempotencyKey = crypto.randomUUID(),
): Promise<T> {
  if (!csrfToken)
    throw new AdminApiError(
      "Start a development/test Administrator session before changing data.",
      401,
      undefined,
      "ADMIN_SESSION_REQUIRED",
    );
  const response = await fetch(`${apiBase}${path}`, {
    method: "POST",
    credentials: "include",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-EOAT-CSRF-Token": csrfToken,
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify(payload),
  });
  const body = (await response.json().catch(() => null)) as {
    message?: string;
    error_code?: string;
    request_id?: string;
  } | null;
  if (!response.ok)
    throw new AdminApiError(
      body?.message ?? "The governed Administrator change failed.",
      response.status,
      body?.request_id,
      body?.error_code,
    );
  return body as T;
}

async function adminDownload(
  path: string,
  payload: unknown,
): Promise<{ blob: Blob; filename: string; id?: string }> {
  if (!csrfToken)
    throw new AdminApiError(
      "Start a development/test Administrator session before generating evidence.",
      401,
      undefined,
      "ADMIN_SESSION_REQUIRED",
    );
  const response = await fetch(`${apiBase}${path}`, {
    method: "POST",
    credentials: "include",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-EOAT-CSRF-Token": csrfToken,
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      message?: string;
      error_code?: string;
      request_id?: string;
    } | null;
    throw new AdminApiError(
      body?.message ?? "Evidence generation failed.",
      response.status,
      body?.request_id,
      body?.error_code,
    );
  }
  const filename =
    response.headers
      .get("content-disposition")
      ?.match(/filename="([^"]+)"/)?.[1] ?? "EOAT_Atlas_evidence.json";
  return {
    blob: await response.blob(),
    filename,
    id:
      response.headers.get("X-EOAT-Export-Id") ??
      response.headers.get("X-EOAT-Support-Bundle-Id") ??
      undefined,
  };
}

export const adminApi = {
  corporateStatus: () =>
    adminFetch<{
      provider: string | null;
      status: "ready" | "degraded" | "unavailable" | "misconfigured" | "unknown";
      mapping_configured: boolean;
    }>("/api/v1/auth/status"),
  corporateLogin: async (username: string, password: string): Promise<void> => {
    const response = await fetch(`${apiBase}/api/v1/auth/kerberos-form/login`, {
      method: "POST",
      credentials: "include",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const body = (await response.json().catch(() => null)) as {
      message?: string;
      error_code?: string;
      request_id?: string;
    } | null;
    if (!response.ok)
      throw new AdminApiError(
        body?.message ?? "Corporate sign-in could not be verified.",
        response.status,
        body?.request_id,
        body?.error_code,
      );
    csrfToken = cookieValue("eoat_corporate_csrf");
    rehearsalIdentity = undefined;
    if (!csrfToken)
      throw new AdminApiError(
        "Corporate sign-in did not establish a CSRF proof.",
        503,
        undefined,
        "CORPORATE_CSRF_UNAVAILABLE",
      );
  },
  catalog: (signal?: AbortSignal) =>
    adminFetch<AuditCatalog>("/api/v1/admin/audit/catalog", signal),
  overview: (signal?: AbortSignal) =>
    adminFetch<AdminOverview>("/api/v1/admin/overview", signal),
  system: (signal?: AbortSignal) =>
    adminFetch<AdminDiagnostics>("/api/v1/admin/system", signal),
  diagnostics: (signal?: AbortSignal) =>
    adminFetch<AdminDiagnostics>("/api/v1/admin/diagnostics", signal),
  audit: (params: URLSearchParams, signal?: AbortSignal) =>
    adminFetch<AuditList>(`/api/v1/admin/audit/events?${params}`, signal),
  event: (eventId: string, signal?: AbortSignal) =>
    adminFetch<AuditEvent>(
      `/api/v1/admin/audit/events/${encodeURIComponent(eventId)}`,
      signal,
    ),
  startRehearsal: async (
    identity: string,
    rehearsalSecret: string,
  ): Promise<AdminSession> => {
    const response = await fetch(`${apiBase}/api/v1/admin/session/rehearsal`, {
      method: "POST",
      credentials: "include",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ identity, rehearsal_secret: rehearsalSecret }),
    });
    const body = (await response.json().catch(() => null)) as AdminSession & {
      message?: string;
      error_code?: string;
      request_id?: string;
    };
    if (!response.ok)
      throw new AdminApiError(
        body?.message ?? "The development/test session could not start.",
        response.status,
        body?.request_id,
        body?.error_code,
      );
    csrfToken = body.csrf_token;
    rehearsalIdentity = identity;
    return body;
  },
  assets: (
    kind: "eoats" | "machines" | "tools",
    search = "",
    includeArchived = false,
  ) =>
    adminFetch<{ items: AdminRecord[] }>(
      `/api/v1/admin/data/${kind}?search=${encodeURIComponent(search)}${includeArchived ? "&include_archived=true" : ""}`,
    ),
  lookup: (lookupType: string) =>
    adminFetch<Array<{ code: string; display_name: string }>>(
      `/api/v1/lookups/${encodeURIComponent(lookupType)}`,
    ),
  previewAsset: (
    kind: string,
    identifier: string,
    payload: Record<string, AuditValue>,
  ) =>
    adminPost<{
      changed_fields: string[];
      before: Record<string, AuditValue>;
      after: Record<string, AuditValue>;
    }>(
      `/api/v1/admin/data/${kind}/${encodeURIComponent(identifier)}/preview`,
      payload,
    ),
  updateAsset: (
    kind: string,
    identifier: string,
    payload: Record<string, AuditValue>,
    correction = false,
  ) =>
    adminWrite<AdminMutationSuccess>(
      `/api/v1/admin/data/${kind}/${encodeURIComponent(identifier)}${correction ? "/correction" : ""}`,
      payload,
    ),
  lifecycleAsset: (
    kind: string,
    identifier: string,
    action: "archive" | "restore",
    payload: Record<string, AuditValue>,
  ) =>
    adminPost<AdminMutationSuccess>(
      `/api/v1/admin/data/${kind}/${encodeURIComponent(identifier)}/${action}`,
      payload,
    ),
  documents: (search = "") =>
    adminFetch<{ items: AdminRecord[] }>(
      `/api/v1/admin/documents?search=${encodeURIComponent(search)}`,
    ),
  updateDocument: (documentId: number, payload: Record<string, AuditValue>) =>
    adminWrite<AdminMutationSuccess>(
      `/api/v1/admin/documents/${documentId}`,
      payload,
    ),
  archiveDocument: (documentId: number, payload: Record<string, AuditValue>) =>
    adminPost<AdminMutationSuccess>(
      `/api/v1/admin/documents/${documentId}/archive`,
      payload,
    ),
  photos: () =>
    adminFetch<{
      items: Array<{
        photo: AdminRecord;
        document: AdminRecord;
        row_version: number;
      }>;
    }>("/api/v1/admin/photos"),
  updatePhoto: (photoId: number, payload: Record<string, AuditValue>) =>
    adminWrite<AdminMutationSuccess>(
      `/api/v1/admin/photos/${photoId}`,
      payload,
    ),
  archivePhoto: (photoId: number, payload: Record<string, AuditValue>) =>
    adminPost<AdminMutationSuccess>(
      `/api/v1/admin/photos/${photoId}/archive`,
      payload,
    ),
  linkRelationship: (
    relationshipType: string,
    payload: Record<string, AuditValue | undefined>,
  ) =>
    adminPost<AdminMutationSuccess>(
      `/api/v1/admin/data/relationships/${encodeURIComponent(relationshipType)}`,
      payload,
    ),
  relationships: (relationshipType: string) =>
    adminFetch<{ items: AdminRecord[] }>(
      `/api/v1/admin/data/relationships/${encodeURIComponent(relationshipType)}`,
    ),
  unlinkRelationship: (
    relationshipType: string,
    relationshipId: number,
    payload: Record<string, AuditValue>,
  ) =>
    adminPost<AdminMutationSuccess>(
      `/api/v1/admin/data/relationships/${encodeURIComponent(relationshipType)}/${relationshipId}/unlink`,
      payload,
    ),
  previewBulkStatus: (payload: Record<string, AuditValue>) =>
    adminPost<{ count: number; records: AdminRecord[]; atomic: boolean }>(
      "/api/v1/admin/data/eoats/bulk-status/preview",
      payload,
    ),
  commitBulkStatus: (payload: Record<string, AuditValue>) =>
    adminPost<{
      audit_event_id: string;
      affected_count: number;
      failed_count: number;
      atomic: boolean;
    }>("/api/v1/admin/data/eoats/bulk-status/commit", payload),
  settings: () =>
    adminFetch<{ items: AdminSetting[] }>("/api/v1/admin/settings"),
  updateSetting: (key: string, payload: Record<string, AuditValue>) =>
    adminWrite<{
      setting: AdminSetting;
      audit_event_id: string;
      correlation_id: string;
      request_id: string;
    }>(`/api/v1/admin/settings/${encodeURIComponent(key)}`, payload),
  mappings: () =>
    adminFetch<{ items: AdminMapping[] }>("/api/v1/admin/access/test-mappings"),
  updateMapping: (identity: string, payload: Record<string, AuditValue>) =>
    adminWrite<{
      mapping: AdminMapping;
      audit_event_id: string;
      correlation_id: string;
      request_id: string;
    }>(
      `/api/v1/admin/access/test-mappings/${encodeURIComponent(identity)}`,
      payload,
    ),
  sessions: () =>
    adminFetch<{ items: AdminRecord[] }>("/api/v1/admin/access/sessions"),
  revokeSession: (reference: string, payload: Record<string, AuditValue>) =>
    adminPost<{
      session_reference: string;
      audit_event_id: string;
      correlation_id: string;
      request_id: string;
    }>(
      `/api/v1/admin/access/sessions/${encodeURIComponent(reference)}/revoke`,
      payload,
    ),
  integrityScan: () =>
    adminPost<{
      operation_id: string;
      status: string;
      finding_count: number;
      findings: Array<Record<string, AuditValue>>;
      audit_event_id: string;
    }>("/api/v1/admin/integrity/scans", {}),
  latestIntegrity: (signal?: AbortSignal) =>
    adminFetch<{
      status: string;
      operation_id?: string;
      finding_count: number | null;
      by_severity: Record<string, number>;
      by_entity_type: Record<string, number>;
      completed_at?: string | null;
    }>("/api/v1/admin/integrity/latest", signal),
  operation: (operationId: string) =>
    adminFetch<AdminOperation>(
      `/api/v1/admin/operations/${encodeURIComponent(operationId)}`,
    ),
  auditExport: (
    format: "csv" | "json",
    filters: Record<string, string | boolean | null>,
  ) => adminDownload("/api/v1/admin/audit/exports", { format, filters }),
  supportBundle: (sections: string[], requestId?: string) =>
    adminDownload("/api/v1/admin/support-bundles", {
      sections,
      request_id: requestId ?? null,
    }),
  dangerStepUp: (payload: { rehearsal_step_up_secret?: string; password?: string }) =>
    adminPost<{
      step_up_reference: string;
      expires_at: string;
      rehearsal_only: boolean;
    }>("/api/v1/admin/danger-zone/fixture-recovery/step-up", payload),
  dangerPreview: (fixture_namespace: string) =>
    adminPost<{
      operation_id: string;
      preview_reference: string;
      expires_at: string;
      target: { fixture_namespace: string; target_count: number };
      typed_confirmation: string;
      preconditions: Array<{ name: string; state: string; detail: string }>;
    }>("/api/v1/admin/danger-zone/fixture-recovery/preview", {
      fixture_namespace,
    }),
  dangerCommit: (payload: {
    preview_reference: string;
    confirmation: string;
    reason: string;
  }) =>
    adminPost<{
      operation_id: string;
      status: string;
      removed_count?: number;
      message?: string;
      audit_event_id: string;
    }>("/api/v1/admin/danger-zone/fixture-recovery/commit", payload),
};
