import type { Location } from "react-router-dom";

export type LibraryContext = {
  pathname: "/library";
  search: string;
  scrollY: number;
  selected?: string;
};

const storageKey = "eoat-atlas-mirrorline-library-context-v1";

export function captureLibraryContext(
  location: Location,
  selected?: string,
): LibraryContext {
  return {
    pathname: "/library",
    search: location.search,
    scrollY: typeof window === "undefined" ? 0 : window.scrollY,
    ...(selected ? { selected } : {}),
  };
}

export function saveLibraryContext(context: LibraryContext): void {
  try {
    sessionStorage.setItem(storageKey, JSON.stringify(context));
  } catch {
    // Session restoration is progressive enhancement; navigation remains safe.
  }
}

export function readLibraryContext(
  value?: unknown,
): LibraryContext | undefined {
  const direct = (value as { libraryContext?: unknown } | undefined)
    ?.libraryContext;
  let stored: unknown;
  try {
    stored = JSON.parse(sessionStorage.getItem(storageKey) || "null");
  } catch {
    stored = undefined;
  }
  const context = direct || stored;
  if (
    !context ||
    typeof context !== "object" ||
    (context as LibraryContext).pathname !== "/library" ||
    typeof (context as LibraryContext).search !== "string" ||
    !Number.isFinite((context as LibraryContext).scrollY)
  ) {
    return undefined;
  }
  return context as LibraryContext;
}
