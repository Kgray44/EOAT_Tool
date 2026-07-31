import { expect, test } from "@playwright/test";

const baseMachine = {
  plant_code: "P4",
  plant_name: "Plant 4",
  machine_number: "27",
  machine_name: "Machine 27",
  area: "Plant 4",
  manufacturer: null,
  model: null,
  machine_type: null,
  controller_type: null,
  cleanroom_classification: null,
  status: "Active",
  current_eoat: "NONE_OBSERVED",
  is_active: true,
  row_version: 1,
  press_capacity_tons: null,
  robot_systems: [],
  relationships: [],
};

const relationship = (type: "eoat" | "tool", index: number) => ({
  relationship_type: type,
  identifier: `${type === "eoat" ? "P4-EOAT" : "TOOL"}-${String(index).padStart(4, "0")}-WITH-A-LONG-IDENTIFIER`,
  display_name: `Relationship ${index} with deliberately long evidence-friendly display text`,
  status: index % 2 ? "COMPATIBLE" : "Observed in legacy source",
  reason: index % 2 ? "VERIFIED_SOURCE" : "OBSERVATION_OR_LATER_LIFECYCLE_EVENT",
});

async function routeProfile(
  page: import("@playwright/test").Page,
  relationships: ReturnType<typeof relationship>[],
) {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/current-setup"))
      return route.fulfill({
        json: {
          machine_number: "27",
          current_eoat: "NONE_OBSERVED",
          current_tool: "NONE_OBSERVED",
          verified: false,
          location_semantics: "OBSERVATION_OR_LATER_LIFECYCLE_EVENT",
        },
      });
    if (path.endsWith("/relationships")) return route.fulfill({ json: relationships });
    if (path.endsWith("/web-documents") || path.endsWith("/web-photos") || path.endsWith("/history"))
      return route.fulfill({ json: [] });
    return route.fulfill({ json: { ...baseMachine, relationships } });
  });
}

async function assertNoHorizontalOverflow(page: import("@playwright/test").Page) {
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBeTruthy();
}

test("relationship cards remain compact, centered, responsive, and semantically readable", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });

  // Zero, one, two, three, and many relationships share one component rather
  // than entity-count-specific CSS. Each case is a fresh profile fixture.
  for (const [count, expected] of [[0, 0], [1, 1], [2, 2], [3, 3], [10, 10]] as const) {
    await routeProfile(
      page,
      Array.from({ length: count }, (_, index) => relationship(index % 2 ? "tool" : "eoat", index)),
    );
    await page.goto(`/machines/27?tab=relationships&case=${count}`);
    const cards = page.locator(".relationship-flow__nodes > a");
    await expect(cards).toHaveCount(expected);
    await assertNoHorizontalOverflow(page);
    if (count === 0) {
      await expect(page.getByText("No current EOAT assignment observed")).toBeVisible();
    }
    if (count === 1) {
      const box = await cards.first().boundingBox();
      const container = await cards.first().locator("..").boundingBox();
      expect(box?.width).toBeGreaterThanOrEqual(180);
      expect(box?.width).toBeLessThanOrEqual(240);
      expect(Math.abs((box!.x + box!.width / 2) - (container!.x + container!.width / 2))).toBeLessThanOrEqual(1);
    }
    if (count >= 3) {
      await expect(page.getByText("Historical observation").first()).toBeVisible();
      await expect(page.getByText("Verified compatibility").first()).toBeVisible();
    }
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/machines/27?tab=relationships&case=mobile");
  await assertNoHorizontalOverflow(page);
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "20px";
  });
  await assertNoHorizontalOverflow(page);
});
