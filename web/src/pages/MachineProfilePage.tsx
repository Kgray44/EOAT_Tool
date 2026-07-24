import { useEffect } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Link, useLocation } from "react-router-dom";
import { apiClient, type MachineProfile } from "@/api/client";
import { decodeRouteIdentifier } from "@/api/routes";
import { rememberItem } from "@/api/recent";
import { ApiError } from "@/api/errors";
import {
  ErrorState,
  LoadingState,
  NotFoundState,
} from "@/components/feedback/StateViews";
import {
  Attribute,
  DocumentList,
  EntityHeader,
  HistoryList,
  PhotoGallery,
  ProfileSection,
  RelationshipList,
} from "@/components/profile/ProfileBlocks";
import { QrLabel } from "@/components/qr/QrLabel";

function Retry({ retry }: { retry: () => void }) {
  return (
    <button className="retry-button" type="button" onClick={retry}>
      Retry
    </button>
  );
}

function assignmentLabel(value: string | null | undefined) {
  if (value === "UNKNOWN_NOT_VERIFIED") return "Not verified";
  if (value === "NONE_OBSERVED") return "No assignment observed";
  return value || "Not recorded";
}

function MachineContent({
  number,
  profile,
}: {
  number: string;
  profile: MachineProfile;
}) {
  const [setup, relationships, documents, photos, history] = useQueries({
    queries: [
      {
        queryKey: ["machine", number, "setup"],
        queryFn: () => apiClient.getMachineSetup(number),
      },
      {
        queryKey: ["machine", number, "relationships"],
        queryFn: () => apiClient.getMachineRelationships(number),
      },
      {
        queryKey: ["machine", number, "documents"],
        queryFn: () => apiClient.getMachineDocuments(number),
      },
      {
        queryKey: ["machine", number, "photos"],
        queryFn: () => apiClient.getMachinePhotos(number),
      },
      {
        queryKey: ["machine", number, "history"],
        queryFn: () => apiClient.getMachineHistory(number),
      },
    ],
  });
  useEffect(() => {
    rememberItem({
      category: "machine",
      identifier: number,
      label: profile.machine_name || number,
    });
  }, [number, profile.machine_name]);
  const resolvedRelationships =
    Array.from(
      new Map(
        (relationships.data ?? profile.relationships ?? []).map((value) => [
          `${value.relationship_type}:${value.identifier}`,
          value,
        ]),
      ).values(),
    );
  const overview = [
    ["Manufacturer", profile.manufacturer],
    ["Model", profile.model],
    ["Controller", profile.controller_type],
    ["Press capacity (tons)", profile.press_capacity_tons],
    ["Cleanroom classification", profile.cleanroom_classification],
  ] as const;
  const missingOverview = overview.filter(([, value]) => value === null || value === undefined || value === "").map(([label]) => label);

  return (
    <>
      <EntityHeader
        category="machine"
        identifier={profile.machine_number}
        title={profile.machine_name}
        summary={[
          ["Status", profile.status],
          [
            "Plant / area",
            [profile.plant_code, profile.area].filter(Boolean).join(" · "),
          ],
          ["Current EOAT", assignmentLabel(setup.data?.current_eoat || profile.current_eoat)],
          [
            "Assignment truth",
            setup.data?.verified ? "Verified" : "Unknown / not verified",
          ],
        ]}
      />
      <div className="profile-sections">
        <ProfileSection title="Overview">
          <dl className="attribute-grid">
            {overview.filter(([, value]) => value !== null && value !== undefined && value !== "").map(([label, value]) => <Attribute key={label} label={label} value={value} />)}
            <Attribute label="Active record" value={profile.is_active} booleanLabels={["Active", "Inactive"]} />
          </dl>
          {missingOverview.length > 0 && <p className="notes"><strong>Not recorded:</strong> {missingOverview.join(", ")}.</p>}
          {profile.notes && (
            <p className="notes">
              <strong>Notes:</strong> {profile.notes}
            </p>
          )}
        </ProfileSection>
        <ProfileSection title="Current assignment and compatibility">
          {setup.isPending && <LoadingState label="Loading current setup…" />}
          {setup.isError && (
            <>
              <ErrorState error={setup.error} title="Current assignment unavailable" />
              <Retry retry={() => setup.refetch()} />
            </>
          )}
          {setup.data && (
            <dl className="attribute-grid">
              <Attribute label="Current EOAT" value={assignmentLabel(setup.data.current_eoat)} />
              <Attribute
                label="Current tool / mold"
                value={assignmentLabel(setup.data.current_tool)}
              />
              <Attribute
                label="Evidence semantics"
                value={setup.data.location_semantics === "OBSERVATION_OR_LATER_LIFECYCLE_EVENT" ? "Observed assignment or later lifecycle event" : setup.data.location_semantics}
              />
            </dl>
          )}
          <p>
            <Link
              to={`/fit-check?machine=${encodeURIComponent(profile.machine_number)}`}
            >
              Run a read-only Fit Check
            </Link>
          </p>
        </ProfileSection>
        <ProfileSection title="Relationships">
          {relationships.isPending ? (
            <LoadingState label="Loading relationships…" />
          ) : relationships.isError ? (
            <>
              <ErrorState error={relationships.error} />
              <Retry retry={() => relationships.refetch()} />
            </>
          ) : (
            <RelationshipList relationships={resolvedRelationships} />
          )}
        </ProfileSection>
        <ProfileSection title="Photos">
          {photos.isPending ? (
            <LoadingState label="Loading photos…" />
          ) : photos.isError ? (
            <>
              <ErrorState error={photos.error} title="Photos unavailable" />
              <Retry retry={() => photos.refetch()} />
            </>
          ) : (
            <PhotoGallery photos={photos.data || []} />
          )}
        </ProfileSection>
        <ProfileSection title="Documents">
          {documents.isPending ? (
            <LoadingState label="Loading documents…" />
          ) : documents.isError ? (
            <>
              <ErrorState error={documents.error} title="Documents unavailable" />
              <Retry retry={() => documents.refetch()} />
            </>
          ) : (
            <DocumentList documents={documents.data || []} />
          )}
        </ProfileSection>
        <ProfileSection title="Recent history">
          {history.isPending ? (
            <LoadingState label="Loading history…" />
          ) : history.isError ? (
            <>
              <ErrorState error={history.error} />
              <Retry retry={() => history.refetch()} />
            </>
          ) : (
            <HistoryList events={history.data || []} />
          )}
        </ProfileSection>
        <QrLabel category="machine" identifier={profile.machine_number} />
      </div>
    </>
  );
}

export function MachineProfilePage() {
  const location = useLocation();
  const number = decodeRouteIdentifier(location.pathname, "machine");
  const profile = useQuery({
    queryKey: ["machine", number, "profile"],
    queryFn: () => apiClient.getMachineProfile(number!),
    enabled: !!number,
  });
  if (!number)
    return (
      <section className="profile-page">
        <NotFoundState entityName="Machine" identifier="invalid identifier" />
      </section>
    );
  if (profile.isPending)
    return (
      <section className="profile-page">
        <LoadingState label="Loading machine profile…" />
      </section>
    );
  if (profile.error instanceof ApiError && profile.error.kind === "not-found")
    return (
      <section className="profile-page">
        <NotFoundState entityName="Machine" identifier={number} />
      </section>
    );
  if (profile.isError)
    return (
      <section className="profile-page">
        <ErrorState error={profile.error} />
        <Retry retry={() => profile.refetch()} />
      </section>
    );
  return (
    <section className="profile-page">
      <MachineContent number={number} profile={profile.data} />
    </section>
  );
}
