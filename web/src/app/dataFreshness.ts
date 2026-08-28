import {
  browserFreshnessState,
  type BrowserFreshnessState,
} from "@/app/browserFreshness";

export type FreshnessState = ReturnType<typeof browserFreshnessState>;

export function freshnessState(
  freshness: BrowserFreshnessState,
  nowPerformanceMs = typeof performance === "undefined" ? 0 : performance.now(),
): FreshnessState {
  return browserFreshnessState(freshness, nowPerformanceMs);
}

export function formatLastRefreshed(value: string): string {
  const timestamp = new Date(value);
  const date = new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(timestamp);
  const time = new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(timestamp);
  return `${date} · ${time}`;
}
