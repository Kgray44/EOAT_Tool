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
    if (path === "/api/v1/onboarding/status")
      return route.fulfill({ json: { enabled: true } });
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
  test(`onboarding keeps the ${theme} theme and fits a phone viewport`, async ({
    page,
  }) => {
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

    await expect(page.locator("html")).toHaveAttribute(
      "data-atlas-theme",
      theme,
    );
    await expect(
      page.getByRole("heading", { name: "Add New EOAT" }),
    ).toBeVisible();
    await expect(
      page.locator(".onboarding-mobile-steps summary"),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
  });
}

test("keeps onboarding management outside the Library", async ({ page }) => {
  await routeOnboardingApi(page);
  await page.goto("/management/eoats");

  await expect(
    page.getByRole("heading", { name: "EOAT Management" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: /Add New EOAT/ })).toBeVisible();
  await expect(
    page.getByRole("link", { name: /Onboarding Drafts/ }),
  ).toBeVisible();

  await page.goto("/library");
  await expect(page.getByRole("heading", { name: "Library" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Add New EOAT" })).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "Onboarding Drafts" }),
  ).toHaveCount(0);
});

test("captures the desktop and narrow onboarding presentation", async ({
  page,
}, testInfo) => {
  await page.addInitScript(() => {
    localStorage.setItem(
      "eoat-atlas-mirrorline-settings-v1",
      JSON.stringify({
        theme: "light",
        accent: "atlas_blue",
        animationSpeed: "standard",
        reduceMotion: true,
        enhancedContrast: true,
      }),
    );
  });
  await routeOnboardingApi(page);
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto("/management/eoats");
  await expect(
    page.getByRole("heading", { name: "EOAT Management" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("management-light-desktop.png"),
    fullPage: true,
  });

  await page.goto("/eoats/new");
  await expect(
    page.getByRole("heading", { name: "Add New EOAT" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("onboarding-light-desktop.png"),
    fullPage: true,
  });

  await page.getByRole("button", { name: /Step 2: Hardware/ }).click();
  await expect(
    page.getByRole("heading", { name: "Pickup hardware" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("onboarding-light-hardware.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: /Step 6: Review/ }).click();
  await expect(page.getByRole("heading", { name: "Review" })).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("onboarding-light-review.png"),
    fullPage: true,
  });

  await page.addInitScript(() => {
    localStorage.setItem(
      "eoat-atlas-mirrorline-settings-v1",
      JSON.stringify({
        theme: "dark",
        accent: "atlas_blue",
        animationSpeed: "standard",
        reduceMotion: true,
        enhancedContrast: true,
      }),
    );
  });
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto("/management/eoats");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute(
    "data-atlas-theme",
    "dark",
  );
  await expect(
    page.getByRole("heading", { name: "EOAT Management" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("management-dark-desktop.png"),
    fullPage: true,
  });

  await page.goto("/eoats/new");
  await page.screenshot({
    path: testInfo.outputPath("onboarding-dark-desktop.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: /Step 2: Hardware/ }).click();
  await page.screenshot({
    path: testInfo.outputPath("onboarding-dark-hardware.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: /Step 6: Review/ }).click();
  await expect(page.getByRole("heading", { name: "Review" })).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("onboarding-dark-review.png"),
    fullPage: true,
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await page.locator(".onboarding-mobile-steps summary").click();
  await expect(
    page.getByRole("navigation", { name: "Onboarding section selector" }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("onboarding-dark-phone.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
});
