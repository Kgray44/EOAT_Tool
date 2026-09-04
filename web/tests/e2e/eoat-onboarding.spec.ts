import { expect, test } from "@playwright/test";

async function routeOnboardingApi(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/auth/session") {
      return route.fulfill({
        json: {
          authenticated: true,
          identity: { display_name: "Fixture Engineer" },
          roles: ["ENGINEER"],
          permissions: ["onboarding.draft.create", "onboarding.draft.finalize"],
          scope: "application",
        },
      });
    }
    if (path === "/api/v1/onboarding/status") return route.fulfill({ json: { enabled: true } });
    if (path === "/api/v1/data-status") {
      return route.fulfill({
        json: {
          status: "available",
          data_revision: 1,
          data_last_modified_at: "2026-09-04T00:00:00Z",
          server_time: "2026-09-04T00:00:00Z",
        },
      });
    }
    return route.fulfill({ json: [] });
  });
}

for (const theme of ["light", "dark"] as const) {
  test(`onboarding keeps the ${theme} theme and fits a phone viewport`, async ({ page }) => {
    await page.addInitScript((savedTheme) => {
      localStorage.setItem(
        "eoat-atlas-mirrorline-settings-v1",
        JSON.stringify({
          theme: savedTheme,
          accent: "atlas_blue",
          animationSpeed: "standard",
          reduceMotion: false,
          enhancedContrast: true,
        }),
      );
    }, theme);
    await routeOnboardingApi(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/eoats/new");

    await expect(page.locator("html")).toHaveAttribute("data-atlas-theme", theme);
    await expect(page.getByRole("heading", { name: "Add New EOAT" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Onboarding sections" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  });
}
