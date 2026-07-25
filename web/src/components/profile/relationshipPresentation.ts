import type { EoatRelationship } from "@/api/client";

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
  const identifier = relationship.identifier.trim();
  const displayName = relationship.display_name?.trim();
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
    const identity = `${relationship.relationship_type}\u0000${relationship.identifier}`;
    if (seen.has(identity)) return false;
    seen.add(identity);
    return true;
  });
}
