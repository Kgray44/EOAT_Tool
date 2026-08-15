import type { components } from "@/api/generated/types";
import { ApiError } from "@/api/errors";

export type HealthStatus = components["schemas"]["HealthResult"];
export type DataStatus = { status: "available"; data_last_modified_at: string; server_time: string; data_revision: number };
export type EoatProfile = components["schemas"]["EOATProfile"];
export type EoatLocation = components["schemas"]["CurrentEOATLocation"];
export type EoatRelationship = components["schemas"]["RelationshipSummary"];
export type EoatHistory = components["schemas"]["PaginatedHistory"];
export type MachineProfile = components["schemas"]["MachineProfile"];
export type MachineSetup = { machine_number: string; current_eoat: string; current_tool: string; verified: boolean; location_semantics?: string };
export type ToolProfile = components["schemas"]["ToolProfile"];
export type HistoryEvent = components["schemas"]["HistoryEvent"];
export type MachineList = components["schemas"]["PaginatedMachines"];
export type ToolList = components["schemas"]["PaginatedTools"];
export type EoatList = components["schemas"]["PaginatedEOATs"];
export type SearchResult = { category: "eoat" | "machine" | "tool"; identifier: string; title: string; subtitle: string; matched_field: string };
export type FitCheckRequest = { machine_number: string; tool_number: string; eoat_identifier: string; persist?: boolean; plant_code?: string };
export type FitCheckResult = components["schemas"]["FitCheckResult"];
export type WebFitCheckOptions = { machines: Array<{ identifier: string; label: string; plant_code?: string }>; tools: Array<{ identifier: string; label: string; plant_code?: string }>; eoats: Array<{ identifier: string; label: string; plant_code?: string }>; warnings: string[]; unresolved_inputs: string[] };
export type WebDocument = components["schemas"]["WebDocumentMetadata"];
export type WebPhoto = components["schemas"]["WebPhotoMetadata"];
export type SetupPacketData = {
  machine: unknown;
  tool: unknown;
  eoat: unknown;
  fit_check: FitCheckResult;
  generated_at: string;
  source: string;
};
export type AuthenticatedSession = {
  authenticated: boolean;
  expires_at?: string;
  identity?: {
    display_name?: string;
    external_subject?: string;
    username?: string;
  };
  roles?: string[];
  /** Server-derived grants inform UI only; every API mutation enforces again. */
  permissions?: string[];
  scope?: "application" | "settings_only";
};
export type EoatPatch = components["schemas"]["EOATPatch"];
export type MachinePatch = components["schemas"]["MachinePatch"];
export type ToolPatch = components["schemas"]["ToolPatch"];
export type CatalogActivity = "active" | "inactive" | "all";
export type CatalogOptionKind =
  | "area"
  | "cleanroom"
  | "compatibility_source"
  | "compatibility_status"
  | "connection_type"
  | "eoat"
  | "eoat_type"
  | "machine"
  | "mold"
  | "plant"
  | "robot"
  | "status"
  | "tool";
export type CatalogOption = { value: string; label: string };
export type CatalogFilters = {
  sort?: string;
  eoatType?: string;
  plant?: string;
  area?: string;
  cleanroom?: string;
  machine?: string;
  tool?: string;
  mold?: string;
  robot?: string;
  eoat?: string;
};

export function sessionHasPermission(
  session: AuthenticatedSession | null | undefined,
  permission: string,
): boolean {
  const grants = session?.permissions ?? [];
  return grants.includes("*") || grants.includes(permission);
}

const REQUEST_TIMEOUT_MS = 8_000;

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : undefined;
}

function isHealthStatus(value: unknown): value is HealthStatus {
  const result = asRecord(value);
  return (
    !!result &&
    typeof result.api_version === "string" &&
    typeof result.application_version === "string" &&
    typeof result.compatible === "boolean" &&
    typeof result.writes_enabled === "boolean" &&
    typeof result.expected_schema_revision === "string"
  );
}

function isDataStatus(value: unknown): value is DataStatus {
  const result = asRecord(value);
  return (
    !!result &&
    result.status === "available" &&
    typeof result.data_last_modified_at === "string" &&
    typeof result.server_time === "string" &&
    typeof result.data_revision === "number"
  );
}

function messageFor(
  status: number,
  body: Record<string, unknown> | undefined,
): ApiError {
  const detail = asRecord(body?.detail);
  const message =
    typeof body?.message === "string"
      ? body.message
      : typeof detail?.message === "string"
        ? detail.message
        : `EOAT Atlas returned HTTP ${status}.`;
  const requestId =
    typeof body?.request_id === "string" ? body.request_id : undefined;
  if (status === 401 || status === 403)
    return new ApiError("authorization", message, status, requestId);
  if (status === 404)
    return new ApiError("not-found", message, status, requestId);
  if (status === 422)
    return new ApiError("validation", message, status, requestId);
  if (status >= 500)
    return new ApiError("unavailable", message, status, requestId);
  return new ApiError("unexpected", message, status, requestId);
}

function assertObject<T>(payload: unknown, fields: string[], label: string): T {
  const result = asRecord(payload);
  if (!result || fields.some((field) => !(field in result)))
    throw new ApiError(
      "malformed-response",
      `EOAT Atlas returned an incomplete ${label} response.`,
    );
  return payload as T;
}

function assertArray<T>(payload: unknown, label: string): T[] {
  if (!Array.isArray(payload))
    throw new ApiError(
      "malformed-response",
      `EOAT Atlas returned an invalid ${label} response.`,
    );
  return payload as T[];
}

function catalogQuery(
  search: string,
  page: number,
  activity: CatalogActivity,
  filters: CatalogFilters,
  parameters: Record<string, string | undefined>,
): string {
  const query = new URLSearchParams({
    search,
    page: String(page),
    page_size: "24",
  });
  if (activity === "all") query.set("include_inactive", "true");
  if (activity === "inactive") query.set("active", "false");
  Object.entries(parameters).forEach(([key, value]) => {
    if (value) query.set(key, value);
  });
  if (filters.sort) query.set("sort", filters.sort);
  return query.toString();
}

async function requestJson(
  path: string,
  fetcher: typeof fetch = fetch,
  init?: RequestInit,
): Promise<unknown> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetcher(path, {
      method: init?.method ?? "GET",
      headers: { Accept: "application/json", ...init?.headers },
      credentials: init?.credentials ?? "same-origin",
      signal: controller.signal,
      body: init?.body,
    });
    const text = await response.text();
    let body: unknown;
    try {
      body = text ? JSON.parse(text) : undefined;
    } catch {
      throw new ApiError(
        "malformed-response",
        "EOAT Atlas returned an invalid JSON response.",
        response.status,
      );
    }
    if (!response.ok) throw messageFor(response.status, asRecord(body));
    return body;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError")
      throw new ApiError(
        "timeout",
        "EOAT Atlas did not respond before the request timed out.",
      );
    throw new ApiError(
      "unavailable",
      "EOAT Atlas is unavailable. Check the local API connection and try again.",
    );
  } finally {
    window.clearTimeout(timer);
  }
}

function csrfHeader(): HeadersInit {
  const value = document.cookie
    .split("; ")
    .find((item) => item.startsWith("eoat_atlas_csrf="))
    ?.split("=", 2)[1];
  return value ? { "X-EOAT-CSRF-Token": decodeURIComponent(value) } : {};
}

export const apiClient = {
  async getAuthenticatedSession(
    fetcher?: typeof fetch,
  ): Promise<AuthenticatedSession> {
    return assertObject<AuthenticatedSession>(
      await requestJson("/api/v1/auth/session", fetcher),
      ["authenticated", "roles", "permissions", "scope"],
      "authentication session",
    );
  },
  async kerberosFormLogin(
    username: string,
    password: string,
    fetcher?: typeof fetch,
  ): Promise<AuthenticatedSession> {
    return assertObject<AuthenticatedSession>(
      await requestJson("/api/v1/auth/kerberos-form/login", fetcher, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      }),
      ["authenticated", "identity", "roles", "permissions", "scope"],
      "authentication session",
    );
  },
  async logout(fetcher?: typeof fetch): Promise<void> {
    await requestJson("/api/v1/auth/logout", fetcher, {
      method: "POST",
      headers: csrfHeader(),
    });
  },
  async patchEoat(
    identifier: string,
    payload: EoatPatch,
    fetcher?: typeof fetch,
  ): Promise<{ row_version: number }> {
    return assertObject<{ row_version: number }>(
      await requestJson(
        `/api/v1/eoats/${encodeURIComponent(identifier)}`,
        fetcher,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json", ...csrfHeader() },
          body: JSON.stringify(payload),
        },
      ),
      ["row_version"],
      "updated EOAT",
    );
  },
  async patchMachine(
    number: string,
    payload: MachinePatch,
    fetcher?: typeof fetch,
  ): Promise<{ row_version: number }> {
    return assertObject<{ row_version: number }>(
      await requestJson(
        `/api/v1/machines/${encodeURIComponent(number)}`,
        fetcher,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json", ...csrfHeader() },
          body: JSON.stringify(payload),
        },
      ),
      ["row_version"],
      "updated Machine",
    );
  },
  async patchTool(
    identifier: string,
    payload: ToolPatch,
    fetcher?: typeof fetch,
  ): Promise<{ row_version: number }> {
    return assertObject<{ row_version: number }>(
      await requestJson(
        `/api/v1/tools/${encodeURIComponent(identifier)}`,
        fetcher,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json", ...csrfHeader() },
          body: JSON.stringify(payload),
        },
      ),
      ["row_version"],
      "updated Tool",
    );
  },
  async createCompatibility(
    relationshipType: "eoat-machine" | "eoat-tool" | "tool-machine",
    payload: Record<string, unknown>,
    fetcher?: typeof fetch,
  ): Promise<{ id: number; row_version: number }> {
    return assertObject<{ id: number; row_version: number }>(
      await requestJson(`/api/v1/compatibility/${relationshipType}`, fetcher, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...csrfHeader() },
        body: JSON.stringify(payload),
      }),
      ["id", "row_version"],
      "created compatibility relationship",
    );
  },
  async moveEoatToMachine(
    identifier: string,
    payload: Record<string, unknown>,
    fetcher?: typeof fetch,
  ): Promise<{ id: number; row_version: number }> {
    return assertObject<{ id: number; row_version: number }>(
      await requestJson(
        `/api/v1/eoats/${encodeURIComponent(identifier)}/move-to-machine`,
        fetcher,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...csrfHeader() },
          body: JSON.stringify(payload),
        },
      ),
      ["id", "row_version"],
      "created installation",
    );
  },
  async uploadWebMedia(
    payload: {
      entityType: "eoat" | "machine" | "tool";
      entityIdentifier: string;
      file: File;
      title: string;
      mediaKind: "document" | "photo";
      description?: string;
    },
    fetcher?: typeof fetch,
  ): Promise<{ document_uuid: string; row_version: number }> {
    const bytes = new Uint8Array(await payload.file.arrayBuffer());
    let binary = "";
    for (let offset = 0; offset < bytes.length; offset += 0x8000) {
      binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
    }
    return assertObject<{ document_uuid: string; row_version: number }>(
      await requestJson("/api/v1/web-media/upload", fetcher, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...csrfHeader() },
        body: JSON.stringify({
          entity_type: payload.entityType,
          entity_identifier: payload.entityIdentifier,
          file_name: payload.file.name,
          content_base64: btoa(binary),
          title: payload.title,
          media_kind: payload.mediaKind,
          document_type: payload.mediaKind === "photo" ? "photo" : "document",
          description: payload.description,
          mime_type: payload.file.type || null,
        }),
      }),
      ["document_uuid", "row_version"],
      "uploaded media",
    );
  },
  async getHealth(fetcher?: typeof fetch): Promise<HealthStatus> {
    const payload = await requestJson("/api/v1/health", fetcher);
    if (!isHealthStatus(payload))
      throw new ApiError(
        "malformed-response",
        "EOAT Atlas returned an incomplete health response.",
      );
    return payload;
  },
  async getDataStatus(fetcher?: typeof fetch): Promise<DataStatus> {
    const payload = await requestJson("/api/v1/data-status", fetcher);
    if (!isDataStatus(payload))
      throw new ApiError(
        "malformed-response",
        "EOAT Atlas returned an incomplete data-status response.",
      );
    return payload;
  },
  async getEoatProfile(
    identifier: string,
    fetcher?: typeof fetch,
  ): Promise<EoatProfile> {
    return assertObject<EoatProfile>(
      await requestJson(
        `/api/v1/eoats/${encodeURIComponent(identifier)}`,
        fetcher,
      ),
      ["business_identifier", "is_active", "relationships"],
      "EOAT profile",
    );
  },
  async getEoatLocation(
    identifier: string,
    fetcher?: typeof fetch,
  ): Promise<EoatLocation> {
    return assertObject<EoatLocation>(
      await requestJson(
        `/api/v1/eoats/${encodeURIComponent(identifier)}/current-location`,
        fetcher,
      ),
      ["state", "source", "confidence", "resolution_status", "evidence"],
      "current-location",
    );
  },
  async getEoatRelationships(
    identifier: string,
    fetcher?: typeof fetch,
  ): Promise<EoatRelationship[]> {
    return assertArray<EoatRelationship>(
      await requestJson(
        `/api/v1/eoats/${encodeURIComponent(identifier)}/relationships`,
        fetcher,
      ),
      "relationships",
    );
  },
  async getEoatDocuments(
    identifier: string,
    fetcher?: typeof fetch,
  ): Promise<WebDocument[]> {
    return assertArray<WebDocument>(
      await requestJson(
        `/api/v1/eoats/${encodeURIComponent(identifier)}/documents`,
        fetcher,
      ),
      "browser-safe documents",
    );
  },
  async getEoatPhotos(
    identifier: string,
    fetcher?: typeof fetch,
  ): Promise<WebPhoto[]> {
    return assertArray<WebPhoto>(
      await requestJson(
        `/api/v1/eoats/${encodeURIComponent(identifier)}/photos`,
        fetcher,
      ),
      "browser-safe photos",
    );
  },
  async getEoatHistory(
    identifier: string,
    fetcher?: typeof fetch,
  ): Promise<EoatHistory> {
    return assertObject<EoatHistory>(
      await requestJson(
        `/api/v1/eoats/${encodeURIComponent(identifier)}/history?page_size=12`,
        fetcher,
      ),
      ["items", "pagination"],
      "history",
    );
  },
  async getMachineProfile(
    number: string,
    fetcher?: typeof fetch,
  ): Promise<MachineProfile> {
    return assertObject<MachineProfile>(
      await requestJson(
        `/api/v1/machines/${encodeURIComponent(number)}`,
        fetcher,
      ),
      ["machine_number", "plant_code", "is_active", "relationships"],
      "machine profile",
    );
  },
  async getMachineRelationships(
    number: string,
    fetcher?: typeof fetch,
  ): Promise<EoatRelationship[]> {
    return assertArray<EoatRelationship>(
      await requestJson(
        `/api/v1/machines/${encodeURIComponent(number)}/relationships`,
        fetcher,
      ),
      "machine relationships",
    );
  },
  async getMachineSetup(
    number: string,
    fetcher?: typeof fetch,
  ): Promise<MachineSetup> {
    return assertObject<MachineSetup>(
      await requestJson(
        `/api/v1/machines/${encodeURIComponent(number)}/current-setup`,
        fetcher,
      ),
      ["machine_number", "current_eoat", "current_tool", "verified"],
      "machine current setup",
    );
  },
  async getMachineHistory(
    number: string,
    fetcher?: typeof fetch,
  ): Promise<HistoryEvent[]> {
    return assertArray<HistoryEvent>(
      await requestJson(
        `/api/v1/machines/${encodeURIComponent(number)}/history`,
        fetcher,
      ),
      "machine history",
    );
  },
  async getMachineDocuments(
    number: string,
    fetcher?: typeof fetch,
  ): Promise<WebDocument[]> {
    return assertArray<WebDocument>(
      await requestJson(
        `/api/v1/machines/${encodeURIComponent(number)}/documents`,
        fetcher,
      ),
      "machine browser-safe documents",
    );
  },
  async getMachinePhotos(
    number: string,
    fetcher?: typeof fetch,
  ): Promise<WebPhoto[]> {
    return assertArray<WebPhoto>(
      await requestJson(
        `/api/v1/machines/${encodeURIComponent(number)}/photos`,
        fetcher,
      ),
      "machine browser-safe photos",
    );
  },
  async getToolProfile(
    identifier: string,
    fetcher?: typeof fetch,
  ): Promise<ToolProfile> {
    return assertObject<ToolProfile>(
      await requestJson(
        `/api/v1/tools/${encodeURIComponent(identifier)}`,
        fetcher,
      ),
      ["business_identifier", "is_active", "relationships"],
      "tool profile",
    );
  },
  async getToolRelationships(
    identifier: string,
    fetcher?: typeof fetch,
  ): Promise<EoatRelationship[]> {
    return assertArray<EoatRelationship>(
      await requestJson(
        `/api/v1/tools/${encodeURIComponent(identifier)}/relationships`,
        fetcher,
      ),
      "tool relationships",
    );
  },
  async getToolHistory(
    identifier: string,
    fetcher?: typeof fetch,
  ): Promise<HistoryEvent[]> {
    return assertArray<HistoryEvent>(
      await requestJson(
        `/api/v1/tools/${encodeURIComponent(identifier)}/history`,
        fetcher,
      ),
      "tool history",
    );
  },
  async getToolDocuments(
    identifier: string,
    fetcher?: typeof fetch,
  ): Promise<WebDocument[]> {
    return assertArray<WebDocument>(
      await requestJson(
        `/api/v1/tools/${encodeURIComponent(identifier)}/documents`,
        fetcher,
      ),
      "tool browser-safe documents",
    );
  },
  async getToolPhotos(
    identifier: string,
    fetcher?: typeof fetch,
  ): Promise<WebPhoto[]> {
    return assertArray<WebPhoto>(
      await requestJson(
        `/api/v1/tools/${encodeURIComponent(identifier)}/photos`,
        fetcher,
      ),
      "tool browser-safe photos",
    );
  },
  async getMachines(
    search = "",
    page = 1,
    activity: CatalogActivity = "active",
    filters: CatalogFilters = {},
    fetcher?: typeof fetch,
  ): Promise<MachineList> {
    return assertObject<MachineList>(
      await requestJson(
        `/api/v1/machines?${catalogQuery(search, page, activity, filters, {
          plant: filters.plant,
          area: filters.area,
          cleanroom: filters.cleanroom,
          eoat_identifier: filters.eoat,
          tool_number: filters.tool,
          robot_number: filters.robot,
        })}`,
        fetcher,
      ),
      ["items", "pagination"],
      "machine list",
    );
  },
  async getTools(
    search = "",
    page = 1,
    activity: CatalogActivity = "active",
    filters: CatalogFilters = {},
    fetcher?: typeof fetch,
  ): Promise<ToolList> {
    return assertObject<ToolList>(
      await requestJson(
        `/api/v1/tools?${catalogQuery(search, page, activity, filters, {
          mold: filters.mold || filters.tool,
          machine_number: filters.machine,
          eoat_identifier: filters.eoat,
        })}`,
        fetcher,
      ),
      ["items", "pagination"],
      "tool list",
    );
  },
  async getCatalogOptions(
    kind: CatalogOptionKind,
    query = "",
    fetcher?: typeof fetch,
  ): Promise<CatalogOption[]> {
    const parameters = new URLSearchParams({ limit: "50" });
    if (query.trim()) parameters.set("query", query.trim());
    return assertArray<CatalogOption>(
      await requestJson(
        `/api/v1/catalog-options/${encodeURIComponent(kind)}?${parameters}`,
        fetcher,
      ),
      "catalog options",
    );
  },
  async getEoats(
    search = "",
    page = 1,
    activity: CatalogActivity = "active",
    filters: CatalogFilters = {},
    fetcher?: typeof fetch,
  ): Promise<EoatList> {
    return assertObject<EoatList>(
      await requestJson(
        `/api/v1/eoats?${catalogQuery(search, page, activity, filters, {
          eoat_type: filters.eoatType,
          area: filters.area,
          cleanroom: filters.cleanroom,
          machine_number: filters.machine,
          tool_number: filters.tool,
        })}`,
        fetcher,
      ),
      ["items", "pagination"],
      "EOAT list",
    );
  },
  async search(query: string, fetcher?: typeof fetch): Promise<SearchResult[]> {
    return assertArray<SearchResult>(
      await requestJson(
        `/api/v1/search?q=${encodeURIComponent(query)}&limit=75`,
        fetcher,
      ),
      "search results",
    );
  },
  async getWebFitCheckOptions(
    selection: Partial<FitCheckRequest>,
    fetcher?: typeof fetch,
  ): Promise<WebFitCheckOptions> {
    const query = new URLSearchParams();
    if (selection.plant_code) query.set("plant_code", selection.plant_code);
    if (selection.machine_number)
      query.set("machine_number", selection.machine_number);
    if (selection.tool_number) query.set("tool_number", selection.tool_number);
    if (selection.eoat_identifier)
      query.set("eoat_identifier", selection.eoat_identifier);
    return assertObject<WebFitCheckOptions>(
      await requestJson(
        `/api/v1/web-fit-checks/options${query.size ? `?${query}` : ""}`,
        fetcher,
      ),
      ["machines", "tools", "eoats", "warnings", "unresolved_inputs"],
      "Fit Check options",
    );
  },
  async evaluateWebFitCheck(
    payload: FitCheckRequest,
    fetcher?: typeof fetch,
  ): Promise<FitCheckResult> {
    return assertObject<FitCheckResult>(
      await requestJson("/api/v1/fit-checks/evaluate", fetcher, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          machine_number: payload.machine_number,
          tool_number: payload.tool_number,
          eoat_identifier: payload.eoat_identifier,
          persist: false,
        }),
      }),
      [
        "overall_result",
        "machine_tool_result",
        "machine_eoat_result",
        "tool_eoat_result",
      ],
      "read-only Fit Check",
    );
  },
  async getSetupPacketData(
    request: FitCheckRequest,
    fetcher?: typeof fetch,
  ): Promise<SetupPacketData> {
    const query = new URLSearchParams({
      machine_number: request.machine_number,
      tool_number: request.tool_number,
      eoat_identifier: request.eoat_identifier,
    });
    if (request.plant_code) query.set("plant_code", request.plant_code);
    return assertObject<SetupPacketData>(
      await requestJson(`/api/v1/setup-packets/data?${query}`, fetcher),
      ["machine", "tool", "eoat", "fit_check", "generated_at", "source"],
      "setup packet data",
    );
  },
  documentContentUrl(documentUuid: string): string {
    return `/api/v1/web-documents/${encodeURIComponent(documentUuid)}/content`;
  },
  photoContentUrl(documentUuid: string): string {
    return `/api/v1/web-photos/${encodeURIComponent(documentUuid)}/content`;
  },
  photoThumbnailUrl(documentUuid: string): string {
    return `/api/v1/web-photos/${encodeURIComponent(documentUuid)}/thumbnail`;
  },
};
