import { useEffect } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
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
  ProfileTabPanel,
  ProfileTabs,
  RelationshipFlow,
  RelationshipList,
} from "@/components/profile/ProfileBlocks";
import { deduplicateRelationships } from "@/components/profile/relationshipPresentation";
import { EntityEditor } from "@/components/profile/EntityEditor";
import { CompatibilityEditor } from "@/components/profile/CompatibilityEditor";
import { MediaUpload } from "@/components/profile/MediaUpload";
import { ProfileActionMenu } from "@/components/profile/ProfileActionMenu";
import { QrLabel } from "@/components/qr/QrLabel";
import {
  isRoutableAuthoritativeIdentifier,
  presentationText,
} from "@/api/presentation";

function Retry({ retry }: { retry: () => void }) {
  return (
    <button className="retry-button" type="button" onClick={retry}>
      Retry
    </button>
  );
}

function assignmentLabel(value: string | null | undefined) {
  return presentationText(value, "Not recorded");
}

function MachineContent({
  number,
  profile,
  onSaved,
}: {
  number: string;
  profile: MachineProfile;
  onSaved: () => void;
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
  const resolvedRelationships = deduplicateRelationships(
    relationships.data ?? profile.relationships ?? [],
  );
  const overview = [
    ["Manufacturer", profile.manufacturer],
    ["Model", profile.model],
    ["Controller", profile.controller_type],
    ["Press capacity (tons)", profile.press_capacity_tons],
    ["Cleanroom classification", profile.cleanroom_classification],
  ] as const;
  const missingOverview = overview
    .filter(
      ([, value]) => value === null || value === undefined || value === "",
    )
    .map(([label]) => label);
  const currentEoat = setup.data?.current_eoat || profile.current_eoat;
  const currentTool = setup.data?.current_tool;
  const relatedEoats = resolvedRelationships
    .filter((item) => item.relationship_type === "eoat")
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
    isRoutableAuthoritativeIdentifier(currentEoat) &&
    relatedEoats.length === 0
  ) {
    relatedEoats.push({
      identifier: currentEoat,
      label: undefined,
      relationshipType: "eoat",
      status: setup.data?.verified
        ? "Current / verified"
        : "Current assignment",
    });
  }
  if (
    isRoutableAuthoritativeIdentifier(currentTool) &&
    relatedTools.length === 0
  ) {
    relatedTools.push({
      identifier: currentTool,
      label: undefined,
      relationshipType: "tool",
      status: "Current tool / mold",
    });
  }

  return (
    <>
      <EntityHeader
        category="machine"
        identifier={profile.machine_number}
        title={profile.machine_name}
        summary={[
          ["Status", profile.status || "Not recorded"],
          [
            "Plant / area",
            [profile.plant_code, profile.area].filter(Boolean).join(" · ") ||
              "Not recorded",
          ],
          [
            "Current EOAT",
            assignmentLabel(setup.data?.current_eoat || profile.current_eoat),
          ],
          [
            "Assignment truth",
            setup.data?.verified ? "Verified" : "Not verified",
          ],
        ]}
        actions={
          <ProfileActionMenu identifier={profile.machine_number}>
            <EntityEditor
              kind="machine"
              identifier={profile.machine_number}
              rowVersion={profile.row_version}
              onSaved={onSaved}
              fields={[
                {
                  key: "area_code",
                  label: "Area",
                  value: profile.area,
                  catalog: "area",
                },
                {
                  key: "machine_name",
                  label: "Machine name",
                  value: profile.machine_name,
                },
                {
                  key: "manufacturer",
                  label: "Manufacturer",
                  value: profile.manufacturer,
                },
                { key: "model", label: "Model", value: profile.model },
                {
                  key: "serial_number",
                  label: "Serial number",
                  value: profile.serial_number,
                },
                {
                  key: "machine_type",
                  label: "Machine type",
                  value: profile.machine_type,
                },
                {
                  key: "press_capacity_tons",
                  label: "Press capacity (tons)",
                  kind: "number",
                  value: profile.press_capacity_tons,
                },
                {
                  key: "controller_type",
                  label: "Controller",
                  value: profile.controller_type,
                },
                {
                  key: "cleanroom_classification",
                  label: "Cleanroom classification",
                  value: profile.cleanroom_classification,
                  catalog: "cleanroom",
                },
                {
                  key: "status",
                  label: "Status",
                  value: profile.status,
                  catalog: "status",
                },
                {
                  key: "installation_date",
                  label: "Installation date",
                  kind: "date",
                  value: profile.installation_date,
                },
                {
                  key: "notes",
                  label: "Notes",
                  kind: "textarea",
                  value: profile.notes,
                },
              ]}
            />
            <CompatibilityEditor
              kind="machine"
              identifier={profile.machine_number}
              onSaved={onSaved}
            />
            <MediaUpload
              entityType="machine"
              identifier={profile.machine_number}
              onSaved={onSaved}
            />
          </ProfileActionMenu>
        }
      />
      <ProfileTabs />
      <div className="profile-sections">
        <ProfileTabPanel tab="relationships">
          <RelationshipFlow
            identifier={profile.machine_number}
            category="Machine"
            leftLabel="EOATs"
            leftNodes={relatedEoats}
            leftAuthoritativeValue={currentEoat}
            hasLeftAuthoritativeValue={
              !!setup.data || currentEoat !== undefined
            }
            leftAuthoritativeLabel="EOAT"
            rightLabel="Tools"
            rightNodes={relatedTools}
            rightAuthoritativeValue={currentTool}
            hasRightAuthoritativeValue={
              !!setup.data || currentTool !== undefined
            }
            rightAuthoritativeLabel="tool / mold"
          />
        </ProfileTabPanel>
        <ProfileSection title="Overview">
          <dl className="attribute-grid">
            {overview
              .filter(
                ([, value]) =>
                  value !== null && value !== undefined && value !== "",
              )
              .map(([label, value]) => (
                <Attribute key={label} label={label} value={value} />
              ))}
            <Attribute
              label="Active record"
              value={profile.is_active}
              booleanLabels={["Active", "Inactive"]}
            />
          </dl>
          {missingOverview.length > 0 && (
            <p className="notes">
              <strong>Not recorded:</strong> {missingOverview.join(", ")}.
            </p>
          )}
          {profile.notes && (
            <p className="notes">
              <strong>Notes:</strong> {presentationText(profile.notes)}
            </p>
          )}
        </ProfileSection>
        <ProfileSection title="Current assignment and compatibility">
          {setup.isPending && <LoadingState label="Loading current setup…" />}
          {setup.isError && (
            <>
              <ErrorState
                error={setup.error}
                title="Current assignment unavailable"
              />
              <Retry retry={() => setup.refetch()} />
            </>
          )}
          {setup.data && (
            <dl className="attribute-grid">
              <Attribute
                label="Current EOAT"
                value={assignmentLabel(setup.data.current_eoat)}
              />
              <Attribute
                label="Current tool / mold"
                value={assignmentLabel(setup.data.current_tool)}
              />
              <Attribute
                label="Evidence semantics"
                value={
                  setup.data.location_semantics ===
                  "OBSERVATION_OR_LATER_LIFECYCLE_EVENT"
                    ? "Observed assignment or later lifecycle event"
                    : setup.data.location_semantics
                }
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
              <ErrorState
                error={documents.error}
                title="Documents unavailable"
              />
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
  const queryClient = useQueryClient();
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
      <MachineContent
        number={number}
        profile={profile.data}
        onSaved={() =>
          void queryClient.invalidateQueries({ queryKey: ["machine", number] })
        }
      />
    </section>
  );
}
