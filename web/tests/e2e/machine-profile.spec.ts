import { expect, test } from "@playwright/test";
import { expectNoInternalSentinels } from "./sentinelAssertions";

const machine = {
  plant_code: "P4",
  machine_number: "27",
  machine_name: "Machine 27",
  area: "Plant 4",
  manufacturer: null,
  model: null,
  cleanroom_classification: null,
  status: "Active",
  current_eoat: "P4-EOAT-0026",
  is_active: true,
  row_version: 1,
  controller_type: null,
  press_capacity_tons: null,
  notes: null,
  relationships: [
    {
      relationship_type: "eoat",
      identifier: "P4-EOAT-0026",
      display_name: "P4-EOAT-0026",
      status: "Observed in legacy source",
      reason: null,
    },
    {
      relationship_type: "tool",
      identifier: "6920150021",
      display_name: "Tool 6920150021",
      status: "Observed in legacy source",
      reason: null,
    },
    {
      relationship_type: "tool",
      identifier: "6920150021",
      display_name: "Tool 6920150021",
      status: "Observed in legacy source",
      reason: null,
    },
  ],
  robots: [],
  audit_evidence: [],
};

const currentSetup = {
  machine_number: "27",
  current_eoat: "UNKNOWN_NOT_VERIFIED",
  current_tool: "UNKNOWN_NOT_VERIFIED",
  verified: false,
  location_semantics: "OBSERVATION_OR_LATER_LIFECYCLE_EVENT",
};

async function routeMachineApi(
  page: import("@playwright/test").Page,
  options: { photosStatus?: number } = {},
) {
  const seen: import("@playwright/test").Request[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    seen.push(request);
    if (path.endsWith("/not-a-real-route")) {
      return route.fulfill({ status: 404, json: { detail: "Not Found" } });
    }
    if (path.endsWith("/web-photos") && options.photosStatus) {
      return route.fulfill({
        status: options.photosStatus,
        json: { detail: "Photo service unavailable" },
      });
    }
    if (path.endsWith("/current-setup"))
      return route.fulfill({ json: currentSetup });
    if (path.endsWith("/relationships")) {
      return route.fulfill({ json: machine.relationships });
    }
    if (
      path.endsWith("/web-documents") ||
      path.endsWith("/web-photos") ||
      path.endsWith("/history")
    ) {
      return route.fulfill({ json: [] });
    }
    return route.fulfill({ json: machine });
  });
  return seen;
}

test("Machine 27 refreshes with typed empty media and truthful readable values", async ({
  page,
}) => {
  const seen = await routeMachineApi(page);
  await page.goto("/machines/27");

  await expect(page.getByRole("heading", { name: "27" })).toBeVisible();
  await expect(page.getByText("Not verified").first()).toBeVisible();
  await expect(page.getByText("Unknown / not verified")).toHaveCount(0);
  await expect(
    page.getByText("Observed assignment or later lifecycle event"),
  ).toBeVisible();
  await expect(page.getByText("Active record")).toBeVisible();
  await expect(
    page.getByLabel("Overview").getByText("Active", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/Not recorded:/)).toBeVisible();
  await page.getByRole("link", { name: "Docs & Photos" }).click();
  await expect(page.getByText("No photos recorded")).toBeVisible();
  await expect(page.getByText("No documents recorded")).toBeVisible();
  await page.getByRole("link", { name: "Relationships" }).click();
  const relationshipItems = page.locator(".relationship-list li");
  await expect(relationshipItems).toHaveCount(2);
  await expect(
    relationshipItems.filter({ hasText: "P4-EOAT-0026" }),
  ).toBeVisible();
  await expect(
    relationshipItems.filter({ hasText: "6920150021" }),
  ).toBeVisible();
  await expect(
    page.locator(".relationship-list li small").filter({ hasText: "EOAT" }),
  ).toBeVisible();
  await expect(
    page.locator(".relationship-list li small").filter({ hasText: "Tool" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "P4-EOAT-0026", exact: true }),
  ).toHaveCount(1);
  await expect(
    page.getByRole("link", { name: "6920150021", exact: true }),
  ).toHaveCount(1);
  await expect(page.getByText("Tool Tool 6920150021")).toHaveCount(0);
  await expect(page.getByText("6920150021 — Tool 6920150021")).toHaveCount(0);
  await expect(page.getByText("P4-EOAT-0026 — P4-EOAT-0026")).toHaveCount(0);
  await expect(page.getByText("UNKNOWN_NOT_VERIFIED")).toHaveCount(0);
  await expect(
    page.getByText("OBSERVATION_OR_LATER_LIFECYCLE_EVENT"),
  ).toHaveCount(0);

  await page.reload();
  await expect(page.getByRole("heading", { name: "27" })).toBeVisible();
  const expectedPaths = [
    "/api/v1/machines/27",
    "/api/v1/machines/27/current-setup",
    "/api/v1/machines/27/relationships",
    "/api/v1/machines/27/web-documents",
    "/api/v1/machines/27/web-photos",
    "/api/v1/machines/27/history",
  ];
  expect(
    expectedPaths.every((path) =>
      seen.some((request) => new URL(request.url()).pathname === path),
    ),
  ).toBeTruthy();
  expect(seen.every((request) => request.method() === "GET")).toBeTruthy();
  expect(
    seen.every((request) => !request.headers()["x-eoat-device-token"]),
  ).toBeTruthy();

  const missingApi = await page.evaluate(async () => {
    const response = await fetch("/api/v1/machines/27/not-a-real-route");
    return {
      status: response.status,
      contentType: response.headers.get("content-type"),
      body: await response.json(),
    };
  });
  expect(missingApi).toMatchObject({
    status: 404,
    contentType: expect.stringContaining("application/json"),
    body: { detail: "Not Found" },
  });
});

test("Machine Photos preserves a real API failure while Documents keeps its successful empty state", async ({
  page,
}) => {
  await routeMachineApi(page, { photosStatus: 503 });
  await page.goto("/machines/27?tab=media");

  await expect(page.getByText("Photos unavailable")).toBeVisible();
  await expect(page.getByText("No photos recorded")).toHaveCount(0);
  await expect(page.getByText("No documents recorded")).toBeVisible();
});

test("production-shaped Machine 14 presents an unverified Tool assignment without an entity", async ({
  page,
}) => {
  const machine14 = {
    ...machine,
    machine_number: "14",
    machine_name: "Machine 14",
    relationships: [],
  };
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/current-setup"))
      return route.fulfill({ json: { ...currentSetup, machine_number: "14" } });
    if (
      path.endsWith("/relationships") ||
      path.endsWith("/web-documents") ||
      path.endsWith("/web-photos") ||
      path.endsWith("/history")
    )
      return route.fulfill({ json: [] });
    return route.fulfill({ json: machine14 });
  });
  await page.goto("/machines/14?tab=relationships");
  await expect(
    page.getByText("Current tool / mold not verified"),
  ).toBeVisible();
  await expect(
    page
      .getByLabel("Relationship overview")
      .getByText("Current tool / mold not verified"),
  ).toBeVisible();
  await expect(page.getByText("No verified tools recorded")).toHaveCount(0);
  await expect(
    page.locator('a[href="/tools/UNKNOWN_NOT_VERIFIED"]'),
  ).toHaveCount(0);
  await expect(page.locator("code")).not.toContainText("UNKNOWN_NOT_VERIFIED");
  await page.getByRole("link", { name: "Overview" }).click();
  await expect(page.locator('a[href*="fit-check"]')).toHaveCount(1);
  const recentState = await page.evaluate(() => JSON.stringify(localStorage));
  expect(recentState).not.toContain("UNKNOWN_NOT_VERIFIED");
  await expectNoInternalSentinels(page);
});

test.describe("Machine relationship-flow assignment semantics", () => {
  const cases = [
    {
      currentTool: "NONE_OBSERVED",
      expected: "No current tool / mold assignment observed",
    },
    { currentTool: null, expected: "Current tool / mold unavailable" },
    { currentTool: "", expected: "Current tool / mold unavailable" },
    { currentTool: "TOOL-ABC-17", expected: "TOOL-ABC-17" },
  ] as const;

  for (const { currentTool, expected } of cases) {
    test(`keeps ${String(currentTool)} semantically distinct`, async ({
      page,
    }) => {
      const fixture = {
        ...machine,
        machine_number: "14",
        machine_name: "Machine 14",
        relationships: [],
      };
      await page.route("**/api/v1/**", async (route) => {
        const path = new URL(route.request().url()).pathname;
        if (path.endsWith("/current-setup"))
          return route.fulfill({
            json: {
              ...currentSetup,
              machine_number: "14",
              current_tool: currentTool,
            },
          });
        if (
          path.endsWith("/relationships") ||
          path.endsWith("/web-documents") ||
          path.endsWith("/web-photos") ||
          path.endsWith("/history")
        )
          return route.fulfill({ json: [] });
        return route.fulfill({ json: fixture });
      });
      await page.goto("/machines/14?tab=relationships");
      await expect(
        page.getByLabel("Relationship overview").getByText(expected),
      ).toBeVisible();
      if (currentTool === "TOOL-ABC-17") {
        await expect(page.locator('a[href^="/tools/TOOL-ABC-17"]')).toHaveCount(
          1,
        );
      } else {
        await expect(page.locator('a[href^="/tools/"]')).toHaveCount(0);
      }
      await expectNoInternalSentinels(page);
    });
  }
});
