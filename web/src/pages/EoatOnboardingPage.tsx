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
  verification_source?: string;
  verified_at?: string;
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
const commandCenterDefaults: Identity = {
  status: "In Progress",
  priority: "Medium",
  follow_up_needed: "No",
  air_circuit_architecture: "Robot Only",
  robot_interchangeable_circuits: 0,
  external_vacuum_circuits: "N/A",
  external_pressure_circuits: "N/A",
  external_interchangeable_circuits: "N/A",
  tubing_condition: "Unknown / Not Checked",
  cable_management_condition: "Unknown / Not Checked",
  mounting_hardware_condition: "Unknown / Not Checked",
  eoat_alignment_condition: "Unknown / Not Checked",
  fastener_locking_hardware_present: "Unknown / Not Checked",
  cycle_time_concern: "Unknown / Not Checked",
  scrap_quality_concern: "Unknown / Not Checked",
  changeover_difficulty: "Unknown / Not Checked",
  spare_parts_identified: "No",
  drawing_cad_available: "No",
  bom_available: "No",
  process_binder_complete: "No",
  photos_taken: "No",
  pilot_candidate: "No",
  pneumatic_quick_disconnect_type: "PTC",
};
const requiredCommandCenterKeys = new Set([
  "audit_context",
  "priority",
  "follow_up_needed",
  "eoat_moves",
  "part_family",
  "part_name_description",
  "air_circuit_architecture",
  "robot_vacuum_circuits",
  "robot_pressure_circuits",
  "robot_interchangeable_circuits",
  "pneumatic_quick_disconnect_type",
  "tubing_condition",
  "mounting_hardware_condition",
  "fastener_locking_hardware_present",
  "cycle_time_concern",
  "scrap_quality_concern",
  "changeover_difficulty",
  "spare_parts_identified",
  "drawing_cad_available",
  "bom_available",
  "process_binder_complete",
  "photos_taken",
]);
const commandCenterFields: Array<{
  key: string;
  label: string;
  options?: string[];
  type?: "text" | "number";
  wide?: boolean;
}> = [
  {
    key: "audit_context",
    label: "Audit context",
    options: [
      "Installed on Machine",
      "Not Installed / Bench Audit",
      "Compatibility row",
      "Historical/imported",
      "Needs review",
    ],
  },
  {
    key: "priority",
    label: "Priority",
    options: ["Low", "Medium", "High", "Critical"],
  },
  {
    key: "follow_up_needed",
    label: "Follow-up needed",
    options: ["Yes", "No"],
  },
  {
    key: "eoat_moves",
    label: "EOAT moves",
    options: ["Part", "Sprue", "Both"],
  },
  { key: "part_family", label: "Part family" },
  {
    key: "part_name_description",
    label: "Part name / description",
    wide: true,
  },
  {
    key: "robot_type",
    label: "Robot type",
    options: ["Wittmann R8", "Wittmann R9", "Engel Viper", "Other", "Unknown"],
  },
  { key: "robot_model_controller", label: "Robot model / controller" },
  {
    key: "air_circuit_architecture",
    label: "Air circuit architecture",
    options: [
      "Robot Only",
      "External Peripheral Only",
      "Mixed Robot + External Peripheral",
      "Unknown / Needs Verification",
    ],
  },
  {
    key: "robot_vacuum_circuits",
    label: "Robot vacuum circuits",
    type: "number",
  },
  {
    key: "robot_pressure_circuits",
    label: "Robot pressure circuits",
    type: "number",
  },
  {
    key: "robot_interchangeable_circuits",
    label: "Robot interchangeable circuits",
    type: "number",
  },
  { key: "external_vacuum_circuits", label: "External vacuum circuits" },
  { key: "external_pressure_circuits", label: "External pressure circuits" },
  {
    key: "external_interchangeable_circuits",
    label: "External interchangeable circuits",
  },
  { key: "robot_notes", label: "Robot notes", wide: true },
  {
    key: "pneumatic_quick_disconnect_type",
    label: "Pneumatic quick disconnect type",
  },
  {
    key: "electrical_quick_disconnect_type",
    label: "Electrical quick disconnect type",
  },
  {
    key: "tubing_condition",
    label: "Tubing condition",
    options: [
      "OK",
      "Worn",
      "Damaged",
      "Poor Routing",
      "Needs Follow-Up",
      "Unknown / Not Checked",
    ],
  },
  { key: "tubing_routing_notes", label: "Tubing routing notes", wide: true },
  {
    key: "cable_management_condition",
    label: "Cable management condition",
    options: [
      "OK",
      "Loose",
      "Damaged",
      "Poor Routing",
      "Needs Follow-Up",
      "Unknown / Not Checked",
    ],
  },
  {
    key: "mounting_hardware_condition",
    label: "Mounting hardware condition",
    options: [
      "OK",
      "Loose",
      "Missing Hardware",
      "Damaged",
      "Needs Follow-Up",
      "Unknown / Not Checked",
    ],
  },
  {
    key: "eoat_alignment_condition",
    label: "EOAT alignment condition",
    options: [
      "OK",
      "Slightly Off",
      "Misaligned",
      "Needs Follow-Up",
      "Unknown / Not Checked",
    ],
  },
  {
    key: "fastener_locking_hardware_present",
    label: "Fastener / locking hardware",
    options: ["Yes", "No", "Partial", "Unknown / Not Checked"],
  },
  { key: "known_issues", label: "Known issues", wide: true },
  { key: "drop_mispick_history", label: "Drop / mis-pick history", wide: true },
  { key: "maintenance_frequency", label: "Maintenance frequency" },
  {
    key: "cycle_time_concern",
    label: "Cycle time concern",
    options: ["Yes", "No", "Unknown / Not Checked"],
  },
  {
    key: "scrap_quality_concern",
    label: "Scrap / quality concern",
    options: ["Yes", "No", "Unknown / Not Checked"],
  },
  {
    key: "changeover_difficulty",
    label: "Changeover difficulty",
    options: ["Easy", "Low", "Medium", "High", "Unknown / Not Checked"],
  },
  {
    key: "spare_parts_identified",
    label: "Spare parts identified",
    options: ["Yes", "No", "Partial", "Unknown / Not Checked"],
  },
  {
    key: "drawing_cad_available",
    label: "Drawing / CAD available",
    options: ["Yes", "No", "Unknown / Not Checked"],
  },
  {
    key: "bom_available",
    label: "BOM available",
    options: ["Yes", "No", "Unknown / Not Checked"],
  },
  {
    key: "process_binder_complete",
    label: "Process binder complete",
    options: ["Yes", "No", "Partial", "Unknown / Not Checked"],
  },
  { key: "photos_taken", label: "Photos taken", options: ["Yes", "No"] },
  {
    key: "pilot_candidate",
    label: "Pilot candidate",
    options: ["Yes", "No", "Maybe"],
  },
];

type StepVisualState =
  "not-started" | "needs-attention" | "complete" | "warning" | "error";

function StepNavigation({
  step,
  stepComplete,
  reviewWarnings,
  reviewErrors,
  busy,
  onStepChange,
  mobile = false,
}: {
  step: number;
  stepComplete: boolean[];
  reviewWarnings: boolean;
  reviewErrors: boolean;
  busy: boolean;
  onStepChange: (next: number) => void;
  mobile?: boolean;
}) {
  const stateFor = (index: number): StepVisualState => {
    if (index === steps.length - 1 && reviewErrors) return "error";
    if (index === steps.length - 1 && reviewWarnings) return "warning";
    if (stepComplete[index]) return "complete";
    return index === step ? "needs-attention" : "not-started";
  };
  const statusLabel = (state: StepVisualState) =>
    state === "complete"
      ? "Complete"
      : state === "error"
        ? "Needs attention"
        : state === "warning"
          ? "Warning"
          : state === "needs-attention"
            ? "Needs attention"
            : "Not started";
  const list = (
    <nav
      className={mobile ? "onboarding-mobile-step-list" : "onboarding-steps"}
      aria-label={
        mobile ? "Onboarding section selector" : "Onboarding sections"
      }
    >
      {steps.map((label, index) => {
        const state = stateFor(index);
        const status = statusLabel(state);
        return (
          <button
            type="button"
            key={label}
            className={`onboarding-step is-${state}${index === step ? " is-current" : ""}`}
            onClick={() => onStepChange(index)}
            disabled={busy}
            aria-current={index === step ? "step" : undefined}
            aria-label={`Step ${index + 1}: ${label}. ${status}.`}
          >
            <span className="onboarding-step-number" aria-hidden="true">
              {index + 1}
            </span>
            <span className="onboarding-step-copy">
              <strong>{label}</strong>
              <small>{state === "complete" ? "Complete ✓" : status}</small>
            </span>
          </button>
        );
      })}
    </nav>
  );
  if (!mobile) return list;
  return (
    <details className="onboarding-mobile-steps">
      <summary>
        <span>
          Step {step + 1} of {steps.length}
        </span>
        <strong>{steps[step]}</strong>
        <progress
          value={step + 1}
          max={steps.length}
          aria-label={`Step ${step + 1} of ${steps.length}`}
        />
      </summary>
      {list}
    </details>
  );
}

function payloadOf(draft: OnboardingDraft | null) {
  return (draft?.payload ?? {}) as {
    identity?: Identity;
    engineering?: Identity;
    command_center?: Identity;
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
    revision: "",
    vacuum_present: null,
    sensors_present: null,
    number_of_vacuum_cups: null,
    number_of_grippers: null,
    notes: "",
    cleanroom_classification: "cleanroom",
  });
  const [plantCode, setPlantCode] = useState("");
  const [areaCode, setAreaCode] = useState("");
  const [engineering, setEngineering] = useState<Identity>({
    cylinders_present: null,
    cylinder_count: null,
    cylinder_model: "",
    gripper_model: "",
    electrical_present: null,
    electrical_connection: "",
    sensor_models: "",
    vacuum_generation: "Venturi",
    pneumatic_connection: "PTC",
  });
  const [commandCenter, setCommandCenter] = useState<Identity>(
    commandCenterDefaults,
  );
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
  const [finalizedIdentifier, setFinalizedIdentifier] = useState<string | null>(
    null,
  );
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
        setCommandCenter({
          ...commandCenterDefaults,
          ...((payload.command_center ?? {}) as Identity),
        });
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
  const mayEdit = sessionHasPermission(session, "onboarding.draft.edit");
  const mayReview = sessionHasPermission(session, "onboarding.draft.review");
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
  const hasReviewWarnings = Boolean(review.data?.warnings.length);
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
      command_center: commandCenter,
      compatibility,
      location,
    }),
    [commandCenter, compatibility, engineering, identity, location],
  );
  useEffect(() => {
    if (!draft?.draft_uuid || !mayEdit) return;
    setSaveStatus("Changes pending…");
    const timer = window.setTimeout(() => {
      const current = draftRef.current;
      if (!current) return;
      setSaveStatus("Saving…");
      void apiClient
        .saveOnboardingDraft(current.draft_uuid, {
          proposed_identifier: String(identity.business_identifier || ""),
          plant_code: plantCode || null,
          area_code: areaCode || null,
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
  }, [
    areaCode,
    draft?.draft_uuid,
    identity.business_identifier,
    mayEdit,
    payload,
    plantCode,
  ]);
  useEffect(() => {
    if (saveStatus !== "Changes pending…" && saveStatus !== "Saving…") return;
    const warnBeforeLeaving = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnBeforeLeaving);
    return () => window.removeEventListener("beforeunload", warnBeforeLeaving);
  }, [saveStatus]);
  async function save(): Promise<boolean> {
    if (draft ? !mayEdit : !mayCreate) return false;
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
      return true;
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "Draft save failed. Your unsaved fields remain on this device.",
      );
      return false;
    } finally {
      setBusy(false);
    }
  }
  async function startAndContinue() {
    if (await save()) setStep(1);
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
    if (!plantCode) {
      setError(
        "Select a plant code before generating an identifier.",
      );
      return;
    }
    if ((draft && !mayEdit) || (!draft && !mayCreate)) return;
    setBusy(true);
    setError("");
    try {
      const body = {
        proposed_identifier: String(identity.business_identifier || ""),
        plant_code: plantCode || null,
        area_code: areaCode || null,
        payload,
      };
      const saved = draft
        ? await apiClient.saveOnboardingDraft(draft.draft_uuid, {
            ...body,
            expected_row_version: draft.row_version,
          })
        : await apiClient.createOnboardingDraft(body);
      draftRef.current = saved;
      setDraft(saved);
      if (!draft) navigate(`/eoats/new/${saved.draft_uuid}`, { replace: true });
      const generated = await apiClient.generateOnboardingIdentifier(
        saved.draft_uuid,
        saved.row_version,
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
        reason instanceof ApiError
          ? reason.message
          : "An identifier could not be generated.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function uploadMedia() {
    if (!draft || !mayEdit || !selectedMedia || !mediaTitle) return;
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
          caption:
            mediaKind === "photo" ? mediaCaption || undefined : undefined,
          description:
            mediaKind === "document" ? mediaCaption || undefined : undefined,
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
    if (!draft || !mayEdit) return;
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
        reason instanceof ApiError
          ? reason.message
          : "Media could not be removed.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function discard() {
    if (!draft || !mayDiscard) return;
    if (
      !window.confirm(
        "Discard this onboarding draft? This keeps an audited record but releases its identifier reservation.",
      )
    )
      return;
    setBusy(true);
    setError("");
    try {
      await apiClient.discardOnboardingDraft(
        draft.draft_uuid,
        draft.row_version,
      );
      navigate("/eoats/onboarding-drafts", { replace: true });
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.message
          : "The onboarding draft could not be discarded.",
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
            <Link
              className="profile-edit-button"
              to={`/eoats/${encodeURIComponent(finalizedIdentifier)}`}
            >
              View profile
            </Link>{" "}
            {mayCreate && (
              <Link className="profile-edit-button" to="/eoats/new">
                Add another EOAT
              </Link>
            )}
          </p>
          <QrLabel category="eoat" identifier={finalizedIdentifier} />
        </section>
      </section>
    );
  if (
    (!draftUuid && !mayCreate) ||
    (draftUuid && !mayEdit && !mayReview && !mayFinalize)
  )
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
        {draft && !mayEdit && (
          <p className="onboarding-save-status" role="status">
            You can review this draft, but you do not have permission to change
            it.
          </p>
        )}
      </header>
      <div className="onboarding-workspace">
        <StepNavigation
          step={step}
          stepComplete={stepComplete}
          reviewWarnings={hasReviewWarnings}
          reviewErrors={hasBlockingReviewErrors}
          busy={busy}
          onStepChange={setStep}
        />
        <div className="onboarding-content">
          <StepNavigation
            step={step}
            stepComplete={stepComplete}
            reviewWarnings={hasReviewWarnings}
            reviewErrors={hasBlockingReviewErrors}
            busy={busy}
            onStepChange={setStep}
            mobile
          />
          <section className="onboarding-card">
            <fieldset
              className="onboarding-fields"
              disabled={busy || (Boolean(draft) && !mayEdit)}
            >
              {step === 0 && (
                <div className="onboarding-grid">
                  <div className="onboarding-field-heading">
                    <h2>Asset identity</h2>
                    <p>Identify the physical EOAT and its governed record.</p>
                  </div>
                  <label>
                    <span>Plant code *</span>
                    <select
                      value={plantCode}
                      onChange={(event) => setPlantCode(event.target.value)}
                      required
                    >
                      <option value="">Select a plant</option>
                      <option value="P4">Plant 4</option>
                      <option value="P7">Plant 7</option>
                      <option value="CL">Cleanroom</option>
                    </select>
                  </label>
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
                  <button
                    type="button"
                    disabled={
                      busy ||
                      !plantCode ||
                      (draft ? !mayEdit : !mayCreate)
                    }
                    onClick={() => void generateIdentifier()}
                  >
                    Generate next identifier
                  </button>
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
                  <div className="onboarding-field-heading">
                    <h2>Classification</h2>
                    <p>Describe how this EOAT is categorized and connected.</p>
                  </div>
                  <SelectField
                    label="EOAT type"
                    value={identity.eoat_type}
                    onChange={(value) =>
                      setIdentity({ ...identity, eoat_type: value })
                    }
                    options={[
                      { value: "vacuum", label: "Vacuum" },
                      {
                        value: "mechanical_gripper",
                        label: "Mechanical / Gripper",
                      },
                      { value: "hybrid", label: "Hybrid" },
                      {
                        value: "unknown_needs_review",
                        label: "Unknown / Needs Review",
                      },
                      { value: "miscellaneous", label: "Miscellaneous" },
                    ]}
                    required
                  />
                  <SelectField
                    label="Status"
                    value={commandCenter.status}
                    onChange={(value) =>
                      setCommandCenter({ ...commandCenter, status: value })
                    }
                    options={[
                      "Not Started",
                      "In Progress",
                      "Complete",
                      "Needs Follow-Up",
                      "Blocked",
                    ]}
                    required
                  />
                  <SelectField
                    label="Robot connection / interface"
                    value={identity.connection_type}
                    onChange={(value) => {
                      setIdentity({ ...identity, connection_type: value });
                      setCommandCenter((current) => ({
                        ...current,
                        changeover_difficulty:
                          current.changeover_difficulty ===
                            "Unknown / Not Checked" ||
                          !current.changeover_difficulty
                            ? value === "ati"
                              ? "Low"
                              : value === "dovetail"
                                ? "Medium"
                                : current.changeover_difficulty
                            : current.changeover_difficulty,
                      }));
                    }}
                    options={[
                      { value: "ati", label: "ATI" },
                      { value: "dovetail", label: "DoveTail" },
                      { value: "direct_mount", label: "Direct Mount" },
                      { value: "lever_lock", label: "Lever Lock" },
                    ]}
                    required
                  />
                  <SelectField
                    label="Environment / classification"
                    value={identity.cleanroom_classification}
                    onChange={(value) =>
                      setIdentity({
                        ...identity,
                        cleanroom_classification: value,
                      })
                    }
                    options={[
                      { value: "cleanroom", label: "Cleanroom" },
                      { value: "non_cleanroom", label: "Non-Cleanroom" },
                      { value: "whiteroom", label: "Whiteroom" },
                      {
                        value: "unknown_not_checked",
                        label: "Unknown / Not Checked",
                      },
                    ]}
                    required
                  />
                  <div className="onboarding-field-heading">
                    <h2>Lifecycle</h2>
                    <p>Capture the revision and important lifecycle dates.</p>
                  </div>
                  <Field
                    label="Revision"
                    value={identity.revision}
                    onChange={(value) =>
                      setIdentity({ ...identity, revision: value })
                    }
                  />
                  <Field
                    label="Date built"
                    type="date"
                    value={identity.date_built}
                    onChange={(value) =>
                      setIdentity({ ...identity, date_built: value || null })
                    }
                  />
                  <Field
                    label="Date commissioned"
                    type="date"
                    value={identity.date_commissioned}
                    onChange={(value) =>
                      setIdentity({
                        ...identity,
                        date_commissioned: value || null,
                      })
                    }
                  />
                  <div className="onboarding-field-heading">
                    <h2>Description</h2>
                    <p>
                      Record context that helps colleagues identify and use this
                      EOAT.
                    </p>
                  </div>
                  <label className="wide">
                    <span>Description / part information</span>
                    <textarea
                      value={String(identity.description ?? "")}
                      onChange={(e) =>
                        setIdentity({
                          ...identity,
                          description: e.target.value,
                        })
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
                  <div className="onboarding-field-heading">
                    <h2>Pickup hardware</h2>
                    <p>
                      Record the pickup, frame, and actuation details without
                      changing unknown values.
                    </p>
                  </div>
                  <BooleanField
                    label="Vacuum present"
                    value={identity.vacuum_present}
                    onChange={(value) =>
                      setIdentity({ ...identity, vacuum_present: value })
                    }
                    required
                  />
                  <Field
                    label="Parts picked"
                    type="number"
                    value={identity.number_of_parts_picked}
                    onChange={(value) =>
                      setIdentity({
                        ...identity,
                        number_of_parts_picked:
                          value === "" ? null : Number(value),
                      })
                    }
                    required
                  />
                  <Field
                    label="Vacuum cups"
                    type="number"
                    value={identity.number_of_vacuum_cups}
                    onChange={(value) =>
                      setIdentity({
                        ...identity,
                        number_of_vacuum_cups:
                          value === "" ? null : Number(value),
                      })
                    }
                    required={identity.vacuum_present === true}
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
                    required={
                      identity.eoat_type === "mechanical_gripper" ||
                      identity.eoat_type === "hybrid"
                    }
                  />
                  <BooleanField
                    label="Quick disconnect present"
                    value={identity.quick_disconnect_present}
                    onChange={(value) =>
                      setIdentity({
                        ...identity,
                        quick_disconnect_present: value,
                      })
                    }
                    required
                  />
                  <Field
                    label="Cup material"
                    value={identity.cup_material}
                    onChange={(value) =>
                      setIdentity({ ...identity, cup_material: value })
                    }
                    required={identity.vacuum_present === true}
                  />
                  <Field
                    label="Frame material"
                    value={identity.frame_material}
                    onChange={(value) =>
                      setIdentity({ ...identity, frame_material: value })
                    }
                  />
                  <Field
                    label="Weight (kg)"
                    type="number"
                    value={identity.weight_kg}
                    onChange={(value) =>
                      setIdentity({
                        ...identity,
                        weight_kg: value === "" ? null : Number(value),
                      })
                    }
                    required
                  />
                  <Field
                    label="Maximum payload (kg)"
                    type="number"
                    value={identity.maximum_payload_kg}
                    onChange={(value) =>
                      setIdentity({
                        ...identity,
                        maximum_payload_kg: value === "" ? null : Number(value),
                      })
                    }
                  />
                  <Field
                    label="Drawing number"
                    value={identity.drawing_number}
                    onChange={(value) =>
                      setIdentity({ ...identity, drawing_number: value })
                    }
                  />
                  <Field
                    label="Manufacturer"
                    value={identity.manufacturer}
                    onChange={(value) =>
                      setIdentity({ ...identity, manufacturer: value })
                    }
                  />
                  <BooleanField
                    label="Cylinders present"
                    value={engineering.cylinders_present}
                    onChange={(value) =>
                      setEngineering({
                        ...engineering,
                        cylinders_present: value,
                      })
                    }
                    required
                  />
                  {engineering.cylinders_present !== false && (
                    <>
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
                        required={engineering.cylinders_present === true}
                      />
                      <Field
                        label="Cylinder model"
                        value={engineering.cylinder_model}
                        onChange={(value) =>
                          setEngineering({
                            ...engineering,
                            cylinder_model: value,
                          })
                        }
                        required={engineering.cylinders_present === true}
                      />
                      <SelectField
                        label="Cylinder type"
                        value={engineering.cylinder_type}
                        onChange={(value) =>
                          setEngineering({
                            ...engineering,
                            cylinder_type: value,
                          })
                        }
                        options={["Linear", "Rotary"]}
                        required={engineering.cylinders_present === true}
                      />
                    </>
                  )}
                  {identity.number_of_grippers !== 0 && (
                    <>
                      <SelectField
                        label="Gripper type"
                        value={engineering.gripper_type}
                        onChange={(value) =>
                          setEngineering({
                            ...engineering,
                            gripper_type: value,
                          })
                        }
                        options={["Single Pressure", "Double Pressure"]}
                        required={Number(identity.number_of_grippers ?? 0) > 0}
                      />
                      <SelectField
                        label="Gripper model"
                        value={engineering.gripper_model}
                        onChange={(value) =>
                          setEngineering({
                            ...engineering,
                            gripper_model: value,
                          })
                        }
                        options={[
                          "Large Double Gripper",
                          "Small Double Gripper",
                        ]}
                        required={Number(identity.number_of_grippers ?? 0) > 0}
                      />
                      <Field
                        label="Gripper size"
                        value={engineering.gripper_size}
                        onChange={(value) =>
                          setEngineering({
                            ...engineering,
                            gripper_size: value,
                          })
                        }
                      />
                    </>
                  )}
                  {identity.vacuum_present !== false && (
                    <>
                      <Field
                        label="Vacuum cup type"
                        value={engineering.vacuum_cup_type}
                        onChange={(value) =>
                          setEngineering({
                            ...engineering,
                            vacuum_cup_type: value,
                          })
                        }
                        required={identity.vacuum_present === true}
                      />
                      <Field
                        label="Vacuum cup size"
                        value={engineering.vacuum_cup_size}
                        onChange={(value) =>
                          setEngineering({
                            ...engineering,
                            vacuum_cup_size: value,
                          })
                        }
                        required={identity.vacuum_present === true}
                      />
                      <Field
                        label="Vacuum cup model"
                        value={engineering.vacuum_cup_model}
                        onChange={(value) =>
                          setEngineering({
                            ...engineering,
                            vacuum_cup_model: value,
                          })
                        }
                      />
                      <Field
                        label="Vacuum generation"
                        value={engineering.vacuum_generation}
                        onChange={(value) =>
                          setEngineering({
                            ...engineering,
                            vacuum_generation: value,
                          })
                        }
                        required={identity.vacuum_present === true}
                      />
                    </>
                  )}
                </div>
              )}
              {step === 2 && (
                <div className="onboarding-grid">
                  <div className="onboarding-field-heading">
                    <h2>Pneumatics &amp; sensors</h2>
                    <p>
                      Capture controls, sensors, and circuit details that
                      support safe operation.
                    </p>
                  </div>
                  <BooleanField
                    label="Sensors present"
                    value={identity.sensors_present}
                    onChange={(value) =>
                      setIdentity({ ...identity, sensors_present: value })
                    }
                    required
                  />
                  {identity.sensors_present !== false && (
                    <>
                      <Field
                        label="Sensor models"
                        value={engineering.sensor_models}
                        onChange={(value) =>
                          setEngineering({
                            ...engineering,
                            sensor_models: value,
                          })
                        }
                        required={identity.sensors_present === true}
                      />
                      <Field
                        label="Sensor types"
                        value={engineering.sensor_types}
                        onChange={(value) =>
                          setEngineering({
                            ...engineering,
                            sensor_types: value,
                          })
                        }
                        required={identity.sensors_present === true}
                      />
                      <BooleanField
                        label="Part-present sensor"
                        value={identity.part_present_sensor_present}
                        onChange={(value) => {
                          setIdentity({
                            ...identity,
                            part_present_sensor_present: value,
                          });
                          if (value === true) {
                            setEngineering((current) => ({
                              ...current,
                              sensor_types:
                                current.sensor_types || "Reed Switch",
                              sensor_models: current.sensor_models || "SMC",
                            }));
                          }
                        }}
                        required={identity.sensors_present === true}
                      />
                    </>
                  )}
                  <BooleanField
                    label="Vacuum-confirmation sensor"
                    value={identity.vacuum_confirmation_sensor_present}
                    onChange={(value) =>
                      setIdentity({
                        ...identity,
                        vacuum_confirmation_sensor_present: value,
                      })
                    }
                  />
                  <BooleanField
                    label="Electrical present"
                    value={engineering.electrical_present}
                    onChange={(value) =>
                      setEngineering({
                        ...engineering,
                        electrical_present: value,
                      })
                    }
                    required
                  />
                  {engineering.electrical_present !== false && (
                    <>
                      <Field
                        label="Electrical connection"
                        value={engineering.electrical_connection}
                        onChange={(value) =>
                          setEngineering({
                            ...engineering,
                            electrical_connection: value,
                          })
                        }
                      />
                      <Field
                        label="Electrical pinout reference"
                        value={engineering.electrical_pinout_reference}
                        onChange={(value) =>
                          setEngineering({
                            ...engineering,
                            electrical_pinout_reference: value,
                          })
                        }
                      />
                    </>
                  )}
                  {identity.vacuum_present !== false && (
                    <Field
                      label="Vacuum circuits"
                      type="number"
                      value={engineering.vacuum_circuits}
                      onChange={(value) =>
                        setEngineering({
                          ...engineering,
                          vacuum_circuits: value === "" ? null : Number(value),
                        })
                      }
                      required={identity.vacuum_present === true}
                    />
                  )}
                  <Field
                    label="Pressure circuits"
                    type="number"
                    value={engineering.pressure_circuits}
                    onChange={(value) =>
                      setEngineering({
                        ...engineering,
                        pressure_circuits: value === "" ? null : Number(value),
                      })
                    }
                    required
                  />
                  <Field
                    label="Interchangeable circuits"
                    type="number"
                    value={engineering.interchangeable_circuits}
                    onChange={(value) =>
                      setEngineering({
                        ...engineering,
                        interchangeable_circuits:
                          value === "" ? null : Number(value),
                      })
                    }
                    required
                  />
                  <Field
                    label="External circuits"
                    type="number"
                    value={engineering.external_circuits}
                    onChange={(value) =>
                      setEngineering({
                        ...engineering,
                        external_circuits: value === "" ? null : Number(value),
                      })
                    }
                  />
                  <Field
                    label="Pneumatic connection"
                    value={engineering.pneumatic_connection}
                    onChange={(value) =>
                      setEngineering({
                        ...engineering,
                        pneumatic_connection: value,
                      })
                    }
                    required
                  />
                  <label className="wide">
                    <span>Pneumatic notes</span>
                    <textarea
                      value={String(engineering.pneumatic_notes ?? "")}
                      onChange={(event) =>
                        setEngineering({
                          ...engineering,
                          pneumatic_notes: event.target.value,
                        })
                      }
                    />
                  </label>
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
                  <div className="onboarding-field-heading">
                    <h2>Command Center engineering &amp; inspection data</h2>
                    <p>
                      These are the controlled operational fields carried from
                      the original Command Center workflow.
                    </p>
                  </div>
                  <CommandCenterDataFields
                    values={commandCenter}
                    onChange={setCommandCenter}
                  />
                  <h2>Photos & Documents</h2>
                  <p>
                    Files remain staged outside the normal EOAT media library
                    until successful finalization.
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
                          <option value="FRONT">
                            Front / profile candidate
                          </option>
                          <option value="BACK">Back / pickup face</option>
                          <option value="SIDE">Side</option>
                          <option value="CONNECTION">
                            Robot connection / mounting interface
                          </option>
                          <option value="VACUUM">Vacuum cups / grippers</option>
                          <option value="SENSORS">Sensors</option>
                          <option value="PNEUMATICS">
                            Tubing / pneumatics
                          </option>
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
                      !mayEdit ||
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
                            {media.media_kind === "photo"
                              ? "Photo"
                              : "Document"}
                            : {media.title} · {media.file_name}
                          </span>
                          <button
                            type="button"
                            disabled={busy || !mayEdit}
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
            </fieldset>
            {step === 5 && (
              <div>
                <h2>Review</h2>
                <p>
                  {complete
                    ? "Core identity fields are present. Final validation will re-check every required field, the identifier, permissions, references, and staged media."
                    : "Blocking: enter an identifier and EOAT type before finalization."}
                </p>
                <p>
                  Draft status: {draft ? draft.completion_state : "Not saved"}
                </p>
                {review.isPending && draft && (
                  <p>Checking current records and staged media…</p>
                )}
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
                  <p role="alert">
                    The server review could not be completed. Finalization
                    remains protected.
                  </p>
                )}
              </div>
            )}
            {error && (
              <p role="alert" className="entity-editor-error">
                {error}
              </p>
            )}
            <footer
              className="onboarding-action-footer"
              aria-label="Onboarding actions"
            >
              <button
                type="button"
                className="onboarding-action onboarding-action--ghost"
                onClick={() => setStep(Math.max(0, step - 1))}
                disabled={step === 0 || busy}
              >
                ← Back
              </button>
              <div className="onboarding-action-footer__primary">
                {draft && mayDiscard && (
                  <button
                    type="button"
                    className="onboarding-action onboarding-action--danger"
                    onClick={() => void discard()}
                    disabled={busy}
                  >
                    Discard draft
                  </button>
                )}
                {!draft ? (
                  <button
                    type="button"
                    className="onboarding-action onboarding-action--primary"
                    onClick={() => void startAndContinue()}
                    disabled={busy || !mayCreate}
                  >
                    {busy ? "Starting…" : "Start Draft & Continue →"}
                  </button>
                ) : step < steps.length - 1 ? (
                  <>
                    <button
                      type="button"
                      className="onboarding-action onboarding-action--secondary"
                      onClick={() => void save()}
                      disabled={busy || !mayEdit}
                    >
                      {busy ? "Saving…" : "Save Draft"}
                    </button>
                    <button
                      type="button"
                      className="onboarding-action onboarding-action--primary"
                      onClick={() => setStep(step + 1)}
                      disabled={busy}
                    >
                      Continue →
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="onboarding-action onboarding-action--primary"
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
                    {mayFinalize
                      ? "Finalize EOAT"
                      : "Finalization approval required"}
                  </button>
                )}
              </div>
            </footer>
          </section>
        </div>
      </div>
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
  const sources = useQuery({
    queryKey: ["onboarding", "compatibility-sources"],
    queryFn: () => apiClient.getCatalogOptions("compatibility_source"),
  });
  const storage = useQuery({
    queryKey: ["onboarding", "storage"],
    queryFn: () => apiClient.getCatalogOptions("storage"),
  });
  const [type, setType] =
    useState<CompatibilityDraft["relationship_type"]>("eoat-machine");
  const [target, setTarget] = useState("");
  const [status, setStatus] = useState("");
  const [source, setSource] = useState("");
  const [verifiedAt, setVerifiedAt] = useState("");
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
        verification_source: source || undefined,
        verified_at: verifiedAt
          ? new Date(`${verifiedAt}T00:00:00Z`).toISOString()
          : undefined,
      },
    ]);
    setTarget("");
    setSearch("");
    setStatus("");
    setSource("");
    setVerifiedAt("");
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
        <label>
          <span>Verification source</span>
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">Not recorded</option>
            {(sources.data ?? []).map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Verified date</span>
          <input
            type="date"
            value={verifiedAt}
            onChange={(e) => setVerifiedAt(e.target.value)}
          />
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
              {item.verification_source ? ` · ${item.verification_source}` : ""}
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
  type?: "text" | "number" | "date";
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
function SelectField({
  label,
  value,
  onChange,
  options,
  required = false,
}: {
  label: string;
  value: unknown;
  onChange: (value: string) => void;
  options: Array<string | { value: string; label: string }>;
  required?: boolean;
}) {
  return (
    <label>
      <span>
        {label}
        {required ? " *" : ""}
      </span>
      <select
        value={value == null ? "" : String(value)}
        onChange={(event) => onChange(event.target.value)}
        required={required}
      >
        <option value="">Select a value</option>
        {options.map((option) => {
          const item =
            typeof option === "string"
              ? { value: option, label: option }
              : option;
          return (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          );
        })}
      </select>
    </label>
  );
}
function CommandCenterDataFields({
  values,
  onChange,
}: {
  values: Identity;
  onChange: (next: Identity) => void;
}) {
  const setValue = (key: string, value: string, type?: "text" | "number") =>
    onChange({
      ...values,
      [key]: type === "number" ? (value === "" ? null : Number(value)) : value,
    });
  return (
    <div className="onboarding-grid">
      {commandCenterFields.map((field) =>
        field.options ? (
          <SelectField
            key={field.key}
            label={field.label}
            value={values[field.key]}
            onChange={(value) => setValue(field.key, value)}
            options={field.options}
            required={requiredCommandCenterKeys.has(field.key)}
          />
        ) : field.wide ? (
          <label className="wide" key={field.key}>
            <span>
              {field.label}
              {requiredCommandCenterKeys.has(field.key) ? " *" : ""}
            </span>
            <textarea
              value={String(values[field.key] ?? "")}
              onChange={(event) => setValue(field.key, event.target.value)}
              required={requiredCommandCenterKeys.has(field.key)}
            />
          </label>
        ) : (
          <Field
            key={field.key}
            label={field.label}
            type={field.type}
            value={values[field.key]}
            onChange={(value) => setValue(field.key, value, field.type)}
            required={requiredCommandCenterKeys.has(field.key)}
          />
        ),
      )}
    </div>
  );
}
function BooleanField({
  label,
  value,
  onChange,
  required = false,
}: {
  label: string;
  value: unknown;
  onChange: (value: boolean | null) => void;
  required?: boolean;
}) {
  return (
    <label>
      <span>
        {label}
        {required ? " *" : ""}
      </span>
      <select
        value={value == null ? "" : String(value)}
        onChange={(e) =>
          onChange(e.target.value === "" ? null : e.target.value === "true")
        }
        required={required}
      >
        <option value="">Unknown</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </select>
    </label>
  );
}
