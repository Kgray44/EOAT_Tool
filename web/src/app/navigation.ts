import type { AuthenticatedSession } from "@/api/client";

export type NavigationGroup = "Pages" | "Settings" | "Administration";

export type NavigationDestination = {
  path: string;
  label: string;
  icon?: string;
  group: NavigationGroup;
  keywords: readonly string[];
  administratorOnly?: boolean;
};

/**
 * The normal browser routes and Settings anchors that users can navigate to.
 * AppShell and GlobalSearchOverlay both consume this list so top navigation
 * and search cannot silently drift into separate route catalogs.
 */
export const navigationDestinations: readonly NavigationDestination[] = [
  {
    path: "/",
    label: "Home",
    icon: "⌂",
    group: "Pages",
    keywords: ["home", "start"],
  },
  {
    path: "/fit-check",
    label: "Fit Check",
    icon: "◉",
    group: "Pages",
    keywords: ["fit check", "compatibility"],
  },
  {
    path: "/library",
    label: "Library",
    icon: "▦",
    group: "Pages",
    keywords: ["library", "catalog", "machines", "tools", "eoats"],
  },
  {
    path: "/setup-packet",
    label: "Setup Packet",
    group: "Pages",
    keywords: ["setup", "packet"],
  },
  {
    path: "/standards",
    label: "Standards & WI",
    group: "Pages",
    keywords: ["standards", "work instructions", "wi"],
  },
  {
    path: "/data-health",
    label: "Data Health",
    group: "Pages",
    keywords: ["data", "health", "freshness"],
  },
  {
    path: "/settings",
    label: "Settings",
    icon: "⚙",
    group: "Settings",
    keywords: ["settings", "preferences"],
  },
  {
    path: "/settings#theme",
    label: "Appearance & Theme",
    group: "Settings",
    keywords: ["settings", "appearance", "theme", "accent", "animation"],
  },
  {
    path: "/settings#accessibility",
    label: "Accessibility",
    group: "Settings",
    keywords: ["settings", "accessibility", "reduce motion", "contrast"],
  },
  {
    path: "/admin",
    label: "Administrator Overview",
    group: "Administration",
    keywords: ["admin", "administrator", "overview"],
    administratorOnly: true,
  },
  {
    path: "/admin/settings",
    label: "Administrator Settings",
    group: "Administration",
    keywords: ["admin", "administrator", "settings", "configuration"],
    administratorOnly: true,
  },
  {
    path: "/admin/users",
    label: "Users & Access",
    group: "Administration",
    keywords: ["admin", "users", "access", "roles"],
    administratorOnly: true,
  },
  {
    path: "/admin/group-policies",
    label: "Group Access Policies",
    group: "Administration",
    keywords: ["admin", "group", "policy", "directory", "roles", "access"],
    administratorOnly: true,
  },
  {
    path: "/admin/audit",
    label: "Audit Ledger",
    group: "Administration",
    keywords: ["admin", "audit", "ledger"],
    administratorOnly: true,
  },
];

export const primaryNavigation = navigationDestinations.filter(
  (destination) =>
    Boolean(destination.icon) && destination.group !== "Administration",
);

export function searchableDestinations(
  query: string,
  session: AuthenticatedSession | null | undefined,
): NavigationDestination[] {
  const normalized = query.trim().toLocaleLowerCase();
  const isAdministrator = session?.roles?.includes("ADMINISTRATOR") ?? false;
  return navigationDestinations.filter((destination) => {
    if (destination.administratorOnly && !isAdministrator) return false;
    if (!normalized) return false;
    return [destination.label, ...destination.keywords].some((value) =>
      value.toLocaleLowerCase().includes(normalized),
    );
  });
}
