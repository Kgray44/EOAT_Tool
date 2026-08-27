import { useEffect, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import {
  apiClient,
  sessionHasPermission,
  type AuthenticatedSession,
} from "@/api/client";
import { ApiError } from "@/api/errors";

function machineParts(value: string) {
  const [plant, number] = value.split("::", 2);
  return number
    ? { plant_code: plant, machine_number: number }
    : { machine_number: value };
}

export function InstallationEditor({
  identifier,
  rowVersion,
  onSaved,
}: {
  identifier: string;
  rowVersion: number;
  onSaved: () => void;
}) {
  const [session, setSession] = useState<AuthenticatedSession | null>(null);
  const [open, setOpen] = useState(false);
  const [machine, setMachine] = useState("");
  const [tool, setTool] = useState("");
  const [reason, setReason] = useState("");
  const [overrideReason, setOverrideReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [machines, tools] = useQueries({
    queries: [
      {
        queryKey: ["editor-catalog", "machine"],
        queryFn: () => apiClient.getCatalogOptions("machine"),
        staleTime: 60_000,
      },
      {
        queryKey: ["editor-catalog", "tool"],
        queryFn: () => apiClient.getCatalogOptions("tool"),
        staleTime: 60_000,
      },
    ],
  });
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
  const mayInstall = sessionHasPermission(session, "assignment.edit");
  const mayOverride = sessionHasPermission(
    session,
    "installation.override_compatibility",
  );
  async function save() {
    if (!mayInstall || !machine || !tool) return;
    setBusy(true);
    setError("");
    try {
      await apiClient.moveEoatToMachine(identifier, {
        ...machineParts(machine),
        tool_identifier: tool,
        expected_row_version: rowVersion,
        reason: reason || null,
        override_reason: mayOverride ? overrideReason || null : null,
      });
      setOpen(false);
      setReason("");
      setOverrideReason("");
      onSaved();
    } catch (failure) {
      setError(
        failure instanceof ApiError
          ? failure.message
          : "The installation was not saved. The displayed assignment is unchanged.",
      );
    } finally {
      setBusy(false);
    }
  }
  if (!mayInstall) return null;
  if (!open)
    return (
      <button
        className="profile-edit-button"
        type="button"
        onClick={() => setOpen(true)}
      >
        Install / assign EOAT
      </button>
    );
  return (
    <section className="entity-editor" aria-label={`Install ${identifier}`}>
      <header>
        <h2>Install / assign EOAT</h2>
        <p>
          EOAT Atlas runs compatibility enforcement before it records this
          assignment.
        </p>
      </header>
      <div className="entity-editor-grid">
        <label>
          <span>Machine</span>
          <select
            value={machine}
            onChange={(event) => setMachine(event.target.value)}
          >
            <option value="">Select a machine</option>
            {(machines.data ?? []).map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Tool / mold</span>
          <select
            value={tool}
            onChange={(event) => setTool(event.target.value)}
          >
            <option value="">Select a tool</option>
            {(tools.data ?? []).map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label className="wide">
          <span>Assignment reason</span>
          <textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
        {mayOverride && (
          <label className="wide">
            <span>Engineering compatibility override reason</span>
            <textarea
              value={overrideReason}
              onChange={(event) => setOverrideReason(event.target.value)}
            />
            <small>
              Only an Engineer or Administrator can provide this. A
              non-compatible assignment remains blocked without it.
            </small>
          </label>
        )}
      </div>
      {error && (
        <p className="entity-editor-error" role="alert">
          {error}
        </p>
      )}
      <footer>
        <button type="button" onClick={() => setOpen(false)} disabled={busy}>
          Cancel
        </button>
        <button
          type="button"
          onClick={() => void save()}
          disabled={busy || !machine || !tool}
        >
          {busy ? "Saving…" : "Confirm installation"}
        </button>
      </footer>
    </section>
  );
}
