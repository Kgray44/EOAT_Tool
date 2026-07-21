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
    relationships.data ?? profile.relationships ?? [];

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
          ["Current EOAT", setup.data?.current_eoat || profile.current_eoat],
          [
            "Assignment truth",
            setup.data?.verified ? "Verified" : "Unknown / not verified",
          ],
        ]}
      />
      <div className="profile-sections">
        <ProfileSection title="Overview">
          <dl className="attribute-grid">
            <Attribute label="Manufacturer" value={profile.manufacturer} />
            <Attribute label="Model" value={profile.model} />
            <Attribute label="Controller" value={profile.controller_type} />
            <Attribute
              label="Press capacity (tons)"
              value={profile.press_capacity_tons}
            />
            <Attribute
              label="Cleanroom classification"
              value={profile.cleanroom_classification}
            />
            <Attribute label="Active record" value={profile.is_active} />
          </dl>
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
              <ErrorState error={setup.error} />
              <Retry retry={() => setup.refetch()} />
            </>
          )}
          {setup.data && (
            <dl className="attribute-grid">
              <Attribute label="Current EOAT" value={setup.data.current_eoat} />
              <Attribute
                label="Current tool / mold"
                value={setup.data.current_tool}
              />
              <Attribute
                label="Evidence semantics"
                value={setup.data.location_semantics}
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
              <ErrorState error={photos.error} />
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
              <ErrorState error={documents.error} />
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
