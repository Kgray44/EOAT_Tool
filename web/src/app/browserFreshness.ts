import type { DataStatus } from "@/api/client";

export const BROWSER_FRESHNESS_STALE_AFTER_MS = 24 * 60 * 60 * 1000;

export type BrowserFreshnessState = {
  lastSuccessfulRefreshAt?: string;
  lastSuccessfulRefreshPerformanceMs?: number;
  lastDataStatusUpdatedAt?: number;
  latestRefreshFailed: boolean;
};

export type ObservedQuery = {
  active: boolean;
  data: unknown;
  dataUpdatedAt: number;
  fetching?: boolean;
  key: readonly unknown[];
  status: "pending" | "error" | "success";
};

const initialState: BrowserFreshnessState = {
  latestRefreshFailed: false,
};

function isDataStatusQuery(query: ObservedQuery): boolean {
  return query.key.length === 1 && query.key[0] === "data-status";
}

function isAuthenticationQuery(query: ObservedQuery): boolean {
  return query.key.length === 1 && query.key[0] === "authentication-session";
}

function isDataStatus(value: unknown): value is DataStatus {
  if (!value || typeof value !== "object") return false;
  const status = value as Partial<DataStatus>;
  return (
    status.status === "available" && typeof status.server_time === "string"
  );
}

/**
 * Advances browser freshness only when the active EOAT Atlas data queries and
 * the server-time query have all completed successfully.  `data-status` is
 * deliberately not sufficient when another displayed query is in error.
 */
export function reconcileBrowserFreshness(
  previous: BrowserFreshnessState = initialState,
  queries: readonly ObservedQuery[],
  observedAtPerformanceMs: number,
): BrowserFreshnessState {
  const active = queries.filter((query) => query.active);
  const dataStatus = active.find(isDataStatusQuery);
  const displayedData = active.filter((query) => !isAuthenticationQuery(query));
  const refreshFailed = displayedData.some((query) => query.status === "error");

  if (refreshFailed) return { ...previous, latestRefreshFailed: true };

  if (
    !dataStatus ||
    dataStatus.status !== "success" ||
    !isDataStatus(dataStatus.data) ||
    !Number.isFinite(new Date(dataStatus.data.server_time).valueOf())
  )
    return previous;

  const allDisplayedDataSucceeded = displayedData.every(
    (query) => query.status === "success" && !query.fetching,
  );
  const dataStatusIsNew =
    dataStatus.dataUpdatedAt > (previous.lastDataStatusUpdatedAt ?? 0);

  if (!allDisplayedDataSucceeded || !dataStatusIsNew) return previous;

  return {
    lastSuccessfulRefreshAt: dataStatus.data.server_time,
    lastSuccessfulRefreshPerformanceMs: observedAtPerformanceMs,
    lastDataStatusUpdatedAt: dataStatus.dataUpdatedAt,
    latestRefreshFailed: false,
  };
}

export function browserFreshnessState(
  freshness: BrowserFreshnessState,
  nowPerformanceMs: number,
): "healthy" | "stale" | "degraded" | "unavailable" {
  if (!freshness.lastSuccessfulRefreshAt) return "unavailable";
  const refreshedAt = freshness.lastSuccessfulRefreshPerformanceMs;
  if (
    refreshedAt === undefined ||
    nowPerformanceMs - refreshedAt > BROWSER_FRESHNESS_STALE_AFTER_MS
  )
    return "stale";
  if (freshness.latestRefreshFailed) return "degraded";
  return "healthy";
}
