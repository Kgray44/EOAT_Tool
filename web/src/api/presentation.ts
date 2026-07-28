/**
 * The authoritative API deliberately exposes a small set of semantic values
 * for relationship/assignment fields.  They are data-state markers, not
 * entity identifiers, and must never cross the web presentation boundary as
 * routes, links, keys, recents, or user-visible internal text.
 */
export const INTERNAL_SEMANTIC_SENTINELS = {
  UNKNOWN_NOT_VERIFIED: "Not verified",
  NONE_OBSERVED: "No assignment observed",
} as const;

export type InternalSemanticSentinel = keyof typeof INTERNAL_SEMANTIC_SENTINELS;

export type PresentedAuthoritativeValue =
  | {
      kind: "identifier";
      value: string;
      display: string;
      routable: true;
    }
  | {
      kind: "sentinel";
      value: InternalSemanticSentinel;
      display: string;
      routable: false;
    }
  | {
      kind: "unavailable";
      display: string;
      routable: false;
    };

export function normalizeAuthoritativeValue(
  value: unknown,
  unavailableLabel = "Unknown / unavailable",
): PresentedAuthoritativeValue {
  if (typeof value !== "string") {
    return { kind: "unavailable", display: unavailableLabel, routable: false };
  }
  const normalized = value.trim();
  if (!normalized) {
    return { kind: "unavailable", display: unavailableLabel, routable: false };
  }
  if (normalized in INTERNAL_SEMANTIC_SENTINELS) {
    const sentinel = normalized as InternalSemanticSentinel;
    return {
      kind: "sentinel",
      value: sentinel,
      display: INTERNAL_SEMANTIC_SENTINELS[sentinel],
      routable: false,
    };
  }
  return {
    kind: "identifier",
    value: normalized,
    display: normalized,
    routable: true,
  };
}

export function isRoutableAuthoritativeIdentifier(
  value: unknown,
): value is string {
  return normalizeAuthoritativeValue(value).kind === "identifier";
}

export function presentationText(
  value: unknown,
  unavailableLabel?: string,
): string {
  return normalizeAuthoritativeValue(value, unavailableLabel).display;
}
