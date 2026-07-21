import type { components } from "@/api/generated/types";
import { ApiError } from "@/api/errors";

export type HealthStatus = components["schemas"]["HealthResult"];

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

function messageFor(
  status: number,
  body: Record<string, unknown> | undefined,
): ApiError {
  const message =
    typeof body?.message === "string"
      ? body.message
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

async function requestJson(
  path: string,
  fetcher: typeof fetch = fetch,
): Promise<unknown> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetcher(path, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: controller.signal,
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
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(
        "timeout",
        "EOAT Atlas did not respond before the request timed out.",
      );
    }
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
    if (!isHealthStatus(payload)) {
      throw new ApiError(
        "malformed-response",
        "EOAT Atlas returned an incomplete health response.",
      );
    }
    return payload;
  },
};
