import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  apiClient,
  type EoatRelationship,
  type HistoryEvent,
  type WebDocument,
  type WebPhoto,
} from "@/api/client";
import { relationshipPath } from "@/api/routes";
import {
  isRoutableAuthoritativeIdentifier,
  normalizeAuthoritativeValue,
  presentationText,
} from "@/api/presentation";
import { EmptyState } from "@/components/feedback/StateViews";
import {
  deduplicateRelationships,
  relationshipDisplayLabel,
  relationshipTypeLabel,
} from "./relationshipPresentation";
import {
  normalizeProfileTab,
  profileTabForSection,
  type ProfileTab,
} from "./profileTabs";

export function ProfileSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  const [searchParams] = useSearchParams();
  const activeTab = normalizeProfileTab(searchParams.get("tab"));
  if (profileTabForSection(title) !== activeTab) return null;
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

export function ProfileTabPanel({
  tab,
  children,
}: {
  tab: ProfileTab;
  children: ReactNode;
}) {
  const [searchParams] = useSearchParams();
  return normalizeProfileTab(searchParams.get("tab")) === tab ? (
    <>{children}</>
  ) : null;
}

function profilePathWithCurrentTab(
  path: string,
  searchParams: URLSearchParams,
) {
  const tab = searchParams.get("tab");
  return tab ? `${path}?tab=${encodeURIComponent(tab)}` : path;
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
        : presentationText(value, missingLabel);
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
      <div className="profile-medallion" aria-hidden="true">
        ◇
      </div>
      <div className="profile-identity">
        <p className="eyebrow">Read-only {category} profile</p>
        <h1>{presentationText(identifier)}</h1>
        {title && <p className="profile-name">{presentationText(title)}</p>}
      </div>
      <div
        className="profile-summary"
        aria-label={`${category} critical status`}
      >
        {summary.map(([label, value]) => (
          <div key={label}>
            <span>{label}</span>
            <strong>{presentationText(value, "Unknown / unavailable")}</strong>
          </div>
        ))}
      </div>
    </header>
  );
}

type RelationshipNode = {
  identifier: string;
  label?: string | null;
  relationshipType: string;
  status?: string | null;
};

/**
 * A relationship column can be empty because no relationship is recorded, or
 * because the authoritative current-assignment value is deliberately
 * non-routable.  Keep those cases distinct: the latter is evidence about an
 * assignment and must not become a fake entity, link, or route.
 */
type RelationshipColumnState =
  | { kind: "nodes"; nodes: RelationshipNode[] }
  | { kind: "authoritative-unverified"; message: string }
  | { kind: "authoritative-none-observed"; message: string }
  | { kind: "authoritative-unavailable"; message: string }
  | { kind: "no-recorded-relationships"; message: string };

function relationshipColumnState(
  label: string,
  nodes: RelationshipNode[],
  authoritativeValue: unknown,
  hasAuthoritativeValue: boolean,
  authoritativeLabel?: string,
): RelationshipColumnState {
  const safeNodes = nodes.filter((node) =>
    isRoutableAuthoritativeIdentifier(node.identifier),
  );
  if (safeNodes.length > 0) return { kind: "nodes", nodes: safeNodes };
  if (!hasAuthoritativeValue) {
    return {
      kind: "no-recorded-relationships",
      message: `No verified ${label.toLowerCase()} recorded`,
    };
  }
  const value = normalizeAuthoritativeValue(authoritativeValue);
  const assignmentLabel =
    authoritativeLabel ?? label.toLowerCase().replace(/s$/, "");
  if (value.kind === "sentinel" && value.value === "UNKNOWN_NOT_VERIFIED") {
    return {
      kind: "authoritative-unverified",
      message: `Current ${assignmentLabel} not verified`,
    };
  }
  if (value.kind === "sentinel" && value.value === "NONE_OBSERVED") {
    return {
      kind: "authoritative-none-observed",
      message: `No current ${assignmentLabel} assignment observed`,
    };
  }
  return {
    kind: "authoritative-unavailable",
    message: `Current ${assignmentLabel} unavailable`,
  };
}

function RelationshipNodeList({
  label,
  nodes,
  authoritativeValue,
  hasAuthoritativeValue = false,
  authoritativeLabel,
}: {
  label: string;
  nodes: RelationshipNode[];
  authoritativeValue?: unknown;
  hasAuthoritativeValue?: boolean;
  authoritativeLabel?: string;
}) {
  const [searchParams] = useSearchParams();
  const state = relationshipColumnState(
    label,
    nodes,
    authoritativeValue,
    hasAuthoritativeValue,
    authoritativeLabel,
  );
  return (
    <div className="relationship-flow__column">
      <span>{label}</span>
      <div className="relationship-flow__nodes">
        {state.kind !== "nodes" ? (
          <small data-relationship-state={state.kind}>{state.message}</small>
        ) : (
          state.nodes.map((node) => {
            const path = relationshipPath(
              node.relationshipType,
              node.identifier,
            );
            const destination =
              path && profilePathWithCurrentTab(path, searchParams);
            const text = presentationText(node.label || node.identifier);
            return destination ? (
              <Link
                key={`${node.relationshipType}-${node.identifier}`}
                to={destination}
              >
                <strong>{text}</strong>
                <small>
                  {presentationText(node.status, "Current relationship")}
                </small>
              </Link>
            ) : (
              <div key={`${node.relationshipType}-${node.identifier}`}>
                <strong>{text}</strong>
                <small>
                  {presentationText(node.status, "Current relationship")}
                </small>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

export function RelationshipFlow({
  identifier,
  category,
  leftLabel,
  leftNodes,
  leftAuthoritativeValue,
  hasLeftAuthoritativeValue,
  leftAuthoritativeLabel,
  rightLabel,
  rightNodes,
  rightAuthoritativeValue,
  hasRightAuthoritativeValue,
  rightAuthoritativeLabel,
}: {
  identifier: string;
  category: string;
  leftLabel: string;
  leftNodes: RelationshipNode[];
  leftAuthoritativeValue?: unknown;
  hasLeftAuthoritativeValue?: boolean;
  leftAuthoritativeLabel?: string;
  rightLabel: string;
  rightNodes: RelationshipNode[];
  rightAuthoritativeValue?: unknown;
  hasRightAuthoritativeValue?: boolean;
  rightAuthoritativeLabel?: string;
}) {
  return (
    <section className="relationship-flow" aria-label="Relationship overview">
      <header>
        <h2>Relationship overview</h2>
        <p>Current compatibility and assignment context for this profile.</p>
      </header>
      <div className="relationship-flow__body">
        <RelationshipNodeList
          label={leftLabel}
          nodes={leftNodes}
          authoritativeValue={leftAuthoritativeValue}
          hasAuthoritativeValue={hasLeftAuthoritativeValue}
          authoritativeLabel={leftAuthoritativeLabel}
        />
        <div className="relationship-flow__primary">
          <span>{category}</span>
          <strong>{presentationText(identifier)}</strong>
          <small>Active profile</small>
        </div>
        <RelationshipNodeList
          label={rightLabel}
          nodes={rightNodes}
          authoritativeValue={rightAuthoritativeValue}
          hasAuthoritativeValue={hasRightAuthoritativeValue}
          authoritativeLabel={rightAuthoritativeLabel}
        />
      </div>
    </section>
  );
}

export function ProfileTabs() {
  const [searchParams] = useSearchParams();
  const activeTab = normalizeProfileTab(searchParams.get("tab"));
  const destination = (tab: ProfileTab) => {
    const next = new URLSearchParams(searchParams);
    if (tab === "overview") next.delete("tab");
    else next.set("tab", tab);
    const value = next.toString();
    return value ? `?${value}` : "";
  };
  return (
    <nav className="profile-tabs" aria-label="Profile sections">
      {(
        [
          ["overview", "Overview"],
          ["relationships", "Relationships"],
          ["media", "Docs & Photos"],
          ["history", "History"],
        ] as const
      ).map(([tab, label]) => (
        <Link
          key={tab}
          to={{ search: destination(tab) }}
          aria-current={activeTab === tab ? "page" : undefined}
        >
          {label}
        </Link>
      ))}
    </nav>
  );
}

export function RelationshipList({
  relationships,
}: {
  relationships: EoatRelationship[];
}) {
  const [searchParams] = useSearchParams();
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
        const destination =
          path && profilePathWithCurrentTab(path, searchParams);
        const label = relationshipDisplayLabel(relationship);
        return (
          <li
            key={`${relationship.relationship_type}-${relationship.identifier}`}
          >
            <small>
              {relationshipTypeLabel(relationship.relationship_type)}
            </small>
            {destination ? (
              <Link to={destination}>{label}</Link>
            ) : (
              <span>{label}</span>
            )}
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
