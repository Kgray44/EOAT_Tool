import { expect, type Page } from "@playwright/test";

export const INTERNAL_SENTINELS = [
  "UNKNOWN_NOT_VERIFIED",
  "NONE_OBSERVED",
] as const;

/** Shared browser-boundary assertion for visible text, accessible labels, links, routes, and recents. */
export async function expectNoInternalSentinels(page: Page) {
  const bodyText = await page.locator("body").innerText();
  const exposed = await page
    .locator("[aria-label], a")
    .evaluateAll((nodes) =>
      nodes
        .map(
          (node) =>
            `${node.getAttribute("aria-label") || ""}\n${node.getAttribute("href") || ""}`,
        )
        .join("\n"),
    );
  const recentState = await page.evaluate(() => JSON.stringify(localStorage));
  for (const sentinel of INTERNAL_SENTINELS) {
    expect(bodyText, `visible text leaked ${sentinel}`).not.toContain(sentinel);
    expect(exposed, `accessible name or link leaked ${sentinel}`).not.toContain(
      sentinel,
    );
    expect(recentState, `recent-state leaked ${sentinel}`).not.toContain(
      sentinel,
    );
  }
}
