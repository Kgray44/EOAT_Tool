import type { EoatRelationship } from "@/api/client";
import {
  isRoutableAuthoritativeIdentifier,
  presentationText,
} from "@/api/presentation";

/**
 * The API can carry legacy status/source text, but browser profiles must make
 * the relationship meaning clear without leaking migration vocabulary.  Keep
 * this translation in one place so EOAT, Machine, and Tool cards agree.
 */
export type RelationshipSemanticState =
  | "current-assignment"
  | "verified-compatibility"
  | "inferred-compatibility"
  | "historical-observation"
  | "unverified-assignment"
  | "incompatible"
  | "unknown-relationship";

export type RelationshipPresentation = {
  state: RelationshipSemanticState;
  primaryLabel: string;
  evidenceLabel: string;
  evidenceNote?: string;
};

function normalizedRelationshipText(value: unknown): string {
  return typeof value === "string"
    ? value.trim().toLocaleUpperCase().replace(/[^A-Z0-9]+/g, "_")
    : "";
}

export function presentRelationship(
  relationship: Pick<EoatRelationship, "status" | "reason">,
): RelationshipPresentation {
  const status = normalizedRelationshipText(relationship.status);
  const reason = normalizedRelationshipText(relationship.reason);
  const source = `${status}_${reason}`;
  if (/ASSIGNED|CURRENT|INSTALLED/.test(status)) {
    return {
      state: "current-assignment",
      primaryLabel: "Current assignment",
      evidenceLabel: "Current assignment is recorded",
    };
  }
  if (/INFERRED/.test(source)) {
    return {
      state: "inferred-compatibility",
      primaryLabel: "Inferred compatibility",
      evidenceLabel: "Compatibility is inferred and needs verification",
    };
  }
  // Test incompatibility before COMPATIBLE: the latter is a substring of
  // INCOMPATIBLE and must never turn a negative record into a verified match.
  if (/(^|_)INCOMPATIBLE($|_)|NOT_COMPATIBLE/.test(status)) {
    return {
      state: "incompatible",
      primaryLabel: "Incompatible",
      evidenceLabel: "Compatibility is explicitly recorded as incompatible",
    };
  }
  if (/COMPATIBLE|VERIFIED/.test(status)) {
    return {
      state: "verified-compatibility",
      primaryLabel: "Verified compatibility",
      evidenceLabel: "Compatibility is explicitly recorded as verified",
    };
  }
  if (/OBSERV|HISTOR/.test(source)) {
    return {
      state: "historical-observation",
      primaryLabel: "Historical observation",
      evidenceLabel: "This is historical evidence, not a current assignment",
    };
  }
  if (/UNVERIFIED|NEEDS_REVIEW|REVIEW_REQUIRED/.test(source)) {
    return {
      state: "unverified-assignment",
      primaryLabel: "Unverified assignment",
      evidenceLabel: "A relationship is recorded but requires verification",
    };
  }
  return {
    state: "unknown-relationship",
    primaryLabel: "Unknown relationship",
    evidenceLabel: "No verified relationship meaning is available",
    evidenceNote:
      status || reason
        ? "Additional source evidence is present but is not classified for browser display"
        : undefined,
  };
}

export function relationshipTypeLabel(value: string): string {
  return value.toLocaleLowerCase() === "eoat"
    ? "EOAT"
    : value.replace(/^./, (first) => first.toUpperCase());
}

function comparableRelationshipText(value: string): string {
  return value.toLocaleLowerCase().replace(/[^a-z0-9]+/g, "");
}

export function relationshipDisplayLabel(
  relationship: EoatRelationship,
): string {
  const identifier = presentationText(relationship.identifier);
  const displayName =
    relationship.display_name &&
    isRoutableAuthoritativeIdentifier(relationship.display_name)
      ? relationship.display_name.trim()
      : undefined;
  const typeAndIdentifier = `${relationshipTypeLabel(relationship.relationship_type)} ${identifier}`;
  if (
    !displayName ||
    comparableRelationshipText(displayName) ===
      comparableRelationshipText(identifier) ||
    comparableRelationshipText(displayName) ===
      comparableRelationshipText(typeAndIdentifier)
  ) {
    return identifier;
  }
  return `${identifier} — ${displayName}`;
}

export function deduplicateRelationships(
  relationships: EoatRelationship[],
): EoatRelationship[] {
  const seen = new Set<string>();
  return relationships.filter((relationship) => {
    if (!isRoutableAuthoritativeIdentifier(relationship.identifier))
      return false;
    const identity = `${relationship.relationship_type}\u0000${relationship.identifier}`;
    if (seen.has(identity)) return false;
    seen.add(identity);
    return true;
  });
}
