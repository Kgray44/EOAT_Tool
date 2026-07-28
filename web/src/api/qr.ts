import { entityPath, type EntityCategory } from "@/api/routes";

export function canonicalQrPayload(
  category: EntityCategory,
  identifier: string,
  origin: string,
): string {
  const path = entityPath(category, identifier);
  if (!path)
    throw new Error("QR labels require a routable authoritative identifier");
  return new URL(path, origin).toString();
}

export function isUnsafeQrOrigin(origin: string): boolean {
  try {
    const host = new URL(origin).hostname;
    return (
      host === "localhost" ||
      host === "127.0.0.1" ||
      host === "::1" ||
      host.endsWith(".local")
    );
  } catch {
    return true;
  }
}
