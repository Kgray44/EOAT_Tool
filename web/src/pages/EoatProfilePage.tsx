import { useEffect, type ReactNode } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import {
  apiClient,
  type EoatLocation,
  type EoatProfile,
  type EoatRelationship,
  type WebPhoto,
} from "@/api/client";
import { ApiError } from "@/api/errors";
import { rememberItem } from "@/api/recent";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  NotFoundState,
  StatusValue,
} from "@/components/feedback/StateViews";
import {
  DocumentList,
  PhotoGallery,
  ProfileTabPanel,
  ProfileTabs,
  RelationshipFlow,
} from "@/components/profile/ProfileBlocks";
import {
  normalizeProfileTab,
  profileTabForSection,
} from "@/components/profile/profileTabs";
import { QrLabel } from "@/components/qr/QrLabel";
import {
  isRoutableAuthoritativeIdentifier,
  presentationText,
} from "@/api/presentation";

function decodeEoatIdentifier(pathname: string): string | undefined {
  const prefix = "/eoats/";
  if (!pathname.startsWith(prefix)) return undefined;
  const encoded = pathname.slice(prefix.length).split("/")[0];
  if (!encoded) return undefined;
  try {
    const decoded = decodeURIComponent(encoded);
    return decoded.trim() && !decoded.includes("/") ? decoded : undefined;
  } catch {
    return undefined;
  }
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "Unknown / unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "Unknown / unavailable";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function truthLabel(location: EoatLocation | undefined): string {
  if (!location) return "Unknown / unavailable";
  if (
    location.state === "CONFLICTING" ||
    location.resolution_status === "REVIEW_REQUIRED"
  ) {
    return "Conflicting — review required";
  }
  if (location.state === "UNKNOWN" || location.source === "NONE") {
    return "Unknown / not verified";
  }
  return `${location.resolution_status.toLowerCase().replace("_", " ")} · ${location.confidence.toLowerCase()}`;
}

function relationshipTo(relationship: EoatRelationship): string | undefined {
  if (!isRoutableAuthoritativeIdentifier(relationship.identifier))
    return undefined;
  if (relationship.relationship_type === "machine") {
    return `/machines/${encodeURIComponent(relationship.identifier)}`;
  }
  if (relationship.relationship_type === "tool") {
    return `/tools/${encodeURIComponent(relationship.identifier)}`;
  }
  if (relationship.relationship_type === "eoat") {
    return `/eoats/${encodeURIComponent(relationship.identifier)}`;
  }
  return undefined;
}

function RetryButton({ retry }: { retry: () => void }) {
  return (
    <button className="retry-button" type="button" onClick={retry}>
      Retry
    </button>
  );
}

function ProfileSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  const [searchParams] = useSearchParams();
  if (
    profileTabForSection(title) !== normalizeProfileTab(searchParams.get("tab"))
  ) {
    return null;
  }
  return (
    <section className="profile-section" aria-labelledby={`section-${title}`}>
      <h2 id={`section-${title.toLowerCase().replaceAll(" ", "-")}`}>
        {title}
      </h2>
      {children}
    </section>
  );
}

function Attribute({
  label,
  value,
}: {
  label: string;
  value: string | number | boolean | null | undefined;
}) {
  const display = typeof value === "boolean" ? (value ? "Yes" : "No") : value;
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        <StatusValue value={display} />
      </dd>
    </div>
  );
}

function ProfileHeader({
  profile,
  location,
  heroPhoto,
}: {
  profile: EoatProfile;
  location?: EoatLocation;
  heroPhoto?: WebPhoto;
}) {
  const locationText =
    location?.state === "INSTALLED" && location.machine_number
      ? `Installed on machine ${location.machine_number}`
      : location?.state === "STORED"
        ? (location.storage_location ?? "Stored; exact location unavailable")
        : presentationText(profile.current_location);
  return (
    <header className="profile-header">
      {heroPhoto?.content_delivery_state === "AVAILABLE" ? (
        <a
          className="profile-hero-photo"
          href={apiClient.photoContentUrl(heroPhoto.document_uuid)}
          target="_blank"
          rel="noreferrer"
          aria-label={`Open full-resolution photo for ${profile.business_identifier}`}
        >
          <img
            src={apiClient.photoThumbnailUrl(heroPhoto.document_uuid)}
            alt={heroPhoto.caption || heroPhoto.title || heroPhoto.file_name}
          />
        </a>
      ) : (
        <div className="profile-medallion" aria-hidden="true">
          ◇
        </div>
      )}
      <div className="profile-identity">
        <p className="eyebrow">EOAT profile</p>
        <h1>{presentationText(profile.business_identifier)}</h1>
        <p className="profile-name">
          <StatusValue value={profile.display_name ?? profile.description} />
        </p>
      </div>
      <div className="profile-summary" aria-label="EOAT critical status">
        <div>
          <span>Status</span>
          <strong>{profile.status ?? "Unknown / unavailable"}</strong>
        </div>
        <div>
          <span>EOAT type</span>
          <strong>{profile.eoat_type ?? "Unknown / unavailable"}</strong>
        </div>
        <div>
          <span>Current location</span>
          <strong>
            {presentationText(locationText, "Unknown / unavailable")}
          </strong>
        </div>
        <div>
          <span>Verification</span>
          <strong>{truthLabel(location)}</strong>
        </div>
      </div>
    </header>
  );
}

function ProfileContent({
  identifier,
  profile,
}: {
  identifier: string;
  profile: EoatProfile;
}) {
  const [searchParams] = useSearchParams();
  useEffect(() => {
    rememberItem({
      category: "eoat",
      identifier,
      label: profile.display_name ?? profile.business_identifier,
    });
  }, [identifier, profile.business_identifier, profile.display_name]);
  const [location, relationships, documents, photos, history] = useQueries({
    queries: [
      {
        queryKey: ["eoat", identifier, "location"],
        queryFn: () => apiClient.getEoatLocation(identifier),
      },
      {
        queryKey: ["eoat", identifier, "relationships"],
        queryFn: () => apiClient.getEoatRelationships(identifier),
      },
      {
        queryKey: ["eoat", identifier, "documents"],
        queryFn: () => apiClient.getEoatDocuments(identifier),
      },
      {
        queryKey: ["eoat", identifier, "photos"],
        queryFn: () => apiClient.getEoatPhotos(identifier),
      },
      {
        queryKey: ["eoat", identifier, "history"],
        queryFn: () => apiClient.getEoatHistory(identifier),
      },
    ],
  });
  const currentLocation =
    location.data ?? profile.current_location_detail ?? undefined;
  const resolvedRelationships = (
    relationships.data ??
    profile.relationships ??
    []
  ).filter((relationship) =>
    isRoutableAuthoritativeIdentifier(relationship.identifier),
  );
  const relatedMachines = resolvedRelationships
    .filter((item) => item.relationship_type === "machine")
    .map((item) => ({
      identifier: item.identifier,
      label: item.display_name,
      relationshipType: item.relationship_type,
      status: item.status,
    }));
  const relatedTools = resolvedRelationships
    .filter((item) => item.relationship_type === "tool")
    .map((item) => ({
      identifier: item.identifier,
      label: item.display_name,
      relationshipType: item.relationship_type,
      status: item.status,
    }));
  if (
    isRoutableAuthoritativeIdentifier(currentLocation?.machine_number) &&
    relatedMachines.length === 0
  ) {
    relatedMachines.push({
      identifier: currentLocation.machine_number,
      label: undefined,
      relationshipType: "machine",
      status: "Current assignment",
    });
  }

  return (
    <>
      <ProfileHeader
        profile={profile}
        location={currentLocation}
        heroPhoto={
          photos.data?.find((photo) => photo.is_profile_photo) ??
          photos.data?.[0]
        }
      />
      <ProfileTabs />
      <div className="profile-sections">
        <ProfileTabPanel tab="relationships">
          <RelationshipFlow
            identifier={profile.business_identifier}
            category="EOAT"
            leftLabel="Machines"
            leftNodes={relatedMachines}
            leftAuthoritativeValue={currentLocation?.machine_number}
            hasLeftAuthoritativeValue={!!currentLocation}
            rightLabel="Tools"
            rightNodes={relatedTools}
          />
        </ProfileTabPanel>
        <ProfileSection title="Overview">
          <dl className="attribute-grid">
            <Attribute label="Description" value={profile.description} />
            <Attribute label="Revision" value={profile.revision} />
            <Attribute label="Connection" value={profile.connection_type} />
            <Attribute
              label="Cleanroom classification"
              value={profile.cleanroom_classification}
            />
            <Attribute
              label="Parts picked"
              value={profile.number_of_parts_picked}
            />
            <Attribute label="Active record" value={profile.is_active} />
          </dl>
        </ProfileSection>

        <ProfileSection title="Current location and assignment">
          {location.isPending && (
            <LoadingState label="Loading current location…" />
          )}
          {location.isError && (
            <>
              <ErrorState error={location.error} />
              <RetryButton retry={() => location.refetch()} />
            </>
          )}
          {currentLocation && (
            <div className="location-card">
              <p>
                <strong>{currentLocation.state}</strong> ·{" "}
                {truthLabel(currentLocation)}
              </p>
              <dl className="attribute-grid">
                <Attribute
                  label="Machine assignment"
                  value={currentLocation.machine_number}
                />
                <Attribute
                  label="Storage location"
                  value={currentLocation.storage_location}
                />
                <Attribute
                  label="Observed"
                  value={formatDate(currentLocation.observed_at)}
                />
                <Attribute label="Evidence" value={currentLocation.evidence} />
                <Attribute label="Source" value={currentLocation.source} />
              </dl>
            </div>
          )}
        </ProfileSection>

        <ProfileSection title="Configuration and capabilities">
          <dl className="attribute-grid">
            <Attribute label="Vacuum present" value={profile.vacuum_present} />
            <Attribute
              label="Vacuum cups"
              value={profile.number_of_vacuum_cups}
            />
            <Attribute label="Grippers" value={profile.number_of_grippers} />
            <Attribute
              label="Sensors present"
              value={profile.sensors_present}
            />
            <Attribute
              label="Part-present sensor"
              value={profile.part_present_sensor_present}
            />
            <Attribute
              label="Vacuum-confirmation sensor"
              value={profile.vacuum_confirmation_sensor_present}
            />
            <Attribute
              label="Quick disconnect"
              value={profile.quick_disconnect_present}
            />
            <Attribute label="Cup material" value={profile.cup_material} />
          </dl>
          {profile.notes && (
            <p className="notes">
              <strong>Notes:</strong> {profile.notes}
            </p>
          )}
        </ProfileSection>

        <ProfileSection title="Relationships">
          {relationships.isPending && (
            <LoadingState label="Loading relationships…" />
          )}
          {relationships.isError && (
            <>
              <ErrorState error={relationships.error} />
              <RetryButton retry={() => relationships.refetch()} />
            </>
          )}
          {!relationships.isPending &&
            !relationships.isError &&
            resolvedRelationships.length === 0 && (
              <EmptyState title="No current relationships">
                EOAT Atlas has no linked machine, tool, or EOAT relationships
                for this record.
              </EmptyState>
            )}
          {resolvedRelationships.length > 0 && (
            <ul className="relationship-list">
              {resolvedRelationships.map((relationship) => {
                const to = relationshipTo(relationship);
                const destination =
                  to && searchParams.get("tab")
                    ? `${to}?tab=${encodeURIComponent(searchParams.get("tab")!)}`
                    : to;
                const text =
                  relationship.display_name &&
                  isRoutableAuthoritativeIdentifier(relationship.display_name)
                    ? `${relationship.identifier} — ${relationship.display_name}`
                    : relationship.identifier;
                return (
                  <li
                    key={`${relationship.relationship_type}-${relationship.identifier}`}
                  >
                    <span>{relationship.relationship_type}: </span>
                    {destination ? (
                      <Link to={destination}>{text}</Link>
                    ) : (
                      <span>{text}</span>
                    )}
                    <small>
                      {presentationText(relationship.status)}
                      {relationship.reason ? ` · ${relationship.reason}` : ""}
                    </small>
                  </li>
                );
              })}
            </ul>
          )}
        </ProfileSection>

        <ProfileSection title="Photos">
          {photos.isPending && <LoadingState label="Loading photo metadata…" />}
          {photos.isError && (
            <>
              <ErrorState error={photos.error} />
              <RetryButton retry={() => photos.refetch()} />
            </>
          )}
          {photos.data && photos.data.length === 0 && (
            <EmptyState title="No photos linked">
              EOAT Atlas has no photo metadata for this record.
            </EmptyState>
          )}
          {photos.data && photos.data.length > 0 && (
            <PhotoGallery photos={photos.data} />
          )}
        </ProfileSection>

        <ProfileSection title="Documents">
          {documents.isPending && (
            <LoadingState label="Loading document metadata…" />
          )}
          {documents.isError && (
            <>
              <ErrorState error={documents.error} />
              <RetryButton retry={() => documents.refetch()} />
            </>
          )}
          {documents.data && documents.data.length === 0 && (
            <EmptyState title="No documents linked">
              EOAT Atlas has no document metadata for this record.
            </EmptyState>
          )}
          {documents.data && documents.data.length > 0 && (
            <DocumentList documents={documents.data} />
          )}
        </ProfileSection>

        <ProfileSection title="Recent history">
          {history.isPending && <LoadingState label="Loading history…" />}
          {history.isError && (
            <>
              <ErrorState error={history.error} />
              <RetryButton retry={() => history.refetch()} />
            </>
          )}
          {history.data?.items.length === 0 && (
            <EmptyState title="No history recorded">
              EOAT Atlas has no history events for this record.
            </EmptyState>
          )}
          {history.data && history.data.items.length > 0 && (
            <ol className="history-list">
              {history.data.items.map((event) => (
                <li key={event.event_id}>
                  <strong>{event.event_type}</strong>
                  <time>{formatDate(event.occurred_at)}</time>
                  <p>{event.description ?? event.summary}</p>
                  {(event.related_machine ||
                    event.related_tool ||
                    event.related_storage_location) && (
                    <small>
                      Related:{" "}
                      {[
                        event.related_machine,
                        event.related_tool,
                        event.related_storage_location,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </small>
                  )}
                  {(event.actor || event.source_record_type) && (
                    <small>
                      Source:{" "}
                      {[event.actor, event.source_record_type]
                        .filter(Boolean)
                        .join(" · ")}
                    </small>
                  )}
                </li>
              ))}
            </ol>
          )}
        </ProfileSection>
        <QrLabel category="eoat" identifier={profile.business_identifier} />
      </div>
    </>
  );
}

export function EoatProfilePage() {
  const location = useLocation();
  const identifier = decodeEoatIdentifier(location.pathname);
  const profile = useQuery({
    queryKey: ["eoat", identifier, "profile"],
    queryFn: () => apiClient.getEoatProfile(identifier!),
    enabled: !!identifier,
  });
  if (!identifier) {
    return (
      <section className="profile-page">
        <EmptyState title="Invalid EOAT identifier">
          This EOAT link is incomplete or contains an invalid encoded
          identifier.
        </EmptyState>
      </section>
    );
  }
  if (profile.isPending)
    return (
      <section className="profile-page">
        <LoadingState label="Loading EOAT profile…" />
      </section>
    );
  if (profile.error instanceof ApiError && profile.error.kind === "not-found")
    return (
      <section className="profile-page">
        <NotFoundState identifier={identifier} />
      </section>
    );
  if (profile.isError)
    return (
      <section className="profile-page">
        <ErrorState error={profile.error} />
        <RetryButton retry={() => profile.refetch()} />
      </section>
    );
  return (
    <section className="profile-page">
      <ProfileContent identifier={identifier} profile={profile.data} />
    </section>
  );
}
