import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { apiClient } from "@/api/client";
import { EntityEditor } from "@/components/profile/EntityEditor";
import { ErrorState, LoadingState } from "@/components/feedback/StateViews";

/** Dedicated, wide editing route; the profile remains the read-only record view. */
export function EditEoatPage() {
  const { identifier } = useParams();
  const profile = useQuery({
    queryKey: ["eoat", identifier],
    queryFn: () => apiClient.getEoatProfile(identifier!),
    enabled: Boolean(identifier),
  });
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
              key: "status",
              label: "Status",
              value: value.status,
              catalog: "status",
            },
            { key: "revision", label: "Revision", value: value.revision },
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
              key: "notes",
              label: "Notes",
              kind: "textarea",
              value: value.notes,
            },
          ]}
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
