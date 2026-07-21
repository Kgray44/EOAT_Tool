import type { EntityCategory } from "@/api/routes";

export type RecentItem = {
  category: EntityCategory;
  identifier: string;
  label: string;
  viewedAt: string;
};

const key = "eoat-atlas-web-recent-v1";
const limit = 8;

export function readRecentItems(): RecentItem[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(value)
      ? value
          .filter(
            (item): item is RecentItem =>
              !!item && typeof item === "object" && "identifier" in item,
          )
          .slice(0, limit)
      : [];
  } catch {
    return [];
  }
}

export function rememberItem(item: Omit<RecentItem, "viewedAt">): RecentItem[] {
  const next = [
    { ...item, viewedAt: new Date().toISOString() },
    ...readRecentItems().filter(
      (value) =>
        !(
          value.category === item.category &&
          value.identifier === item.identifier
        ),
    ),
  ].slice(0, limit);
  localStorage.setItem(key, JSON.stringify(next));
  return next;
}

export function removeRecentItem(
  category: EntityCategory,
  identifier: string,
): RecentItem[] {
  const next = readRecentItems().filter(
    (value) => value.category !== category || value.identifier !== identifier,
  );
  localStorage.setItem(key, JSON.stringify(next));
  return next;
}
