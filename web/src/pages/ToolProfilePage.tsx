import { useEffect } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Link, useLocation } from "react-router-dom";
import { apiClient, type ToolProfile } from "@/api/client";
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
  ProfileTabPanel,
  ProfileTabs,
  RelationshipFlow,
  RelationshipList,
} from "@/components/profile/ProfileBlocks";
import { QrLabel } from "@/components/qr/QrLabel";
import { presentationText } from "@/api/presentation";

function Retry({ retry }: { retry: () => void }) {
  return (
    <button className="retry-button" type="button" onClick={retry}>
      Retry
    </button>
  );
}

function ToolContent({
  identifier,
  profile,
}: {
  identifier: string;
  profile: ToolProfile;
}) {
  const [relationships, documents, photos, history] = useQueries({
    queries: [
      {
        queryKey: ["tool", identifier, "relationships"],
        queryFn: () => apiClient.getToolRelationships(identifier),
      },
      {
        queryKey: ["tool", identifier, "documents"],
        queryFn: () => apiClient.getToolDocuments(identifier),
      },
      {
        queryKey: ["tool", identifier, "photos"],
        queryFn: () => apiClient.getToolPhotos(identifier),
      },
      {
        queryKey: ["tool", identifier, "history"],
        queryFn: () => apiClient.getToolHistory(identifier),
      },
    ],
  });
  useEffect(() => {
    rememberItem({
      category: "tool",
      identifier,
      label: profile.display_name || profile.tool_number || identifier,
    });
  }, [identifier, profile.display_name, profile.tool_number]);
  const resolvedRelationships =
    relationships.data ?? profile.relationships ?? [];
  const relatedEoats = resolvedRelationships
    .filter((item) => item.relationship_type === "eoat")
    .map((item) => ({
      identifier: item.identifier,
      label: item.display_name,
      relationshipType: item.relationship_type,
      status: item.status,
    }));
  const relatedMachines = resolvedRelationships
    .filter((item) => item.relationship_type === "machine")
    .map((item) => ({
      identifier: item.identifier,
      label: item.display_name,
      relationshipType: item.relationship_type,
      status: item.status,
    }));
  return (
    <>
      <EntityHeader
        category="tool / mold"
        identifier={profile.business_identifier}
        title={profile.display_name || profile.description}
        summary={[
          ["Status", profile.status],
          ["Tool number", profile.tool_number],
          ["Mold number", profile.mold_number],
          ["Part verification", profile.part_status],
        ]}
      />
      <ProfileTabs />
      <div className="profile-sections">
        <ProfileTabPanel tab="relationships">
          <RelationshipFlow
            identifier={profile.business_identifier}
            category="Tool / mold"
            leftLabel="EOATs"
            leftNodes={relatedEoats}
            rightLabel="Machines"
            rightNodes={relatedMachines}
          />
        </ProfileTabPanel>
        <ProfileSection title="Overview">
          <dl className="attribute-grid">
            <Attribute label="Description" value={profile.description} />
            <Attribute label="Tool type" value={profile.tool_type} />
            <Attribute label="Customer" value={profile.customer} />
            <Attribute
              label="Program / part family"
              value={profile.program_name}
            />
            <Attribute label="Active record" value={profile.is_active} />
          </dl>
          {profile.notes && (
            <p className="notes">
              <strong>Notes:</strong> {presentationText(profile.notes)}
            </p>
          )}
        </ProfileSection>
        <ProfileSection title="Compatibility and assignment">
          <p>
            Known compatible machines and EOATs are shown in Relationships.
            Current assignment is not exposed by this contract when it is not
            reliably recorded.
          </p>
          <p>
            <Link
              to={`/fit-check?tool=${encodeURIComponent(profile.business_identifier)}`}
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
        <QrLabel category="tool" identifier={profile.business_identifier} />
      </div>
    </>
  );
}

export function ToolProfilePage() {
  const location = useLocation();
  const identifier = decodeRouteIdentifier(location.pathname, "tool");
  const profile = useQuery({
    queryKey: ["tool", identifier, "profile"],
    queryFn: () => apiClient.getToolProfile(identifier!),
    enabled: !!identifier,
  });
  if (!identifier)
    return (
      <section className="profile-page">
        <NotFoundState entityName="Tool" identifier="invalid identifier" />
      </section>
    );
  if (profile.isPending)
    return (
      <section className="profile-page">
        <LoadingState label="Loading tool profile…" />
      </section>
    );
  if (profile.error instanceof ApiError && profile.error.kind === "not-found")
    return (
      <section className="profile-page">
        <NotFoundState entityName="Tool" identifier={identifier} />
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
      <ToolContent identifier={identifier} profile={profile.data} />
    </section>
  );
}
