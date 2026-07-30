export type ProfileTab = "overview" | "relationships" | "media" | "history";

export function normalizeProfileTab(value: string | null): ProfileTab {
  return value === "relationships" || value === "media" || value === "history"
    ? value
    : "overview";
}

export function profileTabForSection(title: string): ProfileTab {
  const normalized = title.trim().toLocaleLowerCase();
  if (normalized === "relationships") return "relationships";
  if (normalized === "photos" || normalized === "documents") return "media";
  if (normalized === "recent history" || normalized === "history") {
    return "history";
  }
  return "overview";
}
