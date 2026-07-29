import type { components } from "@/api/generated/types";
import { ApiError } from "@/api/errors";

export type HealthStatus = components["schemas"]["HealthResult"];
export type DataStatus = components["schemas"]["DataStatusResponse"];
export type EoatProfile = components["schemas"]["EOATProfile"];
export type EoatLocation = components["schemas"]["CurrentEOATLocation"];
export type EoatRelationship = components["schemas"]["RelationshipSummary"];
export type EoatHistory = components["schemas"]["PaginatedHistory"];
export type MachineProfile = components["schemas"]["MachineProfile"];
export type MachineSetup = components["schemas"]["MachineCurrentSetup"];
export type ToolProfile = components["schemas"]["ToolProfile"];
export type HistoryEvent = components["schemas"]["HistoryEvent"];
export type MachineList = components["schemas"]["PaginatedMachines"];
export type ToolList = components["schemas"]["PaginatedTools"];
export type EoatList = components["schemas"]["PaginatedEOATs"];
export type SearchResult = components["schemas"]["SearchResult"];
export type FitCheckRequest = components["schemas"]["WebFitCheckRequest"];
export type FitCheckResult = components["schemas"]["FitCheckResult"];
export type WebFitCheckOptions = components["schemas"]["WebFitCheckOptions"];
export type WebDocument = components["schemas"]["WebDocumentMetadata"];
export type WebPhoto = components["schemas"]["WebPhotoMetadata"];
export type SettingsCatalog = components["schemas"]["SettingsCatalogResponse"];
export type SharedSetting = {
  key: string;
  value: unknown;
  value_type: string;
  description: string | null;
  row_version: number;
};
export type SettingsSession = {
  authenticated: boolean;
  provider?: string;
  identity?: { display_name?: string };
  permissions?: string[];
  expires_at?: string;
};
export type AuthConfiguration = {
  provider: string;
  settings_authentication_available: boolean;
  provider_configured: boolean;
  development_identities?: string[];
  message: string;
};
export type SettingsAction = "reset-section" | "reset-all" | "set-defaults" | "factory-reset";
export type CatalogActivity = "active" | "inactive" | "all";
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
  const query = new URLSearchParams({ search, page: String(page), page_size: "24" });
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

export const apiClient = {
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
  async getSettingsCatalog(fetcher?: typeof fetch): Promise<SettingsCatalog> {
    return assertObject<SettingsCatalog>(
      await requestJson("/api/v1/settings/catalog", fetcher),
      ["sections", "items"],
      "Settings catalog",
    );
  },
  async getSharedSettings(fetcher?: typeof fetch): Promise<SharedSetting[]> {
    const payload = assertObject<{ items: SharedSetting[] }>(
      await requestJson("/api/v1/settings", fetcher),
      ["items"],
      "shared Settings",
    );
    return assertArray<SharedSetting>(payload.items, "shared Settings");
  },
  async getAuthConfiguration(fetcher?: typeof fetch): Promise<AuthConfiguration> {
    return assertObject<AuthConfiguration>(
      await requestJson("/api/v1/auth/config", fetcher),
      ["provider", "settings_authentication_available", "provider_configured", "message"],
      "Settings authentication configuration",
    );
  },
  async loginDevelopment(identity: string, fetcher?: typeof fetch): Promise<SettingsSession & { access_token: string }> {
    return assertObject<SettingsSession & { access_token: string }>(
      await requestJson("/api/v1/auth/development/login", fetcher, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identity }),
      }),
      ["access_token", "authenticated", "permissions"],
      "Settings administrator session",
    );
  },
  async getSettingsSession(token: string, fetcher?: typeof fetch): Promise<SettingsSession> {
    return assertObject<SettingsSession>(
      await requestJson("/api/v1/auth/session", fetcher, {
        headers: { Authorization: `Bearer ${token}` },
      }),
      ["authenticated", "permissions"],
      "Settings administrator session",
    );
  },
  async updateSharedSetting(
    key: string,
    value: unknown,
    token: string,
    description?: string,
    fetcher?: typeof fetch,
  ): Promise<SharedSetting> {
    return assertObject<SharedSetting>(
      await requestJson(`/api/v1/settings/${encodeURIComponent(key)}`, fetcher, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ value, description }),
      }),
      ["key", "value", "row_version"],
      "updated shared Setting",
    );
  },
  async applySettingsAction(
    action: SettingsAction,
    token: string,
    confirmation: string,
    section?: string,
    fetcher?: typeof fetch,
  ): Promise<{ action: SettingsAction; updated: number }> {
    return assertObject<{ action: SettingsAction; updated: number }>(
      await requestJson(`/api/v1/settings/actions/${action}`, fetcher, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ confirmation, section }),
      }),
      ["action", "updated"],
      "Settings action",
    );
  },
  async logoutSettings(token: string, fetcher?: typeof fetch): Promise<void> {
    await requestJson("/api/v1/auth/logout", fetcher, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
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
        `/api/v1/eoats/${encodeURIComponent(identifier)}/web-documents`,
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
        `/api/v1/eoats/${encodeURIComponent(identifier)}/web-photos`,
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
        `/api/v1/machines/${encodeURIComponent(number)}/web-documents`,
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
        `/api/v1/machines/${encodeURIComponent(number)}/web-photos`,
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
        `/api/v1/tools/${encodeURIComponent(identifier)}/web-documents`,
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
        `/api/v1/tools/${encodeURIComponent(identifier)}/web-photos`,
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
      await requestJson("/api/v1/web-fit-checks/evaluate", fetcher, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
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
