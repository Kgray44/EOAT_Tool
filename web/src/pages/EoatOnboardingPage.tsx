import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  apiClient,
  sessionHasPermission,
  type AuthenticatedSession,
  type OnboardingDraft,
} from "@/api/client";
import { ApiError } from "@/api/errors";
import { QrLabel } from "@/components/qr/QrLabel";

type Identity = Record<string, string | number | boolean | null>;
type CompatibilityDraft = {
  relationship_type: "eoat-machine" | "eoat-tool";
  target: string;
  compatibility_status: string;
  effective_from: string;
  reason?: string;
};
function machineNumber(value: string) {
  return value.split("::").at(-1) || value;
}
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
  const [plantCode, setPlantCode] = useState("");
  const [areaCode, setAreaCode] = useState("");
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
  const [selectedMedia, setSelectedMedia] = useState<File | null>(null);
  const [mediaPreview, setMediaPreview] = useState<string | null>(null);
  const [mediaKind, setMediaKind] = useState<"photo" | "document">("photo");
  const [photoViewType, setPhotoViewType] = useState("FRONT");
  const [documentType, setDocumentType] = useState("");
  const [mediaTitle, setMediaTitle] = useState("");
  const [mediaCaption, setMediaCaption] = useState("");
  const [mediaStatus, setMediaStatus] = useState("");
  const [saveStatus, setSaveStatus] = useState("Not saved");
  const [finalizedIdentifier, setFinalizedIdentifier] = useState<string | null>(null);
  const draftRef = useRef<OnboardingDraft | null>(null);
  const onboardingStatus = useQuery({
    queryKey: ["onboarding", "status"],
    queryFn: () => apiClient.getOnboardingStatus(),
  });
  const documentTypes = useQuery({
    queryKey: ["onboarding", "document-types"],
    queryFn: () => apiClient.getCatalogOptions("document_type"),
    enabled: step === 4,
  });

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
        setPlantCode(value.plant_code ?? "");
        setAreaCode(value.area_code ?? "");
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
  useEffect(() => {
    draftRef.current = draft;
  }, [draft]);
  useEffect(() => {
    if (!selectedMedia || mediaKind !== "photo") {
      setMediaPreview(null);
      return;
    }
    const url = URL.createObjectURL(selectedMedia);
    setMediaPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [mediaKind, selectedMedia]);
  const mayCreate = sessionHasPermission(session, "onboarding.draft.create");
  const mayFinalize = sessionHasPermission(
    session,
    "onboarding.draft.finalize",
  );
  const mayDiscard = sessionHasPermission(session, "onboarding.draft.discard");
  const complete = Boolean(identity.business_identifier && identity.eoat_type);
  const review = useQuery({
    queryKey: ["onboarding", draft?.draft_uuid, draft?.row_version, "review"],
    queryFn: () => apiClient.reviewOnboardingDraft(draft!.draft_uuid),
    enabled: step === steps.length - 1 && Boolean(draft),
  });
  const hasBlockingReviewErrors = Boolean(review.data?.blocking_errors.length);
  const stepComplete = [
    complete,
    Boolean(
      identity.number_of_vacuum_cups != null ||
        identity.number_of_grippers != null ||
        engineering.cylinders_present != null,
    ),
    Boolean(
      identity.sensors_present != null ||
        engineering.electrical_present != null ||
        engineering.pneumatic_connection,
    ),
    compatibility.length > 0 || location.kind === "unassigned",
    (draft?.staged_media?.length ?? 0) > 0,
    complete,
  ];
  const payload = useMemo(
    () => ({
      identity,
      engineering,
      compatibility,
      location,
    }),
    [compatibility, engineering, identity, location],
  );
  useEffect(() => {
    if (!draft?.draft_uuid || !mayCreate) return;
    setSaveStatus("Changes pending…");
    const timer = window.setTimeout(() => {
      const current = draftRef.current;
      if (!current) return;
      setSaveStatus("Saving…");
      void apiClient
        .saveOnboardingDraft(current.draft_uuid, {
          proposed_identifier: String(identity.business_identifier || ""),
          payload,
          expected_row_version: current.row_version,
        })
        .then((saved) => {
          draftRef.current = saved;
          setDraft(saved);
          setSaveStatus("Saved");
        })
        .catch((reason) =>
          setSaveStatus(
            reason instanceof ApiError
              ? `Save failed: ${reason.message}`
              : "Save failed. Your changes are still in this browser.",
          ),
        );
    }, 900);
    return () => window.clearTimeout(timer);
  }, [areaCode, draft?.draft_uuid, identity.business_identifier, mayCreate, payload, plantCode]);
  useEffect(() => {
    if (saveStatus !== "Changes pending…" && saveStatus !== "Saving…") return;
    const warnBeforeLeaving = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnBeforeLeaving);
    return () => window.removeEventListener("beforeunload", warnBeforeLeaving);
  }, [saveStatus]);
  async function save() {
    if (!mayCreate) return;
    setBusy(true);
    setError("");
    try {
      const body = {
        proposed_identifier: String(identity.business_identifier || ""),
        plant_code: plantCode || null,
        area_code: areaCode || null,
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
      setFinalizedIdentifier(result.eoat.business_identifier);
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
  async function generateIdentifier() {
    if (!draft) {
      setError("Save the draft with its plant code before generating an identifier.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const generated = await apiClient.generateOnboardingIdentifier(
        draft.draft_uuid,
        draft.row_version,
      );
      draftRef.current = generated;
      setDraft(generated);
      setIdentity((current) => ({
        ...current,
        business_identifier: generated.proposed_identifier ?? "",
      }));
      setSaveStatus("Generated identifier reserved");
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "An identifier could not be generated.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function uploadMedia() {
    if (!draft || !selectedMedia || !mediaTitle) return;
    setBusy(true);
    setMediaStatus("");
    try {
      await apiClient.uploadOnboardingMedia(
        draft.draft_uuid,
        draft.row_version,
        {
          file: selectedMedia,
          mediaKind,
          documentType: mediaKind === "photo" ? "photo" : documentType,
          title: mediaTitle,
          photoViewType: mediaKind === "photo" ? photoViewType : undefined,
          caption: mediaKind === "photo" ? mediaCaption || undefined : undefined,
          description: mediaKind === "document" ? mediaCaption || undefined : undefined,
        },
      );
      const refreshed = await apiClient.getOnboardingDraft(draft.draft_uuid);
      draftRef.current = refreshed;
      setDraft(refreshed);
      setMediaStatus(`${selectedMedia.name} staged safely.`);
      setSelectedMedia(null);
      setMediaTitle("");
      setMediaCaption("");
    } catch (reason) {
      setMediaStatus(
        reason instanceof ApiError
          ? reason.message
          : "Media could not be staged.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function removeMedia(mediaId: number) {
    if (!draft) return;
    setBusy(true);
    setMediaStatus("");
    try {
      const result = await apiClient.removeOnboardingMedia(
        draft.draft_uuid,
        mediaId,
        draft.row_version,
      );
      const updated = {
        ...draft,
        row_version: result.row_version,
        staged_media: (draft.staged_media ?? []).filter(
          (media) => media.id !== mediaId,
        ),
      };
      draftRef.current = updated;
      setDraft(updated);
      setMediaStatus("Staged media removed from this draft.");
    } catch (reason) {
      setMediaStatus(
        reason instanceof ApiError ? reason.message : "Media could not be removed.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function discard() {
    if (!draft || !mayDiscard) return;
    if (!window.confirm("Discard this onboarding draft? This keeps an audited record but releases its identifier reservation."))
      return;
    setBusy(true);
    setError("");
    try {
      await apiClient.discardOnboardingDraft(draft.draft_uuid, draft.row_version);
      navigate("/eoats/onboarding-drafts", { replace: true });
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "The onboarding draft could not be discarded.",
      );
    } finally {
      setBusy(false);
    }
  }
  if (onboardingStatus.isSuccess && !onboardingStatus.data.enabled)
    return (
      <section className="onboarding-page">
        <h1>EOAT onboarding</h1>
        <p>This feature is not enabled in the current environment.</p>
      </section>
    );
  if (finalizedIdentifier)
    return (
      <section className="onboarding-page">
        <header>
          <p className="eyebrow">EOAT onboarding complete</p>
          <h1>{finalizedIdentifier} is now an EOAT Atlas asset</h1>
          <p>
            The permanent record was created through the governed transaction.
            It is ready for its canonical profile, relationships, and QR label.
          </p>
        </header>
        <section className="onboarding-card">
          <p>
            <Link className="profile-edit-button" to={`/eoats/${encodeURIComponent(finalizedIdentifier)}`}>
              View profile
            </Link>{" "}
            <Link className="profile-edit-button" to="/eoats/new">
              Add another EOAT
            </Link>
          </p>
          <QrLabel category="eoat" identifier={finalizedIdentifier} />
        </section>
      </section>
    );
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
        {draft && (
          <p className="onboarding-save-status" role="status">
            {saveStatus}
          </p>
        )}
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
            {stepComplete[index] ? " ✓" : " · needs attention"}
          </button>
        ))}
      </nav>
      <section className="onboarding-card">
        {step === 0 && (
          <div className="onboarding-grid">
            <Field
              label="Plant code"
              value={plantCode}
              onChange={setPlantCode}
              required
            />
            <Field
              label="Area code"
              value={areaCode}
              onChange={setAreaCode}
            />
            <Field
              label="EOAT identifier"
              value={identity.business_identifier}
              onChange={(value) =>
                setIdentity({ ...identity, business_identifier: value })
              }
              required
            />
            {draft && (
              <button type="button" disabled={busy || !plantCode} onClick={() => void generateIdentifier()}>
                Generate next identifier
              </button>
            )}
            <Field
              label="Display name"
              value={identity.display_name}
              onChange={(value) =>
                setIdentity({ ...identity, display_name: value })
              }
            />
            <Field
              label="Legacy / physical label"
              value={identity.legacy_identifier}
              onChange={(value) =>
                setIdentity({ ...identity, legacy_identifier: value })
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
              label="Robot connection / interface"
              value={identity.connection_type}
              onChange={(value) =>
                setIdentity({ ...identity, connection_type: value })
              }
            />
            <Field
              label="Environment / classification"
              value={identity.cleanroom_classification}
              onChange={(value) =>
                setIdentity({ ...identity, cleanroom_classification: value })
              }
            />
            <Field
              label="Revision"
              value={identity.revision}
              onChange={(value) =>
                setIdentity({ ...identity, revision: value })
              }
            />
            <label className="wide">
              <span>Description / part information</span>
              <textarea
                value={String(identity.description ?? "")}
                onChange={(e) =>
                  setIdentity({ ...identity, description: e.target.value })
                }
              />
            </label>
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
              label="Parts picked"
              type="number"
              value={identity.number_of_parts_picked}
              onChange={(value) =>
                setIdentity({
                  ...identity,
                  number_of_parts_picked: value === "" ? null : Number(value),
                })
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
              label="Quick disconnect present"
              value={identity.quick_disconnect_present}
              onChange={(value) =>
                setIdentity({ ...identity, quick_disconnect_present: value })
              }
            />
            <Field
              label="Cup material"
              value={identity.cup_material}
              onChange={(value) => setIdentity({ ...identity, cup_material: value })}
            />
            <Field
              label="Frame material"
              value={identity.frame_material}
              onChange={(value) => setIdentity({ ...identity, frame_material: value })}
            />
            <Field
              label="Weight (kg)"
              type="number"
              value={identity.weight_kg}
              onChange={(value) =>
                setIdentity({ ...identity, weight_kg: value === "" ? null : Number(value) })
              }
            />
            <Field
              label="Maximum payload (kg)"
              type="number"
              value={identity.maximum_payload_kg}
              onChange={(value) =>
                setIdentity({ ...identity, maximum_payload_kg: value === "" ? null : Number(value) })
              }
            />
            <Field
              label="Drawing number"
              value={identity.drawing_number}
              onChange={(value) => setIdentity({ ...identity, drawing_number: value })}
            />
            <Field
              label="Manufacturer"
              value={identity.manufacturer}
              onChange={(value) => setIdentity({ ...identity, manufacturer: value })}
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
              label="Part-present sensor"
              value={identity.part_present_sensor_present}
              onChange={(value) =>
                setIdentity({ ...identity, part_present_sensor_present: value })
              }
            />
            <BooleanField
              label="Vacuum-confirmation sensor"
              value={identity.vacuum_confirmation_sensor_present}
              onChange={(value) =>
                setIdentity({ ...identity, vacuum_confirmation_sensor_present: value })
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
              label="Vacuum circuits"
              type="number"
              value={engineering.vacuum_circuits}
              onChange={(value) =>
                setEngineering({ ...engineering, vacuum_circuits: value === "" ? null : Number(value) })
              }
            />
            <Field
              label="Pressure circuits"
              type="number"
              value={engineering.pressure_circuits}
              onChange={(value) =>
                setEngineering({ ...engineering, pressure_circuits: value === "" ? null : Number(value) })
              }
            />
            <Field
              label="Electrical pinout reference"
              value={engineering.electrical_pinout_reference}
              onChange={(value) =>
                setEngineering({ ...engineering, electrical_pinout_reference: value })
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
          <div className="onboarding-media">
            <h2>Photos & Documents</h2>
            <p>
              Files remain staged outside the normal EOAT media library until
              successful finalization.
            </p>
            <div className="onboarding-grid">
              <label>
                <span>Media type</span>
                <select
                  value={mediaKind}
                  onChange={(e) =>
                    setMediaKind(e.target.value as "photo" | "document")
                  }
                >
                  <option value="photo">Photo</option>
                  <option value="document">Document</option>
                </select>
              </label>
              <label>
                <span>Title</span>
                <input
                  value={mediaTitle}
                  onChange={(e) => setMediaTitle(e.target.value)}
                />
              </label>
              {mediaKind === "photo" ? (
                <label>
                  <span>Photo view</span>
                  <select
                    value={photoViewType}
                    onChange={(e) => setPhotoViewType(e.target.value)}
                  >
                    <option value="FRONT">Front / profile candidate</option>
                    <option value="BACK">Back / pickup face</option>
                    <option value="SIDE">Side</option>
                    <option value="CONNECTION">Robot connection / mounting interface</option>
                    <option value="VACUUM">Vacuum cups / grippers</option>
                    <option value="SENSORS">Sensors</option>
                    <option value="PNEUMATICS">Tubing / pneumatics</option>
                    <option value="DETAIL">Detail / problem</option>
                    <option value="ADDITIONAL">Additional</option>
                  </select>
                </label>
              ) : (
                <label>
                  <span>Document category</span>
                  <select
                    value={documentType}
                    onChange={(e) => setDocumentType(e.target.value)}
                  >
                    <option value="">Select a controlled category</option>
                    {(documentTypes.data ?? []).map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label className="wide">
                <span>{mediaKind === "photo" ? "Caption" : "Notes"}</span>
                <textarea
                  value={mediaCaption}
                  onChange={(e) => setMediaCaption(e.target.value)}
                />
              </label>
              <label className="wide">
                <span>File</span>
                <input
                  type="file"
                  accept={mediaKind === "photo" ? "image/*" : undefined}
                  onChange={(e) =>
                    setSelectedMedia(e.target.files?.[0] ?? null)
                  }
                />
                {mediaPreview && (
                  <img
                    className="onboarding-media-preview"
                    src={mediaPreview}
                    alt="Selected upload preview"
                  />
                )}
              </label>
            </div>
            <button
              type="button"
              disabled={
                !draft ||
                !selectedMedia ||
                !mediaTitle ||
                busy ||
                (mediaKind === "document" && !documentType)
              }
              onClick={() => void uploadMedia()}
            >
              {busy ? "Staging…" : "Stage media"}
            </button>
            {mediaStatus && <p role="status">{mediaStatus}</p>}
            {(draft?.staged_media?.length ?? 0) > 0 && (
              <ul className="onboarding-relationship-list">
                {draft?.staged_media?.map((media) => (
                  <li key={media.id}>
                    <span>
                      {media.media_kind === "photo" ? "Photo" : "Document"}: {media.title} · {media.file_name}
                    </span>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void removeMedia(media.id)}
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
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
            {review.isPending && draft && <p>Checking current records and staged media…</p>}
            {review.data && (
              <>
                <h3>Blocking errors</h3>
                {review.data.blocking_errors.length ? (
                  <ul>
                    {review.data.blocking_errors.map((item) => (
                      <li key={item.code}>{item.message}</li>
                    ))}
                  </ul>
                ) : (
                  <p>No current blocking errors.</p>
                )}
                <h3>Warnings</h3>
                {review.data.warnings.length ? (
                  <ul>
                    {review.data.warnings.map((item) => (
                      <li key={item.code}>{item.message}</li>
                    ))}
                  </ul>
                ) : (
                  <p>No current warnings.</p>
                )}
              </>
            )}
            {review.isError && (
              <p role="alert">The server review could not be completed. Finalization remains protected.</p>
            )}
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
          {draft && mayDiscard && (
            <button type="button" onClick={() => void discard()} disabled={busy}>
              Discard draft
            </button>
          )}
          {step < steps.length - 1 ? (
            <button type="button" onClick={() => setStep(step + 1)}>
              Next
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void finalize()}
              disabled={
                !draft ||
                !complete ||
                !mayFinalize ||
                busy ||
                review.isPending ||
                review.isError ||
                hasBlockingReviewErrors
              }
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
  const [search, setSearch] = useState("");
  const machines = useQuery({
    queryKey: ["onboarding", "machines", search],
    queryFn: () => apiClient.getCatalogOptions("machine", search),
  });
  const tools = useQuery({
    queryKey: ["onboarding", "tools", search],
    queryFn: () => apiClient.getCatalogOptions("tool", search),
  });
  const statuses = useQuery({
    queryKey: ["onboarding", "compatibility-statuses"],
    queryFn: () => apiClient.getCatalogOptions("compatibility_status"),
  });
  const storage = useQuery({
    queryKey: ["onboarding", "storage"],
    queryFn: () => apiClient.getCatalogOptions("storage"),
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
        target: type === "eoat-machine" ? machineNumber(target) : target,
        compatibility_status: status,
        effective_from: new Date().toISOString(),
        reason: reason || undefined,
      },
    ]);
    setTarget("");
    setSearch("");
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
        {location.kind === "storage" && (
          <label>
            <span>Storage location</span>
            <select
              value={String(location.storage_location_code ?? "")}
              onChange={(e) =>
                onLocationChange({
                  ...location,
                  storage_location_code: e.target.value || null,
                })
              }
            >
              <option value="">Select a storage location</option>
              {(storage.data ?? []).map((item) => (
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
          <span>Search {type === "eoat-machine" ? "machines" : "Tools"}</span>
          <input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setTarget("");
            }}
            placeholder="Type an identifier or name"
          />
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
