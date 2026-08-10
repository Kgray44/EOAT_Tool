import { expect, test } from "@playwright/test";

const evidence = process.env.EOAT_MIRRORLINE_VISUAL_EVIDENCE;

const libraryEoats = [
  {
    business_identifier: "P4-EOAT-0052",
    display_name: "P4-EOAT-0052",
    current_location: "Machine 52",
  },
  {
    business_identifier: "P4-EOAT-0099",
    display_name: "P4-EOAT-0099",
    current_location: "Machine 99",
  },
];
const libraryMachines = [
  {
    machine_number: "52",
    machine_name: "Machine 52",
    area: "Plant 4 / Production",
  },
];
const profileEoat = {
  business_identifier: "P4-EOAT-0052",
  display_name: "P4-EOAT-0052",
  description: "Vacuum EOAT",
  status: "ACTIVE",
  eoat_type: "VACUUM",
  connection_type: "Quick disconnect",
  cleanroom_classification: null,
  number_of_parts_picked: 1,
  is_active: true,
  current_location: "Machine 52",
  relationships: [],
  audit_evidence: [],
  revision: "A",
};
const profileMachine = {
  machine_number: "52",
  machine_name: "Machine 52",
  plant_code: "Plant 4",
  area: "Production",
  manufacturer: "Atlas",
  model: "M52",
  cleanroom_classification: null,
  status: "ACTIVE",
  current_eoat: "P4-EOAT-0052",
  is_active: true,
  controller_type: "RC",
  press_capacity_tons: 100,
  notes: null,
  relationships: [],
  robots: [],
  audit_evidence: [],
};
const profileTool = {
  business_identifier: "6201510010",
  tool_number: "6201510010",
  mold_number: "MOLD-52",
  display_name: "Tool 6201510010",
  status: "ACTIVE",
  part_status: "VERIFIED",
  is_active: true,
  description: "Production tool",
  tool_type: "MOLD",
  customer: null,
  program_name: null,
  notes: null,
  relationships: [],
  audit_evidence: [],
};

test.skip(!evidence, "Visual capture is an explicitly requested artifact run.");

async function fixtureApi(page: import("@playwright/test").Page) {
  const scenario = {
    apiUnavailable: false,
    emptySearch: false,
    slowSearch: false,
    staleData: false,
  };
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/data-status") {
      if (scenario.apiUnavailable)
        return route.fulfill({
          status: 503,
          json: { detail: { message: "fixture unavailable" } },
        });
      return route.fulfill({
        json: {
          status: "available",
          data_revision: 7,
          data_last_modified_at: scenario.staleData
            ? "2020-01-01T00:00:00Z"
            : "2026-07-27T12:00:00Z",
          server_time: "2026-07-27T12:01:00Z",
          source: "mysql",
          environment: "fixture",
        },
      });
    }
    if (path.endsWith("/web-fit-checks/options")) {
      return route.fulfill({
        json: {
          machines: [
            { identifier: "52", label: "Machine 52", plant_code: "P4" },
            { identifier: "99", label: "Machine 99", plant_code: "P4" },
          ],
          tools: [{ identifier: "6201510010", label: "Tool 6201510010" }],
          eoats: [{ identifier: "P4-EOAT-0052", label: "P4-EOAT-0052" }],
          warnings: [],
          unresolved_inputs: [],
        },
      });
    }
    if (path.includes("/catalog-options/")) return route.fulfill({ json: [] });
    if (path.endsWith("/web-fit-checks/evaluate")) {
      const request = route.request();
      const body = request.postDataJSON() as { machine_number?: string } | null;
      const warning = body?.machine_number === "99";
      return route.fulfill({
        json: {
          overall_result: warning ? "INCOMPATIBLE" : "COMPATIBLE",
          machine_tool_result: {
            pair: "machine_tool",
            result: warning ? "INCOMPATIBLE" : "COMPATIBLE",
            reason: warning ? "Fixture mismatch" : "Fixture compatible",
          },
          machine_eoat_result: {
            pair: "machine_eoat",
            result: warning ? "WARNING" : "COMPATIBLE",
            reason: warning
              ? "Review machine assignment"
              : "Fixture compatible",
          },
          tool_eoat_result: {
            pair: "tool_eoat",
            result: "COMPATIBLE",
            reason: "Fixture compatible",
          },
          reasons: [warning ? "Fixture incompatibility" : "Fixture compatible"],
          warnings: warning ? ["Fixture warning"] : [],
          unknown_relationships: [],
          alternative_compatible_eoats: warning ? ["P4-EOAT-0099"] : [],
          evaluation_engine_version: "fixture",
          stored: false,
        },
      });
    }
    if (path === "/api/v1/setup-packets/data") {
      return route.fulfill({
        json: {
          machine: profileMachine,
          tool: profileTool,
          eoat: profileEoat,
          fit_check: {
            overall_result: "COMPATIBLE",
            machine_tool_result: {
              pair: "machine_tool",
              result: "COMPATIBLE",
              reason: "Fixture compatible",
            },
            machine_eoat_result: {
              pair: "machine_eoat",
              result: "COMPATIBLE",
              reason: "Fixture compatible",
            },
            tool_eoat_result: {
              pair: "tool_eoat",
              result: "COMPATIBLE",
              reason: "Fixture compatible",
            },
            reasons: ["Fixture compatible"],
            warnings: [],
            unknown_relationships: [],
            alternative_compatible_eoats: [],
            stored: false,
          },
          generated_at: "2026-08-10T16:00:00Z",
          source: "fixture",
        },
      });
    }
    if (path === "/api/v1/settings/catalog") {
      return route.fulfill({
        json: {
          sections: [],
          items: [
            {
              section: "data_sources",
              key: "paths.eoat_master_tracker",
              label: "EOAT Master Tracker",
              control: "path",
              default: "",
              options: [],
              locked: false,
            },
            {
              section: "data_sources",
              key: "data.source_status",
              label: "Authoritative source status",
              control: "status",
              default: "Available",
              options: [],
              locked: true,
            },
          ],
        },
      });
    }
    if (path === "/api/v1/settings")
      return route.fulfill({ json: { items: [] } });
    if (path === "/api/v1/auth/config") {
      return route.fulfill({
        json: {
          provider: "kerberos_form",
          settings_authentication_available: true,
          provider_configured: true,
          message: "Kerberos sign-in is required for shared changes.",
        },
      });
    }
    if (path.includes("MISSING"))
      return route.fulfill({
        status: 404,
        json: { detail: { message: "fixture missing" } },
      });
    if (path.endsWith("/search")) {
      if (scenario.slowSearch)
        await new Promise((resolve) => setTimeout(resolve, 1200));
      if (scenario.emptySearch) return route.fulfill({ json: [] });
      return route.fulfill({
        json: libraryEoats.map((item) => ({
          category: "eoat",
          identifier: item.business_identifier,
          title: item.display_name,
          subtitle: "Vacuum",
          matched_field: "fixture",
        })),
      });
    }
    if (path === "/api/v1/eoats")
      return route.fulfill({
        json: {
          items: libraryEoats,
          pagination: { page: 1, page_size: 24, total: 2, pages: 1 },
        },
      });
    if (path === "/api/v1/machines")
      return route.fulfill({
        json: {
          items: libraryMachines,
          pagination: { page: 1, page_size: 24, total: 1, pages: 1 },
        },
      });
    if (path === "/api/v1/tools")
      return route.fulfill({
        json: {
          items: [],
          pagination: { page: 1, page_size: 24, total: 0, pages: 1 },
        },
      });
    if (path.includes("/current-location"))
      return route.fulfill({
        json: {
          state: "INSTALLED",
          source: "FIXTURE",
          machine_number: "52",
          storage_location: null,
          observed_at: "2026-07-27T12:00:00Z",
          observed_on: null,
          observation_precision: null,
          confidence: "HIGH",
          resolution_status: "CURRENT",
          evidence: "deterministic fixture",
          observation_uuid: null,
          conflict_group_uuid: null,
        },
      });
    if (path.includes("/current-setup"))
      return route.fulfill({
        json: {
          machine_number: "52",
          current_eoat: "P4-EOAT-0052",
          current_tool: "6201510010",
          verified: true,
          location_semantics: "FIXTURE",
        },
      });
    if (
      path.endsWith("/relationships") ||
      path.endsWith("/web-documents") ||
      path.endsWith("/web-photos")
    )
      return route.fulfill({ json: [] });
    if (path.endsWith("/history"))
      return route.fulfill({
        json: path.includes("/eoats/")
          ? {
              items: [],
              pagination: { page: 1, page_size: 12, total: 0, pages: 0 },
            }
          : [],
      });
    if (path.includes("/eoats/")) return route.fulfill({ json: profileEoat });
    if (path.includes("/machines/"))
      return route.fulfill({ json: profileMachine });
    if (path.includes("/tools/")) return route.fulfill({ json: profileTool });
    return route.fulfill({
      json: {
        items: [],
        pagination: { page: 1, page_size: 24, total: 0, pages: 1 },
      },
    });
  });
  return scenario;
}

async function capture(page: import("@playwright/test").Page, state: string) {
  await page.screenshot({
    path: `${evidence}/browser/${state}.png`,
    fullPage: false,
  });
}

async function expectHeadingBelowMobileHeader(
  page: import("@playwright/test").Page,
  heading: import("@playwright/test").Locator,
) {
  const [topbar, title] = await Promise.all([
    page.locator(".atlas-topbar").boundingBox(),
    heading.boundingBox(),
  ]);
  expect(topbar).not.toBeNull();
  expect(title).not.toBeNull();
  expect(title!.y).toBeGreaterThanOrEqual(topbar!.y + topbar!.height);
}

test("captures governed Mirrorline browser shell references", async ({
  page,
}) => {
  const scenario = await fixtureApi(page);
  await page.setViewportSize({ width: 1760, height: 1080 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();
  await capture(page, "home-dark");

  await page.evaluate(() =>
    localStorage.setItem(
      "eoat-atlas-web-recent-v1",
      JSON.stringify([
        {
          category: "eoat",
          identifier: "P4-EOAT-0052",
          label: "P4-EOAT-0052",
          viewedAt: "2026-07-27T12:00:00Z",
        },
      ]),
    ),
  );
  await page.reload();
  await capture(page, "home-recents");
  await page.getByLabel("Search the EOAT Atlas Library").fill("P4-EOAT-0052");
  await capture(page, "home-live-search");
  await page.keyboard.press("Escape");

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
  await page.goto("/library?type=eoat");
  await expect(page.getByText("P4-EOAT-0052").first()).toBeVisible();
  await capture(page, "library-default");
  await page.goto("/library?q=P4-EOAT-0052");
  await expect(page.getByText("P4-EOAT-0052").first()).toBeVisible();
  await capture(page, "library-query");
  await page.goto("/library?type=machine");
  await expect(page.getByText("Machine 52").first()).toBeVisible();
  await capture(page, "library-filters");
  scenario.slowSearch = true;
  await page.goto("/library?q=loading", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("status")).toBeVisible();
  await capture(page, "loading");
  scenario.slowSearch = false;
  scenario.emptySearch = true;
  await page.goto("/library?q=empty");
  await expect(
    page.getByRole("heading", { name: "No matching records" }),
  ).toBeVisible();
  await capture(page, "empty");
  await page.goto("/eoats/MISSING");
  await expect(
    page.getByRole("heading", { name: "EOAT not found" }),
  ).toBeVisible();
  await capture(page, "not-found");
  scenario.emptySearch = false;
  await page.goto("/eoats/P4-EOAT-0052");
  await expect(
    page.getByRole("heading", { name: "P4-EOAT-0052" }),
  ).toBeVisible();
  await capture(page, "eoat-profile");
  await page.goto("/machines/52");
  await expect(page.getByRole("heading", { name: "52" })).toBeVisible();
  await capture(page, "machine-profile");
  await page.goto("/tools/6201510010");
  await expect(page.getByRole("heading", { name: "6201510010" })).toBeVisible();
  await capture(page, "tool-profile");
  await page.goto("/fit-check");
  const fitHeading = page.getByRole("heading", {
    name: "Fit Check",
    exact: true,
  });
  await expect(fitHeading).toBeVisible();
  await expectHeadingBelowMobileHeader(page, fitHeading);
  await capture(page, "fit-empty");
  await page.goto("/fit-check?tool=6201510010");
  await capture(page, "fit-populated");
  await page.goto("/fit-check?machine=52&tool=6201510010&eoat=P4-EOAT-0052");
  await page.getByRole("button", { name: "Evaluate without saving" }).click();
  await expect(page.getByRole("heading", { name: "COMPATIBLE" })).toBeVisible();
  await capture(page, "fit-compatible");
  await page.goto("/fit-check?machine=99&tool=6201510010&eoat=P4-EOAT-0052");
  await page.getByRole("button", { name: "Evaluate without saving" }).click();
  await expect(
    page.getByRole("heading", { name: "INCOMPATIBLE" }),
  ).toBeVisible();
  await capture(page, "fit-warning");
  await page.goto("/settings");
  await expect(
    page.getByRole("heading", { name: "Settings", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("EOAT Master Tracker")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  expect(
    await page
      .locator(".settings-page")
      .evaluate(
        (element) => element.getBoundingClientRect().right <= window.innerWidth,
      ),
  ).toBeTruthy();
  await capture(page, "settings-dark");
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
  await expect(page.getByText("EOAT Master Tracker")).toBeVisible();
  await capture(page, "settings-light");
  await page.evaluate(() => {
    const stored = JSON.parse(
      localStorage.getItem("eoat-atlas-mirrorline-settings-v1") || "{}",
    );
    localStorage.setItem(
      "eoat-atlas-mirrorline-settings-v1",
      JSON.stringify({ ...stored, theme: "dark" }),
    );
  });
  await page.reload();
  scenario.apiUnavailable = true;
  await page.goto("/");
  await expect(page.getByText(/API unavailable/)).toBeVisible();
  await capture(page, "api-unavailable");
  scenario.apiUnavailable = false;
  scenario.staleData = true;
  await page.reload();
  await capture(page, "stale-data");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await capture(page, "reduced-motion");
  scenario.staleData = false;
  await page.goto("/");
  await page.getByRole("button", { name: "Open search" }).click();
  await capture(page, "global-search");
});

test("captures tablet and phone responsive parity references", async ({
  page,
}) => {
  await fixtureApi(page);
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto("/library?type=machine");
  await expect(page.getByRole("heading", { name: "Library" })).toBeVisible();
  await capture(page, "library-tablet");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/fit-check?machine=52&tool=6201510010&eoat=P4-EOAT-0052");
  await expect(
    page.getByRole("heading", { name: "Fit Check", exact: true }),
  ).toBeVisible();
  await capture(page, "fit-mobile");

  await page.goto("/setup-packet?machine=52&tool=6201510010&eoat=P4-EOAT-0052");
  const packetHeading = page.getByRole("heading", {
    name: "Setup Packet",
    exact: true,
  });
  await expect(packetHeading).toBeVisible();
  await expectHeadingBelowMobileHeader(page, packetHeading);
  await expect(
    page.getByRole("button", { name: "Print or save as PDF" }),
  ).toBeVisible();
  await capture(page, "setup-packet-mobile");
});
