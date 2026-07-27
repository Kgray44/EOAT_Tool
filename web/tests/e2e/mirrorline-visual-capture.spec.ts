import { expect, test } from "@playwright/test";

const evidence = process.env.EOAT_MIRRORLINE_VISUAL_EVIDENCE;

test.skip(!evidence, "Visual capture is an explicitly requested artifact run.");

async function fixtureApi(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/data-status") {
      return route.fulfill({
        json: {
          status: "available",
          data_revision: 7,
          data_last_modified_at: "2026-07-27T12:00:00Z",
          server_time: "2026-07-27T12:01:00Z",
          source: "mysql",
          environment: "fixture",
        },
      });
    }
    if (path.endsWith("/search")) return route.fulfill({ json: [] });
    return route.fulfill({
      json: {
        items: [],
        pagination: { page: 1, page_size: 24, total: 0, pages: 1 },
      },
    });
  });
}

async function capture(page: import("@playwright/test").Page, state: string) {
  await page.screenshot({
    path: `${evidence}/browser/${state}.png`,
    fullPage: false,
  });
}

test("captures governed Mirrorline browser shell references", async ({
  page,
}) => {
  await fixtureApi(page);
  await page.setViewportSize({ width: 1760, height: 1080 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();
  await capture(page, "home-dark");

  await page.evaluate(() => {
    const stored = JSON.parse(
      localStorage.getItem("eoat-atlas-mirrorline-settings-v1") || "{}",
    );
    localStorage.setItem(
      "eoat-atlas-mirrorline-settings-v1",
      JSON.stringify({ ...stored, theme: "light" }),
    );
  });
  await page.reload();
  await capture(page, "home-light");

  await page.evaluate(() =>
    localStorage.removeItem("eoat-atlas-mirrorline-settings-v1"),
  );
  await page.reload();
  await page.getByRole("button", { name: "Open navigation menu" }).click();
  await capture(page, "navigation-home");
  await page.getByRole("link", { name: "Fit Check" }).click();
  await page.getByRole("button", { name: "Open navigation menu" }).click();
  await capture(page, "navigation-fit-check");
  await page.getByRole("link", { name: "Library" }).click();
  await page.getByRole("button", { name: "Open navigation menu" }).click();
  await capture(page, "navigation-library");
  await page.getByRole("link", { name: "Settings" }).click();
  await page.getByRole("button", { name: "Open navigation menu" }).click();
  await capture(page, "navigation-settings");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Open search" }).click();
  await capture(page, "global-search");
});
