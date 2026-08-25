import { expect, test } from "@playwright/test";

const profile = {
  business_identifier: "QR-EOAT-1",
  display_name: "QR vacuum picker",
  description: "Controlled browser fixture",
  status: "ACTIVE",
  eoat_type: "VACUUM",
  connection_type: "QD",
  cleanroom_classification: null,
  number_of_parts_picked: 2,
  is_active: true,
  row_version: 1,
  current_location: "INSTALLED — Machine M-1",
  current_location_detail: null,
  relationships: [],
  audit_evidence: [],
  revision: "R1",
  number_of_vacuum_cups: 2,
  number_of_grippers: 0,
  vacuum_present: true,
  sensors_present: true,
  part_present_sensor_present: false,
  vacuum_confirmation_sensor_present: true,
  quick_disconnect_present: true,
  cup_material: "Silicone",
  notes: null,
  part_status: "NOT_YET_VERIFIED",
};
const location = {
  state: "INSTALLED",
  source: "OBSERVATION",
  machine_number: "M-1",
  storage_location: null,
  observed_at: "2026-07-21T12:00:00Z",
  observed_on: null,
  observation_precision: "TIMESTAMP",
  confidence: "HIGH",
  resolution_status: "CURRENT",
  evidence: "Controlled fixture",
  observation_uuid: null,
  conflict_group_uuid: null,
};
const auditedProfile = {
  ...profile,
  number_of_parts_picked: null,
  number_of_vacuum_cups: null,
  number_of_grippers: null,
  sensors_present: null,
  latest_physical_audit: {
    audit_identifier: "AUD-20260521-012",
    observed_on: "2026-05-21T00:00:00Z",
    observed_machine: "9",
    observed_tool: "7130080010",
    verified: true,
    evidence: "Physical audit AUD-20260521-012",
    configuration: {
      parts_picked: 4,
      vacuum_cup_count: 4,
      gripper_count: 1,
      vacuum_circuits: 2,
      pressure_circuits: 0,
      sensors_present: false,
      quick_disconnect_present: true,
    },
  },
};

async function routeApi(
  page: import("@playwright/test").Page,
  seen: import("@playwright/test").Request[],
  profilePayload = profile,
) {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    seen.push(request);
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/health"))
      return route.fulfill({
        json: {
          api_version: "1.4.0",
          application_version: "0.17.2",
          compatible: true,
          writes_enabled: false,
          expected_schema_revision: "20260717_0007",
          api_contract_version: "1.4.0",
          current_schema_revision: "20260717_0007",
        },
      });
    if (path.includes("MISSING"))
      return route.fulfill({
        status: 404,
        json: { detail: { message: "EOAT missing" } },
      });
    if (path.endsWith("/current-location"))
      return route.fulfill({ json: location });
    if (
      path.endsWith("/relationships") ||
      path.endsWith("/documents") ||
      path.endsWith("/photos")
    )
      return route.fulfill({ json: [] });
    if (path.endsWith("/history"))
      return route.fulfill({
        json: {
          items: [],
          pagination: { page: 1, page_size: 12, total: 0, pages: 0 },
        },
      });
    return route.fulfill({ json: profilePayload });
  });
}

test("QR-style direct EOAT route loads, refreshes, and remains read-only", async ({
  page,
}) => {
  const seen: import("@playwright/test").Request[] = [];
  await routeApi(page, seen);
  await page.goto("/eoats/QR-EOAT-1");
  await expect(page.getByRole("heading", { name: "QR-EOAT-1" })).toBeVisible();
  await expect(page.getByLabel("Relationship overview")).toBeVisible();
  await expect(
    page.getByText(
      "Current compatibility and assignment context for this profile.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Relationships" }),
  ).toHaveAttribute("aria-current", "page");
  await page.reload();
  await expect(page.getByRole("heading", { name: "QR-EOAT-1" })).toBeVisible();
  expect(seen.every((request) => request.method() === "GET")).toBeTruthy();
  expect(
    seen.every((request) => !request.headers()["x-eoat-device-token"]),
  ).toBeTruthy();
});

test("verified physical-audit configuration is visible without being presented as current", async ({
  page,
}) => {
  const seen: import("@playwright/test").Request[] = [];
  await routeApi(page, seen, auditedProfile);
  await page.goto("/eoats/QR-EOAT-1");
  await page.getByRole("link", { name: "Overview" }).click();

  const valueFor = (label: string) =>
    page.getByText(label, { exact: true }).first().locator("..").locator("dd");
  await expect(valueFor("Parts picked")).toContainText("4");
  await expect(valueFor("Vacuum cups")).toContainText("4");
  await expect(valueFor("Grippers")).toContainText("1");
  await expect(valueFor("Vacuum circuits")).toContainText("2");
  await expect(valueFor("Pressure circuits")).toContainText("0");
  await expect(valueFor("Sensors present")).toContainText("No");
  await expect(valueFor("Parts picked")).toContainText(
    "Observed in verified physical audit AUD-20260521-012",
  );
  await expect(
    page.getByText(
      "This is a dated observation, not a present-day assignment.",
    ),
  ).toBeVisible();
  await expect(page.getByText("9", { exact: true })).toBeVisible();
});

test("landing, back navigation, not-found, and mobile overflow are truthful", async ({
  page,
}) => {
  const seen: import("@playwright/test").Request[] = [];
  await routeApi(page, seen);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();
  await page.goto("/eoats/QR-EOAT-1");
  await expect(page.getByRole("heading", { name: "QR-EOAT-1" })).toBeVisible();
  await page.goto("/search");
  await page.goBack();
  await expect(page.getByRole("heading", { name: "QR-EOAT-1" })).toBeVisible();
  await page.goForward();
  await expect(page.getByRole("heading", { name: "Library" })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading", { name: "QR-EOAT-1" })).toBeVisible();
  await page.goto("/eoats/MISSING");
  await expect(
    page.getByRole("heading", { name: "EOAT not found" }),
  ).toBeVisible();
  for (const width of [360, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/eoats/QR-EOAT-1");
    await expect(
      page.getByRole("heading", { name: "QR-EOAT-1" }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
  }
});
