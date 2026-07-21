import { entityPath, type EntityCategory } from "@/api/routes";

export function canonicalQrPayload(
  category: EntityCategory,
  identifier: string,
  origin: string,
): string {
  return new URL(entityPath(category, identifier), origin).toString();
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
