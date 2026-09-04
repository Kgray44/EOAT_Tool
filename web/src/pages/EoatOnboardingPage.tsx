import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  apiClient,
  sessionHasPermission,
  type AuthenticatedSession,
  type OnboardingDraft,
} from "@/api/client";
import { ApiError } from "@/api/errors";

type Identity = Record<string, string | number | boolean | null>;
type CompatibilityDraft = {
  relationship_type: "eoat-machine" | "eoat-tool";
  target: string;
  compatibility_status: string;
  effective_from: string;
  reason?: string;
};
const steps = [
  "Identity",
  "Hardware",
  "Pneumatics & Sensors",
  "Machines, Tools & Compatibility",
  "Photos & Documents",
  "Review & Create",
];

function payloadOf(draft: OnboardingDraft | null) {
  return (draft?.payload ?? {}) as {
    identity?: Identity;
    engineering?: Identity;
    compatibility?: unknown[];
    location?: Identity;
  };
}

export function EoatOnboardingPage() {
  const { draftUuid } = useParams();
  const navigate = useNavigate();
  const [draft, setDraft] = useState<OnboardingDraft | null>(null);
  const [session, setSession] = useState<AuthenticatedSession | null>(null);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [identity, setIdentity] = useState<Identity>({
    business_identifier: "",
    display_name: "",
    eoat_type: "",
    status: "",
    revision: "",
    vacuum_present: null,
    sensors_present: null,
    number_of_vacuum_cups: null,
    number_of_grippers: null,
    notes: "",
  });
  const [engineering, setEngineering] = useState<Identity>({
    cylinders_present: null,
    cylinder_count: null,
    cylinder_model: "",
    gripper_model: "",
    vacuum_generation: "",
    pneumatic_connection: "",
    electrical_present: null,
    electrical_connection: "",
    sensor_models: "",
  });
  const [compatibility, setCompatibility] = useState<CompatibilityDraft[]>([]);
  const [location, setLocation] = useState<Identity>({ kind: "unassigned" });

  useEffect(() => {
    void apiClient
      .getAuthenticatedSession()
      .then(setSession)
      .catch(() => setSession(null));
  }, []);
  useEffect(() => {
    if (!draftUuid) return;
    void apiClient
      .getOnboardingDraft(draftUuid)
      .then((value) => {
        setDraft(value);
        const payload = payloadOf(value);
        setIdentity((payload.identity ?? {}) as Identity);
        setEngineering((payload.engineering ?? {}) as Identity);
        setCompatibility((payload.compatibility ?? []) as CompatibilityDraft[]);
        setLocation((payload.location ?? { kind: "unassigned" }) as Identity);
      })
      .catch((reason) =>
        setError(
          reason instanceof ApiError
            ? reason.message
            : "The onboarding draft could not be loaded.",
        ),
      );
  }, [draftUuid]);
  const mayCreate = sessionHasPermission(session, "onboarding.draft.create");
  const mayFinalize = sessionHasPermission(
    session,
    "onboarding.draft.finalize",
  );
  const complete = Boolean(identity.business_identifier && identity.eoat_type);
  const payload = useMemo(
    () => ({
      identity,
      engineering,
      compatibility,
      location,
    }),
    [compatibility, engineering, identity, location],
  );
  async function save() {
    if (!mayCreate) return;
    setBusy(true);
    setError("");
    try {
      const body = {
        proposed_identifier: String(identity.business_identifier || ""),
        payload,
        ...(draft ? { expected_row_version: draft.row_version } : {}),
      };
      const saved = draft
        ? await apiClient.saveOnboardingDraft(draft.draft_uuid, body)
        : await apiClient.createOnboardingDraft(body);
      setDraft(saved);
      if (!draft) navigate(`/eoats/new/${saved.draft_uuid}`, { replace: true });
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Draft save failed. Your unsaved fields remain on this device.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function finalize() {
    if (!draft || !mayFinalize) return;
    setBusy(true);
    setError("");
    try {
      const result = await apiClient.finalizeOnboardingDraft(
        draft.draft_uuid,
        draft.row_version,
      );
      navigate(
        `/eoats/${encodeURIComponent(result.eoat.business_identifier)}`,
        { replace: true },
      );
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Finalization failed; the draft remains recoverable.",
      );
    } finally {
      setBusy(false);
    }
  }
  if (!mayCreate)
    return (
      <section className="onboarding-page">
        <h1>EOAT onboarding</h1>
        <p>You do not have permission to prepare an EOAT onboarding draft.</p>
      </section>
    );
  return (
    <section className="onboarding-page" aria-label="EOAT onboarding workflow">
      <header>
        <p className="eyebrow">EOAT onboarding</p>
        <h1>{draft ? "Continue onboarding" : "Add New EOAT"}</h1>
        <p>
          {draft
            ? `Draft ${draft.proposed_identifier || "without an identifier"} · ${draft.completion_state}`
            : "Start a governed draft. It will not enter the Library until finalization."}
        </p>
      </header>
      <nav className="onboarding-steps" aria-label="Onboarding sections">
        {steps.map((label, index) => (
          <button
            type="button"
            key={label}
            className={index === step ? "active" : undefined}
            onClick={() => setStep(index)}
            aria-current={index === step ? "step" : undefined}
          >
            {index + 1}. {label}
            {index === 0 && complete ? " ✓" : ""}
          </button>
        ))}
      </nav>
      <section className="onboarding-card">
        {step === 0 && (
          <div className="onboarding-grid">
            <Field
              label="EOAT identifier"
              value={identity.business_identifier}
              onChange={(value) =>
                setIdentity({ ...identity, business_identifier: value })
              }
              required
            />
            <Field
              label="Display name"
              value={identity.display_name}
              onChange={(value) =>
                setIdentity({ ...identity, display_name: value })
              }
            />
            <Field
              label="EOAT type"
              value={identity.eoat_type}
              onChange={(value) =>
                setIdentity({ ...identity, eoat_type: value })
              }
              required
            />
            <Field
              label="Status"
              value={identity.status}
              onChange={(value) => setIdentity({ ...identity, status: value })}
            />
            <Field
              label="Revision"
              value={identity.revision}
              onChange={(value) =>
                setIdentity({ ...identity, revision: value })
              }
            />
            <label className="wide">
              <span>Notes</span>
              <textarea
                value={String(identity.notes ?? "")}
                onChange={(e) =>
                  setIdentity({ ...identity, notes: e.target.value })
                }
              />
            </label>
          </div>
        )}
        {step === 1 && (
          <div className="onboarding-grid">
            <BooleanField
              label="Vacuum present"
              value={identity.vacuum_present}
              onChange={(value) =>
                setIdentity({ ...identity, vacuum_present: value })
              }
            />
            <Field
              label="Vacuum cups"
              type="number"
              value={identity.number_of_vacuum_cups}
              onChange={(value) =>
                setIdentity({
                  ...identity,
                  number_of_vacuum_cups: value === "" ? null : Number(value),
                })
              }
            />
            <Field
              label="Grippers"
              type="number"
              value={identity.number_of_grippers}
              onChange={(value) =>
                setIdentity({
                  ...identity,
                  number_of_grippers: value === "" ? null : Number(value),
                })
              }
            />
            <BooleanField
              label="Cylinders present"
              value={engineering.cylinders_present}
              onChange={(value) =>
                setEngineering({ ...engineering, cylinders_present: value })
              }
            />
            <Field
              label="Cylinder count"
              type="number"
              value={engineering.cylinder_count}
              onChange={(value) =>
                setEngineering({
                  ...engineering,
                  cylinder_count: value === "" ? null : Number(value),
                })
              }
            />
            <Field
              label="Cylinder model"
              value={engineering.cylinder_model}
              onChange={(value) =>
                setEngineering({ ...engineering, cylinder_model: value })
              }
            />
            <Field
              label="Gripper model"
              value={engineering.gripper_model}
              onChange={(value) =>
                setEngineering({ ...engineering, gripper_model: value })
              }
            />
            <Field
              label="Vacuum generation"
              value={engineering.vacuum_generation}
              onChange={(value) =>
                setEngineering({ ...engineering, vacuum_generation: value })
              }
            />
          </div>
        )}
        {step === 2 && (
          <div className="onboarding-grid">
            <BooleanField
              label="Sensors present"
              value={identity.sensors_present}
              onChange={(value) =>
                setIdentity({ ...identity, sensors_present: value })
              }
            />
            <Field
              label="Sensor models"
              value={engineering.sensor_models}
              onChange={(value) =>
                setEngineering({ ...engineering, sensor_models: value })
              }
            />
            <BooleanField
              label="Electrical present"
              value={engineering.electrical_present}
              onChange={(value) =>
                setEngineering({ ...engineering, electrical_present: value })
              }
            />
            <Field
              label="Electrical connection"
              value={engineering.electrical_connection}
              onChange={(value) =>
                setEngineering({ ...engineering, electrical_connection: value })
              }
            />
            <Field
              label="Pneumatic connection"
              value={engineering.pneumatic_connection}
              onChange={(value) =>
                setEngineering({ ...engineering, pneumatic_connection: value })
              }
            />
          </div>
        )}
        {step === 3 && (
          <RelationshipSection
            compatibility={compatibility}
            onCompatibilityChange={setCompatibility}
            location={location}
            onLocationChange={setLocation}
          />
        )}
        {step === 4 && (
          <p>
            Stage controlled media through the existing approved media root.
            Draft media remains unavailable as ordinary EOAT media until
            finalization.
          </p>
        )}
        {step === 5 && (
          <div>
            <h2>Review</h2>
            <p>
              {complete
                ? "Required identity fields are present. Final validation will re-check the identifier, permissions, references, and staged media."
                : "Blocking: enter an identifier and EOAT type before finalization."}
            </p>
            <p>Draft status: {draft ? draft.completion_state : "Not saved"}</p>
          </div>
        )}
        {error && (
          <p role="alert" className="entity-editor-error">
            {error}
          </p>
        )}
        <footer>
          <button
            type="button"
            onClick={() => setStep(Math.max(0, step - 1))}
            disabled={step === 0 || busy}
          >
            Back
          </button>
          <button type="button" onClick={() => void save()} disabled={busy}>
            {busy ? "Saving…" : draft ? "Save draft" : "Start draft"}
          </button>
          {step < steps.length - 1 ? (
            <button type="button" onClick={() => setStep(step + 1)}>
              Next
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void finalize()}
              disabled={!draft || !complete || !mayFinalize || busy}
            >
              {mayFinalize ? "Create EOAT" : "Finalization approval required"}
            </button>
          )}
        </footer>
      </section>
      <Link to="/library">Return to Library</Link>
    </section>
  );
}
function RelationshipSection({
  compatibility,
  onCompatibilityChange,
  location,
  onLocationChange,
}: {
  compatibility: CompatibilityDraft[];
  onCompatibilityChange: (value: CompatibilityDraft[]) => void;
  location: Identity;
  onLocationChange: (value: Identity) => void;
}) {
  const machines = useQuery({
    queryKey: ["onboarding", "machines"],
    queryFn: () => apiClient.getCatalogOptions("machine"),
  });
  const tools = useQuery({
    queryKey: ["onboarding", "tools"],
    queryFn: () => apiClient.getCatalogOptions("tool"),
  });
  const statuses = useQuery({
    queryKey: ["onboarding", "compatibility-statuses"],
    queryFn: () => apiClient.getCatalogOptions("compatibility_status"),
  });
  const [type, setType] =
    useState<CompatibilityDraft["relationship_type"]>("eoat-machine");
  const [target, setTarget] = useState("");
  const [status, setStatus] = useState("");
  const [reason, setReason] = useState("");
  const options =
    type === "eoat-machine" ? (machines.data ?? []) : (tools.data ?? []);
  const add = () => {
    if (!target || !status) return;
    onCompatibilityChange([
      ...compatibility,
      {
        relationship_type: type,
        target,
        compatibility_status: status,
        effective_from: new Date().toISOString(),
        reason: reason || undefined,
      },
    ]);
    setTarget("");
    setStatus("");
    setReason("");
  };
  return (
    <div className="onboarding-relationships">
      <h2>Current location and compatibility</h2>
      <p>
        Current assignment is separate from approved compatibility. Unknown
        relationships are not inferred.
      </p>
      <div className="onboarding-grid">
        <label>
          <span>Current location</span>
          <select
            value={String(location.kind ?? "unassigned")}
            onChange={(e) =>
              onLocationChange({ ...location, kind: e.target.value })
            }
          >
            <option value="unassigned">Unassigned</option>
            <option value="machine">Installed on a machine</option>
            <option value="storage">Stored</option>
          </select>
        </label>
        {location.kind === "machine" && (
          <label>
            <span>Installed machine</span>
            <select
              value={String(location.machine_number ?? "")}
              onChange={(e) =>
                onLocationChange({
                  ...location,
                  machine_number: e.target.value,
                })
              }
            >
              <option value="">Select a machine</option>
              {(machines.data ?? []).map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
        )}
        {location.kind === "machine" && (
          <label>
            <span>Installed tool (if known)</span>
            <select
              value={String(location.tool_identifier ?? "")}
              onChange={(e) =>
                onLocationChange({
                  ...location,
                  tool_identifier: e.target.value || null,
                })
              }
            >
              <option value="">Not recorded</option>
              {(tools.data ?? []).map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <hr />
      <h3>Add approved compatibility</h3>
      <div className="onboarding-grid">
        <label>
          <span>Relationship</span>
          <select
            value={type}
            onChange={(e) =>
              setType(e.target.value as CompatibilityDraft["relationship_type"])
            }
          >
            <option value="eoat-machine">EOAT ↔ Machine</option>
            <option value="eoat-tool">EOAT ↔ Tool</option>
          </select>
        </label>
        <label>
          <span>{type === "eoat-machine" ? "Machine" : "Tool"}</span>
          <select value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">Select authoritative record</option>
            {options.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Select verified status</option>
            {(statuses.data ?? []).map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label className="wide">
          <span>Evidence / provenance</span>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
      </div>
      <button type="button" onClick={add} disabled={!target || !status}>
        Add compatibility
      </button>
      <ul className="onboarding-relationship-list">
        {compatibility.map((item, index) => (
          <li key={`${item.relationship_type}-${item.target}-${index}`}>
            <span>
              {item.relationship_type === "eoat-machine" ? "Machine" : "Tool"}:{" "}
              {item.target} · {item.compatibility_status}
            </span>
            <button
              type="button"
              onClick={() =>
                onCompatibilityChange(
                  compatibility.filter((_, itemIndex) => itemIndex !== index),
                )
              }
            >
              Remove
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
function Field({
  label,
  value,
  onChange,
  type = "text",
  required = false,
}: {
  label: string;
  value: unknown;
  onChange: (value: string) => void;
  type?: "text" | "number";
  required?: boolean;
}) {
  return (
    <label>
      <span>
        {label}
        {required ? " *" : ""}
      </span>
      <input
        type={type}
        value={value == null ? "" : String(value)}
        onChange={(e) => onChange(e.target.value)}
        required={required}
      />
    </label>
  );
}
function BooleanField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: unknown;
  onChange: (value: boolean | null) => void;
}) {
  return (
    <label>
      <span>{label}</span>
      <select
        value={value == null ? "" : String(value)}
        onChange={(e) =>
          onChange(e.target.value === "" ? null : e.target.value === "true")
        }
      >
        <option value="">Unknown</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </select>
    </label>
  );
}
