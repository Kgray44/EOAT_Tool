import { useEffect, useMemo, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import {
  apiClient,
  sessionHasPermission,
  type AuthenticatedSession,
  type CatalogOptionKind,
} from "@/api/client";
import { ApiError } from "@/api/errors";

export type EditorField = {
  key: string;
  label: string;
  kind?: "text" | "number" | "date" | "boolean" | "textarea";
  catalog?: CatalogOptionKind;
  value: unknown;
};

type EntityKind = "eoat" | "machine" | "tool";

function serialized(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

function requestFor(
  kind: EntityKind,
  identifier: string,
  values: Record<string, unknown>,
) {
  if (kind === "eoat") return apiClient.patchEoat(identifier, values as never);
  if (kind === "machine")
    return apiClient.patchMachine(identifier, values as never);
  return apiClient.patchTool(identifier, values as never);
}

function inputValue(field: EditorField, value: string): unknown {
  if (field.kind === "boolean") return value === "" ? null : value === "true";
  if (field.kind === "number") return value === "" ? null : Number(value);
  return value || null;
}

export function EntityEditor({
  kind,
  identifier,
  rowVersion,
  fields,
  onSaved,
}: {
  kind: EntityKind;
  identifier: string;
  rowVersion: number;
  fields: EditorField[];
  onSaved: () => void;
}) {
  const [session, setSession] = useState<AuthenticatedSession | null>(null);
  const [editing, setEditing] = useState(false);
  const fieldSignature = JSON.stringify(
    fields.map((field) => [field.key, field.value]),
  );
  const initial = useMemo(
    () =>
      Object.fromEntries(
        (JSON.parse(fieldSignature) as [string, unknown][]).map(
          ([key, value]) => [key, serialized(value)],
        ),
      ),
    [fieldSignature],
  );
  const [values, setValues] = useState<Record<string, string>>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const refresh = () =>
      void apiClient
        .getAuthenticatedSession()
        .then(setSession)
        .catch(() => setSession(null));
    refresh();
    window.addEventListener("atlas-authentication-changed", refresh);
    return () =>
      window.removeEventListener("atlas-authentication-changed", refresh);
  }, []);
  useEffect(() => {
    if (!editing) setValues(initial);
  }, [editing, initial]);

  const catalogs = useQueries({
    queries: fields
      .filter((field) => field.catalog)
      .map((field) => ({
        queryKey: ["editor-catalog", field.catalog],
        queryFn: () => apiClient.getCatalogOptions(field.catalog!),
        staleTime: 60_000,
      })),
  });
  const optionsByCatalog = new Map<
    CatalogOptionKind,
    { value: string; label: string }[]
  >();
  fields
    .filter((field) => field.catalog)
    .forEach((field, index) => {
      optionsByCatalog.set(field.catalog!, catalogs[index]?.data ?? []);
    });

  const mayEdit = sessionHasPermission(session, `${kind}.edit`);
  const dirty = fields.some(
    (field) => values[field.key] !== initial[field.key],
  );
  function cancel() {
    setValues(initial);
    setError("");
    setEditing(false);
  }
  async function save() {
    if (!mayEdit || !dirty) return;
    setBusy(true);
    setError("");
    const changed = fields.reduce<Record<string, unknown>>(
      (result, field) => {
        if (values[field.key] !== initial[field.key])
          result[field.key] = inputValue(field, values[field.key]);
        return result;
      },
      { expected_row_version: rowVersion },
    );
    try {
      await requestFor(kind, identifier, changed);
      setEditing(false);
      onSaved();
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "The update could not be completed. Your profile still shows server-confirmed data.",
      );
    } finally {
      setBusy(false);
    }
  }
  if (!mayEdit) return null;
  if (!editing) {
    return (
      <button
        className="profile-edit-button"
        type="button"
        onClick={() => setEditing(true)}
      >
        Edit {kind}
      </button>
    );
  }
  return (
    <section
      className="entity-editor"
      aria-label={`Edit ${kind} ${identifier}`}
    >
      <header>
        <h2>Edit {kind}</h2>
        <p>
          Changes are saved only after EOAT Atlas confirms this authenticated
          update.
        </p>
      </header>
      <div className="entity-editor-grid">
        {fields.map((field) => (
          <label
            key={field.key}
            className={field.kind === "textarea" ? "wide" : undefined}
          >
            <span>{field.label}</span>
            {field.kind === "textarea" ? (
              <textarea
                value={values[field.key] ?? ""}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    [field.key]: event.target.value,
                  }))
                }
              />
            ) : field.kind === "boolean" ? (
              <select
                value={values[field.key] ?? ""}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    [field.key]: event.target.value,
                  }))
                }
              >
                <option value="">Not recorded</option>
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            ) : field.catalog ? (
              <select
                value={values[field.key] ?? ""}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    [field.key]: event.target.value,
                  }))
                }
              >
                <option value="">Not recorded</option>
                {values[field.key] &&
                  !optionsByCatalog
                    .get(field.catalog)
                    ?.some((option) => option.value === values[field.key]) && (
                    <option value={values[field.key]}>
                      {values[field.key]}
                    </option>
                  )}
                {(optionsByCatalog.get(field.catalog) ?? []).map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type={
                  field.kind === "number"
                    ? "number"
                    : field.kind === "date"
                      ? "date"
                      : "text"
                }
                value={values[field.key] ?? ""}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    [field.key]: event.target.value,
                  }))
                }
              />
            )}
          </label>
        ))}
      </div>
      {error && (
        <p className="entity-editor-error" role="alert">
          {error}
        </p>
      )}
      <footer>
        <button type="button" onClick={cancel} disabled={busy}>
          Cancel
        </button>
        <button type="button" onClick={save} disabled={busy || !dirty}>
          {busy ? "Saving…" : "Save changes"}
        </button>
      </footer>
    </section>
  );
}
