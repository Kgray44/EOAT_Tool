export type EntityCategory = "eoat" | "machine" | "tool";

const prefixes: Record<EntityCategory, string> = {
  eoat: "/eoats/",
  machine: "/machines/",
  tool: "/tools/",
};

export function entityPath(
  category: EntityCategory,
  identifier: string,
): string {
  return `${prefixes[category]}${encodeURIComponent(identifier)}`;
}

export function decodeRouteIdentifier(
  pathname: string,
  category: EntityCategory,
): string | undefined {
  const encoded = pathname.slice(prefixes[category].length).split("/")[0];
  if (!encoded) return undefined;
  try {
    const decoded = decodeURIComponent(encoded);
    return decoded && !decoded.includes("/") && !decoded.includes("\\")
      ? decoded
      : undefined;
  } catch {
    return undefined;
  }
}

export function relationshipPath(
  relationshipType: string,
  identifier: string,
): string | undefined {
  const category = relationshipType.toLowerCase();
  return category === "eoat" || category === "machine" || category === "tool"
    ? entityPath(category, identifier)
    : undefined;
}
