import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  apiClient,
  sessionHasPermission,
  type AuthenticatedSession,
} from "@/api/client";
import { ApiError } from "@/api/errors";

type EntityKind = "eoat" | "machine" | "tool";
type RelationshipType = "eoat-machine" | "eoat-tool" | "tool-machine";

type RelationshipChoice = {
  value: RelationshipType;
  label: string;
  targetLabel: string;
};

const choices: Record<EntityKind, RelationshipChoice[]> = {
  eoat: [
    {
      value: "eoat-machine",
      label: "EOAT to machine",
      targetLabel: "Machine number",
    },
    {
      value: "eoat-tool",
      label: "EOAT to tool",
      targetLabel: "Tool identifier",
    },
  ],
  machine: [
    {
      value: "eoat-machine",
      label: "Machine to EOAT",
      targetLabel: "EOAT identifier",
    },
    {
      value: "tool-machine",
      label: "Machine to tool",
      targetLabel: "Tool identifier",
    },
  ],
  tool: [
    {
      value: "eoat-tool",
      label: "Tool to EOAT",
      targetLabel: "EOAT identifier",
    },
    {
      value: "tool-machine",
      label: "Tool to machine",
      targetLabel: "Machine number",
    },
  ],
};

function payloadFor(
  kind: EntityKind,
  identifier: string,
  relationshipType: RelationshipType,
  target: string,
  compatibilityStatus: string,
  effectiveFrom: string,
  reason: string,
) {
  const payload: Record<string, unknown> = {
    compatibility_status: compatibilityStatus,
    effective_from: new Date(`${effectiveFrom}T00:00:00Z`).toISOString(),
    reason: reason || null,
  };
  if (relationshipType === "eoat-machine") {
    payload.eoat_identifier = kind === "eoat" ? identifier : target;
    payload.machine_number = kind === "machine" ? identifier : target;
  } else if (relationshipType === "eoat-tool") {
    payload.eoat_identifier = kind === "eoat" ? identifier : target;
    payload.tool_identifier = kind === "tool" ? identifier : target;
  } else {
    payload.tool_identifier = kind === "tool" ? identifier : target;
    payload.machine_number = kind === "machine" ? identifier : target;
  }
  return payload;
}

export function CompatibilityEditor({
  kind,
  identifier,
  onSaved,
}: {
  kind: EntityKind;
  identifier: string;
  onSaved: () => void;
}) {
  const [session, setSession] = useState<AuthenticatedSession | null>(null);
  const [open, setOpen] = useState(false);
  const [relationshipType, setRelationshipType] = useState<RelationshipType>(
    choices[kind][0].value,
  );
  const [target, setTarget] = useState("");
  const [status, setStatus] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState(
    new Date().toISOString().slice(0, 10),
  );
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const statuses = useQuery({
    queryKey: ["editor-catalog", "compatibility_status"],
    queryFn: () => apiClient.getCatalogOptions("compatibility_status"),
    staleTime: 60_000,
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

  const mayEdit = sessionHasPermission(session, "compatibility.write");
  const choice =
    choices[kind].find((value) => value.value === relationshipType) ??
    choices[kind][0];
  const consequential = /incompatible|not.compatible|failed/i.test(status);
  async function save() {
    if (
      !mayEdit ||
      !target ||
      !status ||
      !effectiveFrom ||
      (consequential && !confirmed)
    )
      return;
    setBusy(true);
    setError("");
    try {
      await apiClient.createCompatibility(
        relationshipType,
        payloadFor(
          kind,
          identifier,
          relationshipType,
          target,
          status,
          effectiveFrom,
          reason,
        ),
      );
      setOpen(false);
      setTarget("");
      setReason("");
      setConfirmed(false);
      onSaved();
    } catch (failure) {
      setError(
        failure instanceof ApiError
          ? failure.message
          : "The compatibility record was not saved. The displayed relationships are unchanged.",
      );
    } finally {
      setBusy(false);
    }
  }
  if (!mayEdit) return null;
  if (!open)
    return (
      <button
        className="profile-edit-button"
        type="button"
        onClick={() => setOpen(true)}
      >
        Add compatibility
      </button>
    );
  return (
    <section
      className="entity-editor"
      aria-label={`Add compatibility for ${identifier}`}
    >
      <header>
        <h2>Add compatibility relationship</h2>
        <p>
          EOAT Atlas validates the referenced records and does not infer
          compatibility from an absent relationship.
        </p>
      </header>
      <div className="entity-editor-grid">
        <label>
          <span>Relationship</span>
          <select
            value={relationshipType}
            onChange={(event) =>
              setRelationshipType(event.target.value as RelationshipType)
            }
          >
            {choices[kind].map((value) => (
              <option key={value.value} value={value.value}>
                {value.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>{choice.targetLabel}</span>
          <input
            value={target}
            onChange={(event) => setTarget(event.target.value)}
            required
          />
        </label>
        <label>
          <span>Compatibility status</span>
          <select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setConfirmed(false);
            }}
          >
            <option value="">Select a verified status</option>
            {(statuses.data ?? []).map((value) => (
              <option key={value.value} value={value.value}>
                {value.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Effective from</span>
          <input
            type="date"
            value={effectiveFrom}
            onChange={(event) => setEffectiveFrom(event.target.value)}
            required
          />
        </label>
        <label className="wide">
          <span>Reason / evidence</span>
          <textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
      </div>
      {consequential && (
        <label className="entity-editor-confirm">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />{" "}
          I confirm this consequential incompatible status is supported by the
          stated evidence.
        </label>
      )}
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
          disabled={busy || !target || !status || (consequential && !confirmed)}
        >
          {busy ? "Saving…" : "Save compatibility"}
        </button>
      </footer>
    </section>
  );
}
