import { expect, test } from "@playwright/test";

const pagination = { page: 1, page_size: 24, total: 4, pages: 1 };

function machine(machine_number: string) {
  return {
    plant_code: "P4",
    machine_number,
    machine_name: `Machine ${machine_number}`,
    area: "Molding",
    is_active: true,
    row_version: 1,
  };
}

function tool(business_identifier: string) {
  return {
    business_identifier,
    tool_number: business_identifier,
    display_name: `Tool ${business_identifier}`,
    is_active: true,
    row_version: 1,
  };
}

function eoat(business_identifier: string) {
  return {
    business_identifier,
    display_name: business_identifier,
    current_location: "STORED",
    is_active: true,
    row_version: 1,
  };
}

async function mockNavigationApi(page: import("@playwright/test").Page) {
  let serverTime = "2026-08-21T19:28:00Z";
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/auth/session")
      return route.fulfill({
        json: {
          authenticated: true,
          roles: ["VIEWER"],
          permissions: [],
          scope: "application",
        },
      });
    if (path === "/api/v1/data-status")
      return route.fulfill({
        json: {
          status: "available",
          data_revision: 9,
          data_last_modified_at: "2026-07-21T19:27:18Z",
          server_time: serverTime,
        },
      });
    if (path === "/api/v1/machines")
      return route.fulfill({
        json: { items: ["1", "2", "11", "19"].map(machine), pagination },
      });
    if (path === "/api/v1/tools")
      return route.fulfill({
        json: { items: ["TOOL-2", "TOOL-11", "TOOL-19"].map(tool), pagination },
      });
    if (path === "/api/v1/eoats")
      return route.fulfill({
        json: {
          items: ["P4-EOAT-2", "P4-EOAT-11", "P4-EOAT-19"].map(eoat),
          pagination,
        },
      });
    if (path === "/api/v1/search")
      return route.fulfill({
        json: [
          {
            category: "machine",
            identifier: "11",
            title: "Machine 11",
            subtitle: "P4 · Molding",
            matched_field: "number",
          },
        ],
      });
    return route.fulfill({ json: [] });
  });
  return { setServerTime: (value: string) => (serverTime = value) };
}

test("Library renders server-paginated natural machine, tool, and EOAT ordering", async ({
  page,
}) => {
  await mockNavigationApi(page);
  for (const [type, expected] of [
    ["machine", ["Machine 1", "Machine 2", "Machine 11", "Machine 19"]],
    ["tool", ["Tool TOOL-2", "Tool TOOL-11", "Tool TOOL-19"]],
    ["eoat", ["P4-EOAT-2", "P4-EOAT-11", "P4-EOAT-19"]],
  ] as const) {
    await page.goto(`/library?type=${type}`);
    await expect(page.locator(".result-deck .result-card strong")).toHaveText(
      expected,
    );
  }
});

test("Home freshness indicator reports browser refresh time, not database mutation time", async ({
  page,
}) => {
  const api = await mockNavigationApi(page);
  await page.goto("/");
  const status = page.locator(".atlas-data-status");
  await expect(status).toContainText("Last Refreshed: Aug 21, 2026");
  await expect(status.locator(".atlas-status-dot")).toHaveClass(/healthy/);
  expect(await status.getAttribute("title")).toContain(
    "Last successful refresh of data displayed in this browser",
  );

  api.setServerTime("2026-08-22T19:28:00Z");
  await page.evaluate(() =>
    window.dispatchEvent(new Event("visibilitychange")),
  );
  await expect(status).toContainText("Last Refreshed: Aug 22, 2026");

  api.setServerTime("2026-08-23T19:28:00Z");
  await page.evaluate(() => window.dispatchEvent(new Event("offline")));
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  await expect(status).toContainText("Last Refreshed: Aug 23, 2026");
});

test("global search groups entities and user-accessible destinations without exposing admin pages", async ({
  page,
}) => {
  await mockNavigationApi(page);
  await page.goto("/");
  await page.keyboard.press("Control+k");
  const search = page.getByRole("textbox", { name: "Search EOAT Atlas" });

  await search.fill("machine 11");
  await expect(
    page.getByRole("region", { name: "Entities results" }),
  ).toContainText("Machine 11");

  await search.fill("settings");
  await expect(
    page.getByRole("region", { name: "Settings results" }),
  ).toContainText("Appearance & Theme");
  await expect(
    page.getByRole("region", { name: "Settings results" }),
  ).toContainText("Accessibility");
  await expect(
    page.getByRole("region", { name: "Administration results" }),
  ).toHaveCount(0);

  await search.fill("fit check");
  await page.getByRole("button", { name: /Fit Check/ }).click();
  await expect(page).toHaveURL(/\/fit-check$/);
});
