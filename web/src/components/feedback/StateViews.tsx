import type { ReactNode } from "react";
import { apiErrorMessage, ApiError } from "@/api/errors";

export function LoadingState({
  label = "Loading EOAT Atlas status…",
}: {
  label?: string;
}) {
  return (
    <p className="state state--loading" role="status">
      {label}
    </p>
  );
}

export function EmptyState({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="state" aria-labelledby="empty-state-title">
      <h2 id="empty-state-title">{title}</h2>
      <p>{children}</p>
    </section>
  );
}

export function ErrorState({ error, title }: { error: unknown; title?: string }) {
  const unavailable =
    error instanceof ApiError &&
    ["unavailable", "timeout"].includes(error.kind);
  return (
    <section className="state state--error" role="alert">
      <h2>{title || (unavailable ? "API unavailable" : "Unable to load status")}</h2>
      <p>{apiErrorMessage(error)}</p>
    </section>
  );
}

export function NotFoundState({
  identifier,
  entityName = "EOAT",
}: {
  identifier: string;
  entityName?: string;
}) {
  return (
    <section className="state" aria-labelledby="not-found-title">
      <h2 id="not-found-title">{entityName} not found</h2>
      <p>
        EOAT Atlas did not find <code>{identifier}</code>. Check the QR link or
        identifier and try again.
      </p>
    </section>
  );
}

export function StatusValue({
  value,
}: {
  value: string | number | boolean | null | undefined;
}) {
  if (value === null || value === undefined || value === "")
    return <span>Unknown / unavailable</span>;
  return <span>{String(value)}</span>;
}
