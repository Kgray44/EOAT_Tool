import type { DataStatus } from "@/api/client";

const STALE_AFTER_MS = 24 * 60 * 60 * 1000;

export type FreshnessState = "healthy" | "stale" | "unavailable";

export function freshnessState(status: DataStatus | undefined): FreshnessState {
  if (!status) return "unavailable";
  const lastUpdated = new Date(status.data_last_modified_at).valueOf();
  const serverTime = new Date(status.server_time).valueOf();
  if (!Number.isFinite(lastUpdated) || !Number.isFinite(serverTime))
    return "unavailable";
  return serverTime - lastUpdated > STALE_AFTER_MS ? "stale" : "healthy";
}

export function formatLastUpdated(value: string): string {
  const timestamp = new Date(value);
  const date = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(timestamp);
  const time = new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(timestamp);
  return `${date} · ${time}`;
}
