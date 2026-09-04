import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { apiClient, sessionHasPermission } from "@/api/client";
import { ApiError } from "@/api/errors";
import { EntityEditor } from "@/components/profile/EntityEditor";
import { CompatibilityEditor } from "@/components/profile/CompatibilityEditor";
import { InstallationEditor } from "@/components/profile/InstallationEditor";
import { MediaUpload } from "@/components/profile/MediaUpload";
import { ErrorState, LoadingState } from "@/components/feedback/StateViews";

/** Dedicated, wide editing route; the profile remains the read-only record view. */
export function EditEoatPage() {
  const { identifier } = useParams();
  const onboardingStatus = useQuery({
    queryKey: ["onboarding", "status"],
    queryFn: () => apiClient.getOnboardingStatus(),
  });
  const profile = useQuery({
    queryKey: ["eoat", identifier],
    queryFn: () => apiClient.getEoatProfile(identifier!),
    enabled: Boolean(identifier) && onboardingStatus.data?.enabled === true,
  });
  if (onboardingStatus.isPending)
    return <LoadingState label="Checking EOAT editing availability…" />;
  if (onboardingStatus.isError)
    return <ErrorState error={onboardingStatus.error} />;
  if (!onboardingStatus.data?.enabled)
    return (
      <section className="onboarding-page">
        <header>
          <p className="eyebrow">Governed EOAT editing</p>
          <h1>EOAT editing unavailable</h1>
          <p>
            EOAT onboarding and the dedicated editor are not enabled in this
            environment.
          </p>
        </header>
      </section>
    );
  if (profile.isPending) return <LoadingState label="Loading EOAT editor…" />;
  if (profile.isError || !profile.data)
    return <ErrorState error={profile.error} />;
  const value = profile.data;
  return (
    <section className="onboarding-page">
      <header>
        <p className="eyebrow">Governed EOAT editing</p>
        <h1>Edit {value.business_identifier}</h1>
        <p>
          Changes use the existing optimistic version, audit, and history write
          path. Identifier changes are intentionally excluded.
        </p>
      </header>
      <section className="onboarding-card">
        <EntityEditor
          initialOpen
          kind="eoat"
          identifier={value.business_identifier}
          rowVersion={value.row_version}
          onSaved={() => void profile.refetch()}
          fields={[
            {
              key: "legacy_identifier",
              label: "Legacy identifier",
              value: value.legacy_identifier,
            },
            {
              key: "display_name",
              label: "Display name",
              value: value.display_name,
            },
            {
              key: "description",
              label: "Description",
              kind: "textarea",
              value: value.description,
            },
            {
              key: "eoat_type",
              label: "EOAT type",
              value: value.eoat_type,
              catalog: "eoat_type",
            },
            {
              key: "connection_type",
              label: "Connection type",
              value: value.connection_type,
              catalog: "connection_type",
            },
            {
              key: "cleanroom_classification",
              label: "Environment / classification",
              value: value.cleanroom_classification,
              catalog: "cleanroom",
            },
            {
              key: "status",
              label: "Status",
              value: value.status,
              catalog: "status",
            },
            { key: "revision", label: "Revision", value: value.revision },
            {
              key: "number_of_parts_picked",
              label: "Parts picked",
              kind: "number",
              value: value.number_of_parts_picked,
            },
            {
              key: "number_of_vacuum_cups",
              label: "Vacuum cups",
              kind: "number",
              value: value.number_of_vacuum_cups,
            },
            {
              key: "number_of_grippers",
              label: "Grippers",
              kind: "number",
              value: value.number_of_grippers,
            },
            {
              key: "vacuum_present",
              label: "Vacuum present",
              kind: "boolean",
              value: value.vacuum_present,
            },
            {
              key: "sensors_present",
              label: "Sensors present",
              kind: "boolean",
              value: value.sensors_present,
            },
            {
              key: "part_present_sensor_present",
              label: "Part-present sensor",
              kind: "boolean",
              value: value.part_present_sensor_present,
            },
            {
              key: "vacuum_confirmation_sensor_present",
              label: "Vacuum-confirmation sensor",
              kind: "boolean",
              value: value.vacuum_confirmation_sensor_present,
            },
            {
              key: "quick_disconnect_present",
              label: "Quick disconnect",
              kind: "boolean",
              value: value.quick_disconnect_present,
            },
            {
              key: "cup_material",
              label: "Cup material",
              value: value.cup_material,
            },
            {
              key: "frame_material",
              label: "Frame material",
              value: value.frame_material,
            },
            {
              key: "weight_kg",
              label: "Weight (kg)",
              kind: "number",
              value: value.weight_kg,
            },
            {
              key: "maximum_payload_kg",
              label: "Maximum payload (kg)",
              kind: "number",
              value: value.maximum_payload_kg,
            },
            {
              key: "drawing_number",
              label: "Drawing number",
              value: value.drawing_number,
            },
            {
              key: "manufacturer",
              label: "Manufacturer",
              value: value.manufacturer,
            },
            {
              key: "date_built",
              label: "Date built",
              kind: "date",
              value: value.date_built,
            },
            {
              key: "date_commissioned",
              label: "Date commissioned",
              kind: "date",
              value: value.date_commissioned,
            },
            {
              key: "notes",
              label: "Notes",
              kind: "textarea",
              value: value.notes,
            },
          ]}
        />
      </section>
      <EngineeringEditor identifier={value.business_identifier} />
      <ProfilePhotoSelector
        identifier={value.business_identifier}
        onSaved={() => void profile.refetch()}
      />
      <section className="onboarding-card">
        <h2>Assignment, compatibility, and media</h2>
        <p>
          These actions use the established governed paths and remain separate:
          current assignment does not imply compatibility.
        </p>
        <CompatibilityEditor
          kind="eoat"
          identifier={value.business_identifier}
          onSaved={() => void profile.refetch()}
        />
        <InstallationEditor
          identifier={value.business_identifier}
          rowVersion={value.row_version}
          onSaved={() => void profile.refetch()}
        />
        <MediaUpload
          entityType="eoat"
          identifier={value.business_identifier}
          onSaved={() => void profile.refetch()}
        />
      </section>
      <p>
        <Link to={`/eoats/${encodeURIComponent(value.business_identifier)}`}>
          Return to profile
        </Link>
      </p>
    </section>
  );
}

export function ProfilePhotoSelector({
  identifier,
  onSaved,
}: {
  identifier: string;
  onSaved: () => void;
}) {
  const session = useQuery({
    queryKey: ["auth", "session"],
    queryFn: () => apiClient.getAuthenticatedSession(),
  });
  const maySelect = sessionHasPermission(session.data, "photo.edit");
  const photos = useQuery({
    queryKey: ["eoat", identifier, "photos"],
    queryFn: () => apiClient.getEoatPhotos(identifier),
    enabled: maySelect,
  });
  const [busyUuid, setBusyUuid] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  if (!maySelect) return null;
  if (photos.isPending) return <LoadingState label="Loading EOAT photos…" />;
  if (photos.isError) return <ErrorState error={photos.error} />;
  if (!photos.data?.length) return null;
  async function select(documentUuid: string) {
    setBusyUuid(documentUuid);
    setMessage("");
    try {
      await apiClient.selectOnboardingProfilePhoto(identifier, documentUuid);
      await photos.refetch();
      onSaved();
      setMessage("Profile photo updated.");
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Profile photo could not be updated.");
    } finally {
      setBusyUuid(null);
    }
  }
  return (
    <section className="onboarding-card">
      <h2>Profile photo</h2>
      <p>Select the preferred EOAT photo. This uses the existing audited profile-photo change path.</p>
      <div className="onboarding-photo-selector">
        {photos.data.map((photo) => (
          <button
            type="button"
            key={photo.document_uuid}
            className={photo.is_profile_photo ? "selected" : undefined}
            aria-pressed={photo.is_profile_photo}
            disabled={Boolean(busyUuid) || photo.is_profile_photo}
            onClick={() => void select(photo.document_uuid)}
          >
            {photo.content_delivery_state === "AVAILABLE" && (
              <img src={apiClient.photoThumbnailUrl(photo.document_uuid)} alt="" />
            )}
            <span>{photo.title}</span>
            <small>{photo.is_profile_photo ? "Current profile photo" : "Set as profile photo"}</small>
          </button>
        ))}
      </div>
      {message && <p role="status">{message}</p>}
    </section>
  );
}

const engineeringFields = [
  ["cylinders_present", "Cylinders present", "boolean"],
  ["cylinder_count", "Cylinder count", "number"],
  ["cylinder_type", "Cylinder type", "text"],
  ["cylinder_model", "Cylinder model", "text"],
  ["gripper_type", "Gripper type", "text"],
  ["gripper_model", "Gripper model", "text"],
  ["gripper_size", "Gripper size", "text"],
  ["vacuum_cup_type", "Vacuum cup type", "text"],
  ["vacuum_cup_size", "Vacuum cup size", "text"],
  ["vacuum_cup_model", "Vacuum cup model", "text"],
  ["vacuum_generation", "Vacuum generation", "text"],
  ["vacuum_circuits", "Vacuum circuits", "number"],
  ["pressure_circuits", "Pressure circuits", "number"],
  ["interchangeable_circuits", "Interchangeable circuits", "number"],
  ["external_circuits", "External circuits", "number"],
  ["pneumatic_connection", "Pneumatic connection", "text"],
  ["pneumatic_notes", "Pneumatic notes", "textarea"],
  ["electrical_present", "Electrical present", "boolean"],
  ["electrical_connection", "Electrical connection", "text"],
  ["electrical_pinout_reference", "Electrical pinout reference", "text"],
  ["sensor_types", "Sensor types", "textarea"],
  ["sensor_models", "Sensor models", "textarea"],
] as const;

function EngineeringEditor({ identifier }: { identifier: string }) {
  const profile = useQuery({
    queryKey: ["eoat", identifier, "engineering"],
    queryFn: () => apiClient.getEoatEngineeringProfile(identifier),
  });
  const session = useQuery({
    queryKey: ["auth", "session"],
    queryFn: () => apiClient.getAuthenticatedSession(),
  });
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (profile.data) setValues(profile.data);
  }, [profile.data]);
  const mayEdit = sessionHasPermission(session.data, "eoat.edit");
  if (profile.isPending) return <LoadingState label="Loading engineering details…" />;
  if (profile.isError || !profile.data) return <ErrorState error={profile.error} />;
  const setValue = (key: string, value: unknown) =>
    setValues((current) => ({ ...current, [key]: value }));
  async function save() {
    setSaving(true);
    setMessage("");
    try {
      await apiClient.patchEoatEngineeringProfile(identifier, {
        ...values,
        expected_row_version: profile.data!.row_version,
      });
      await profile.refetch();
      setMessage("Engineering details saved.");
    } catch (error) {
      setMessage(
        error instanceof ApiError
          ? error.message
          : "Engineering details could not be saved.",
      );
    } finally {
      setSaving(false);
    }
  }
  return (
    <section className="onboarding-card">
      <h2>Engineering configuration</h2>
      <p>
        Unknown remains distinct from No or zero. Changes are version-protected
        and recorded in EOAT history.
      </p>
      <div className="onboarding-grid">
        {engineeringFields.map(([key, label, kind]) => (
          <label className={kind === "textarea" ? "wide" : undefined} key={key}>
            <span>{label}</span>
            {kind === "boolean" ? (
              <select
                value={values[key] == null ? "" : String(values[key])}
                disabled={!mayEdit || saving}
                onChange={(event) =>
                  setValue(
                    key,
                    event.target.value === ""
                      ? null
                      : event.target.value === "true",
                  )
                }
              >
                <option value="">Unknown</option>
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            ) : kind === "textarea" ? (
              <textarea
                value={String(values[key] ?? "")}
                disabled={!mayEdit || saving}
                onChange={(event) => setValue(key, event.target.value || null)}
              />
            ) : (
              <input
                type={kind}
                min={kind === "number" ? 0 : undefined}
                value={values[key] == null ? "" : String(values[key])}
                disabled={!mayEdit || saving}
                onChange={(event) =>
                  setValue(
                    key,
                    kind === "number"
                      ? event.target.value === "" ? null : Number(event.target.value)
                      : event.target.value || null,
                  )
                }
              />
            )}
          </label>
        ))}
      </div>
      {message && <p role="status">{message}</p>}
      <button type="button" disabled={!mayEdit || saving} onClick={() => void save()}>
        {saving ? "Saving…" : mayEdit ? "Save engineering details" : "EOAT edit permission required"}
      </button>
    </section>
  );
}
