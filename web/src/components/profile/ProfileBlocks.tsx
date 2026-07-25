import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  apiClient,
  type EoatRelationship,
  type HistoryEvent,
  type WebDocument,
  type WebPhoto,
} from "@/api/client";
import { relationshipPath } from "@/api/routes";
import { EmptyState } from "@/components/feedback/StateViews";
import {
  deduplicateRelationships,
  relationshipDisplayLabel,
  relationshipTypeLabel,
} from "./relationshipPresentation";

export function ProfileSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section
      className="profile-section"
      aria-labelledby={`section-${title.replaceAll(" ", "-").toLowerCase()}`}
    >
      <h2 id={`section-${title.replaceAll(" ", "-").toLowerCase()}`}>
        {title}
      </h2>
      {children}
    </section>
  );
}

export function Attribute({
  label,
  value,
  missingLabel = "Not recorded",
  booleanLabels,
}: {
  label: string;
  value: string | number | boolean | null | undefined;
  missingLabel?: string;
  booleanLabels?: [string, string];
}) {
  const displayed =
    value === null || value === undefined || value === ""
      ? missingLabel
      : typeof value === "boolean" && booleanLabels
        ? value
          ? booleanLabels[0]
          : booleanLabels[1]
        : String(value);
  return (
    <div>
      <dt>{label}</dt>
      <dd>{displayed}</dd>
    </div>
  );
}

export function EntityHeader({
  category,
  identifier,
  title,
  summary,
}: {
  category: string;
  identifier: string;
  title?: string | null;
  summary: Array<[string, string | null | undefined]>;
}) {
  return (
    <header className="profile-header">
      <p className="eyebrow">Read-only {category} profile</p>
      <h1>{identifier}</h1>
      {title && <p className="profile-name">{title}</p>}
      <div
        className="profile-summary"
        aria-label={`${category} critical status`}
      >
        {summary.map(([label, value]) => (
          <div key={label}>
            <span>{label}</span>
            <strong>{value || "Unknown / unavailable"}</strong>
          </div>
        ))}
      </div>
    </header>
  );
}

export function RelationshipList({
  relationships,
}: {
  relationships: EoatRelationship[];
}) {
  const uniqueRelationships = deduplicateRelationships(relationships);
  if (uniqueRelationships.length === 0)
    return (
      <EmptyState title="No current relationships">
        No linked relationships are recorded for this profile.
      </EmptyState>
    );
  return (
    <ul className="relationship-list">
      {uniqueRelationships.map((relationship) => {
        const path = relationshipPath(
          relationship.relationship_type,
          relationship.identifier,
        );
        const label = relationshipDisplayLabel(relationship);
        return (
          <li
            key={`${relationship.relationship_type}-${relationship.identifier}`}
          >
            <small>
              {relationshipTypeLabel(relationship.relationship_type)}
            </small>
            {path ? <Link to={path}>{label}</Link> : <span>{label}</span>}
            <small>
              {[relationship.status, relationship.reason]
                .filter(Boolean)
                .join(" · ")}
            </small>
          </li>
        );
      })}
    </ul>
  );
}

export function PhotoGallery({ photos }: { photos: WebPhoto[] }) {
  if (photos.length === 0)
    return (
      <EmptyState title="No photos recorded">
        No browser-safe photo metadata is recorded for this profile.
      </EmptyState>
    );
  return (
    <div className="photo-gallery">
      {photos.map((photo) => (
        <figure key={photo.document_uuid} className="photo-card">
          {photo.content_delivery_state === "AVAILABLE" ? (
            <a
              href={apiClient.photoContentUrl(photo.document_uuid)}
              target="_blank"
              rel="noreferrer"
            >
              <img
                src={apiClient.photoThumbnailUrl(photo.document_uuid)}
                alt={photo.caption || photo.title || photo.file_name}
                loading="lazy"
              />
            </a>
          ) : (
            <div
              className="media-unavailable"
              role="img"
              aria-label={`Photo unavailable: ${photo.title}`}
            >
              Photo unavailable
            </div>
          )}
          <figcaption>
            <strong>{photo.title}</strong>
            <span>{photo.caption || photo.file_name}</span>
          </figcaption>
        </figure>
      ))}
    </div>
  );
}

export function DocumentList({ documents }: { documents: WebDocument[] }) {
  if (documents.length === 0)
    return (
      <EmptyState title="No documents recorded">
        No browser-safe document metadata is recorded for this profile.
      </EmptyState>
    );
  return (
    <ul className="metadata-list">
      {documents.map((document) => (
        <li key={document.document_uuid}>
          <strong>{document.title}</strong>
          <span>
            {document.file_name}
            {document.mime_type ? ` · ${document.mime_type}` : ""}
          </span>
          <small>{document.description || "No description provided."}</small>
          {document.content_delivery_state === "AVAILABLE" ? (
            <a
              href={apiClient.documentContentUrl(document.document_uuid)}
              target="_blank"
              rel="noreferrer"
            >
              {document.mime_type === "application/pdf"
                ? "View PDF"
                : "Download document"}
            </a>
          ) : (
            <small>Not available through the web interface.</small>
          )}
        </li>
      ))}
    </ul>
  );
}

export function HistoryList({ events }: { events: HistoryEvent[] }) {
  if (events.length === 0)
    return (
      <EmptyState title="No history recorded">
        No history events are recorded for this profile.
      </EmptyState>
    );
  return (
    <ol className="history-list">
      {events.map((event) => (
        <li key={event.event_id}>
          <strong>{event.event_type}</strong>
          {event.occurred_at && (
            <time>{new Date(event.occurred_at).toLocaleString()}</time>
          )}
          <p>{event.description || event.summary}</p>
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
  );
}
