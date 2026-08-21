import { expect, test } from "@playwright/test";

const eoat = {
  business_identifier: "EOAT-1",
  display_name: "Picker",
  description: "Fixture EOAT",
  status: "ACTIVE",
  eoat_type: "VACUUM",
  connection_type: null,
  cleanroom_classification: null,
  number_of_parts_picked: null,
  is_active: true,
  row_version: 1,
  current_location: "UNKNOWN_NOT_VERIFIED",
  current_location_detail: null,
  photo_document_uuid: "photo-1",
  photo_available_through_web: true,
  relationships: [],
  audit_evidence: [],
  revision: null,
  number_of_vacuum_cups: null,
  number_of_grippers: null,
  vacuum_present: null,
  sensors_present: null,
  part_present_sensor_present: null,
  vacuum_confirmation_sensor_present: null,
  quick_disconnect_present: null,
  cup_material: null,
  notes: null,
  part_status: "NOT_YET_VERIFIED",
};
const machine = {
  plant_code: "P1",
  machine_number: "M-1",
  machine_name: "Press 1",
  area: "Molding",
  manufacturer: "Atlas",
  model: "X1",
  cleanroom_classification: null,
  status: "ACTIVE",
  current_eoat: "EOAT-1",
  is_active: true,
  row_version: 1,
  controller_type: "RC",
  press_capacity_tons: 100,
  notes: null,
  relationships: [
    {
      relationship_type: "tool",
      identifier: "TOOL-1",
      display_name: "Mold 1",
      status: "COMPATIBLE",
      reason: null,
    },
  ],
  robots: [],
  audit_evidence: [],
};
const tool = {
  business_identifier: "TOOL-1",
  tool_number: "T-1",
  mold_number: "MOLD-1",
  display_name: "Mold 1",
  status: "ACTIVE",
  part_status: "VERIFIED",
  is_active: true,
  row_version: 1,
  description: "Fixture tool",
  tool_type: "MOLD",
  customer: null,
  program_name: null,
  notes: null,
  relationships: [
    {
      relationship_type: "eoat",
      identifier: "EOAT-1",
      display_name: "Picker",
      status: "COMPATIBLE",
      reason: null,
    },
  ],
  audit_evidence: [],
};
const photo = {
  document_uuid: "photo-1",
  document_number: null,
  title: "Profile photo",
  description: null,
  file_name: "photo.jpg",
  mime_type: "image/jpeg",
  related_entities: [],
  content_delivery_state: "AVAILABLE",
  photo_view_type: null,
  captured_at: null,
  caption: "Fixture image",
  is_profile_photo: true,
};
const document = {
  document_uuid: "doc-1",
  document_number: "D1",
  title: "Setup sheet",
  description: "Fixture PDF",
  file_name: "setup.pdf",
  mime_type: "application/pdf",
  related_entities: [],
  content_delivery_state: "AVAILABLE",
};

async function routeApi(
  page: import("@playwright/test").Page,
  seen: import("@playwright/test").Request[],
) {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    seen.push(request);
    const path = new URL(request.url()).pathname;
    if (path.includes("MISSING"))
      return route.fulfill({
        status: 404,
        json: { detail: { message: "missing" } },
      });
    if (path.endsWith("/thumbnail"))
      return route.fulfill({
        contentType: "image/jpeg",
        body: Buffer.from(
          "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAH/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAEFAqf/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/Aaf/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/Aaf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAY/Aqf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/IV//2gAMAwEAAgADAAAAEP/EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQMBAT8QH//EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQIBAT8QH//EABQQAQAAAAAAAAAAAAAAAAAAABD/2gAIAQEAAT8QH//Z",
          "base64",
        ),
      });
    if (path.endsWith("/content"))
      return route.fulfill({
        contentType: "application/pdf",
        body: "%PDF-1.4",
      });
    if (path.endsWith("/documents")) return route.fulfill({ json: [document] });
    if (path.endsWith("/photos")) return route.fulfill({ json: [photo] });
    if (path.endsWith("/current-location"))
      return route.fulfill({
        json: {
          state: "UNKNOWN",
          source: "NONE",
          machine_number: null,
          storage_location: null,
          observed_at: null,
          observed_on: null,
          observation_precision: null,
          confidence: "UNKNOWN",
          resolution_status: "CURRENT",
          evidence: "Fixture",
          observation_uuid: null,
          conflict_group_uuid: null,
        },
      });
    if (path.endsWith("/current-setup"))
      return route.fulfill({
        json: {
          machine_number: "M-1",
          current_eoat: "EOAT-1",
          current_tool: "TOOL-1",
          verified: true,
          location_semantics: "Fixture",
        },
      });
    if (path.endsWith("/relationships"))
      return route.fulfill({
        json: path.includes("machines")
          ? machine.relationships
          : path.includes("tools")
            ? tool.relationships
            : [],
      });
    if (path.endsWith("/history"))
      return route.fulfill({
        json: path.includes("eoats")
          ? {
              items: [],
              pagination: { page: 1, page_size: 12, total: 0, pages: 0 },
            }
          : [],
      });
    if (path.endsWith("/web-fit-checks/options"))
      return route.fulfill({
        json: {
          machines: [{ identifier: "M-1", label: "Press 1", plant_code: "P1" }],
          tools: [{ identifier: "TOOL-1", label: "Mold 1" }],
          eoats: [{ identifier: "EOAT-1", label: "Picker" }],
          warnings: [],
          unresolved_inputs: [],
        },
      });
    if (path.includes("/catalog-options/")) return route.fulfill({ json: [] });
    if (path.endsWith("/fit-checks/evaluate"))
      return route.fulfill({
        json: {
          overall_result: "COMPATIBLE",
          machine_tool_result: {
            pair: "machine_tool",
            result: "COMPATIBLE",
            reason: "Fixture",
          },
          machine_eoat_result: {
            pair: "machine_eoat",
            result: "COMPATIBLE",
            reason: "Fixture",
          },
          tool_eoat_result: {
            pair: "tool_eoat",
            result: "COMPATIBLE",
            reason: "Fixture",
          },
          reasons: ["Fixture compatible"],
          warnings: [],
          unknown_relationships: [],
          alternative_compatible_eoats: [],
          evaluation_engine_version: "fixture",
          stored: false,
        },
      });
    if (path.endsWith("/search"))
      return route.fulfill({
        json: [
          {
            category: "machine",
            identifier: "M-1",
            title: "Press 1",
            subtitle: "Molding",
            matched_field: "fixture",
          },
        ],
      });
    if (path === "/api/v1/data-status")
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
    if (path === "/api/v1/machines")
      return route.fulfill({
        json: {
          items: [machine],
          pagination: { page: 1, page_size: 24, total: 1, pages: 1 },
        },
      });
    if (path === "/api/v1/tools")
      return route.fulfill({
        json: {
          items: [tool],
          pagination: { page: 1, page_size: 24, total: 1, pages: 1 },
        },
      });
    if (path === "/api/v1/eoats")
      return route.fulfill({
        json: {
          items: [eoat],
          pagination: { page: 1, page_size: 24, total: 1, pages: 1 },
        },
      });
    return route.fulfill({
      json: path.includes("/machines/")
        ? machine
        : path.includes("/tools/")
          ? tool
          : eoat,
    });
  });
}

test("machine and tool deep links refresh, relate, and render media", async ({
  page,
}) => {
  const seen: import("@playwright/test").Request[] = [];
  await routeApi(page, seen);
  await page.goto("/machines/M-1?tab=media");
  await expect(page.getByRole("heading", { name: "M-1" })).toBeVisible();
  await expect(page.getByRole("img", { name: /Fixture image/ })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "M-1" })).toBeVisible();
  await page.goto("/machines/M-1?tab=relationships");
  await page.getByRole("link", { name: /TOOL-1/ }).click();
  await expect(page.getByRole("heading", { name: "TOOL-1" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "TOOL-1" })).toBeVisible();
  await page.getByRole("link", { name: /EOAT-1/ }).click();
  await expect(page.getByRole("heading", { name: "EOAT-1" })).toBeVisible();
  expect(
    seen.every((request) => !request.headers()["x-eoat-device-token"]),
  ).toBeTruthy();
  expect(
    seen.filter(
      (request) =>
        request.method() !== "GET" && !request.url().includes("fit-checks"),
    ).length,
  ).toBe(0);
});

test("library, Fit Check, QR payload, and responsive layouts are browser-safe", async ({
  page,
}) => {
  const seen: import("@playwright/test").Request[] = [];
  await routeApi(page, seen);
  await page.goto("/library?type=machine");
  await expect(
    page.getByRole("link", { name: /Press 1/ }).first(),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByRole("link", { name: /Press 1/ })).toBeVisible();
  await page.getByRole("textbox", { name: "Search" }).fill("press");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByRole("link", { name: /Press 1/ })).toBeVisible();
  await page.goto("/fit-check?machine=M-1&tool=TOOL-1&eoat=EOAT-1");
  await page.getByRole("button", { name: /Evaluate without saving/ }).click();
  await expect(
    page.getByRole("heading", { name: /compatible/i }),
  ).toBeVisible();
  await expect(page.getByText("Fit Check result")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Recent Fit Checks" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Machine" })).toHaveValue("");
  await page.getByRole("combobox", { name: "Machine" }).click();
  await page.getByRole("option", { name: /Press 1/ }).click();
  await page.getByRole("combobox", { name: "Tool" }).click();
  await page.getByRole("option", { name: /Mold 1/ }).click();
  await page.getByRole("combobox", { name: "EOAT" }).click();
  await page.getByRole("option", { name: /Picker/ }).click();
  await expect(
    page.getByRole("button", { name: "Evaluate without saving" }),
  ).toBeEnabled();
  await page.goto("/machines/M-1");
  await expect(
    page.locator("code").filter({ hasText: "/machines/M-1" }),
  ).toBeVisible();
  for (const [width, height] of [
    [1760, 1080],
    [1440, 900],
    [1280, 820],
    [1024, 768],
    [768, 1024],
    [430, 932],
    [390, 844],
    [360, 800],
  ]) {
    await page.setViewportSize({ width, height });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
  }
  expect(
    seen.some(
      (request) =>
        request.url().includes("fit-checks") && request.method() === "POST",
    ),
  ).toBeTruthy();
});

test("EOAT Library, profile, and Docs & Photos use the same browser-safe photo", async ({
  page,
}) => {
  const seen: import("@playwright/test").Request[] = [];
  await routeApi(page, seen);
  await page.goto("/library?type=eoat");
  const card = page.getByRole("link", { name: /Picker/ }).first();
  await expect(card.locator("img")).toHaveAttribute(
    "src",
    "/api/v1/web-photos/photo-1/thumbnail",
  );

  await card.click();
  const fullImage = page.getByRole("link", {
    name: "Open full-resolution photo for EOAT-1",
  });
  await expect(fullImage).toHaveAttribute(
    "href",
    "/api/v1/web-photos/photo-1/content",
  );

  await page.getByRole("link", { name: "Docs & Photos" }).click();
  const galleryImage = page.locator(".photo-gallery img").first();
  await expect(galleryImage).toHaveAttribute(
    "src",
    "/api/v1/web-photos/photo-1/thumbnail",
  );
  await expect(page.locator(".photo-gallery a").first()).toHaveAttribute(
    "href",
    "/api/v1/web-photos/photo-1/content",
  );
  expect(
    seen.every((request) => !request.headers()["x-eoat-device-token"]),
  ).toBeTruthy();
});

test("Fit Check keeps dedicated searchable Machine, Tool, and EOAT selectors", async ({
  page,
}) => {
  const seen: import("@playwright/test").Request[] = [];
  await routeApi(page, seen);
  await page.goto("/fit-check");
  await expect(page.getByRole("group", { name: /Setup item/i })).toHaveCount(0);
  await expect(
    page.getByRole("combobox", { name: "Entity slot 1 type" }),
  ).toHaveCount(0);
  const machineSelector = page.getByRole("combobox", { name: "Machine" });
  await machineSelector.click();
  await machineSelector.fill("press");
  await expect(page.getByRole("option", { name: /Press 1/ })).toBeVisible();
  await expect(page.getByRole("option")).toHaveCount(1);
  await page.getByRole("option", { name: /Press 1/ }).click();
  await page.getByRole("combobox", { name: "Tool" }).click();
  await page.getByRole("option", { name: /Mold 1/ }).click();
  await page.getByRole("combobox", { name: "EOAT" }).click();
  await page.getByRole("option", { name: /Picker/ }).click();
  await expect(
    page.getByRole("button", { name: "Evaluate without saving" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Evaluate without saving" }).click();
  await expect(page.getByRole("heading", { name: "COMPATIBLE" })).toBeVisible();
  expect(
    seen.filter(
      (request) =>
        request.url().includes("fit-checks/evaluate") &&
        request.method() === "POST",
    ),
  ).toHaveLength(1);
});

test("Mirrorline shell traps overlays, restores Library context, and fades top chrome", async ({
  page,
}) => {
  const seen: import("@playwright/test").Request[] = [];
  await routeApi(page, seen);
  await page.goto("/library?type=machine&page=1");
  await page.getByRole("link", { name: /Press 1/ }).click();
  await expect(page.getByRole("heading", { name: "M-1" })).toBeVisible();
  await page.getByRole("button", { name: "Back to Library" }).click();
  await expect(page).toHaveURL(/\/library\?type=machine&page=1/);
  await expect(
    page.getByRole("link", { name: /Press 1/ }).first(),
  ).toBeVisible();

  const menu = page.getByRole("button", { name: "Open navigation menu" });
  await menu.click();
  const menuDialog = page.getByRole("dialog", { name: "Atlas navigation" });
  await expect(menuDialog).toBeVisible();
  await expect(
    menuDialog.getByRole("button", { name: "Close navigation menu" }),
  ).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(menu).toBeFocused();

  await page.keyboard.press("Control+k");
  await expect(
    page.getByRole("dialog", { name: "Search EOAT Atlas" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await page.goto("/");
  const search = page.getByRole("textbox", {
    name: "Search the EOAT Atlas Library",
  });
  await search.focus();
  await page.keyboard.press("m");
  await expect(search).toHaveValue("m");
  await page.waitForTimeout(150);
  await expect(page.getByRole("button", { name: /Press 1/ })).toBeVisible();
  await expect(
    page.getByRole("dialog", { name: "Search EOAT Atlas" }),
  ).toHaveCount(0);
  await page.keyboard.press("Escape");

  await page.evaluate(() => {
    document.body.style.minHeight = "3000px";
    window.scrollTo(0, 60);
  });
  await expect(page.locator(".atlas-app-shell")).toHaveAttribute(
    "data-scrolled",
    "true",
  );
  expect(seen.every((request) => request.method() === "GET")).toBeTruthy();
});
