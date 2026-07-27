export type BrowserFitCheckRecent = {
  machine: string;
  tool: string;
  eoat: string;
  result: string;
  evaluatedAt: string;
};

const storageKey = "eoat-atlas-mirrorline-fit-check-recents-v1";
const maxRecent = 15;

export function readFitCheckRecents(): BrowserFitCheckRecent[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (record): record is BrowserFitCheckRecent =>
        !!record &&
        typeof record.machine === "string" &&
        typeof record.tool === "string" &&
        typeof record.eoat === "string" &&
        typeof record.result === "string" &&
        typeof record.evaluatedAt === "string",
    );
  } catch {
    return [];
  }
}

export function rememberFitCheck(
  recent: Omit<BrowserFitCheckRecent, "evaluatedAt">,
): BrowserFitCheckRecent[] {
  const entry = { ...recent, evaluatedAt: new Date().toISOString() };
  const signature = `${entry.machine}\u0000${entry.tool}\u0000${entry.eoat}`;
  const next = [
    entry,
    ...readFitCheckRecents().filter(
      (item) =>
        `${item.machine}\u0000${item.tool}\u0000${item.eoat}` !== signature,
    ),
  ].slice(0, maxRecent);
  localStorage.setItem(storageKey, JSON.stringify(next));
  return next;
}
