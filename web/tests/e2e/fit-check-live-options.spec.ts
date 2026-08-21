import { expect, test } from "@playwright/test";

const runLiveAcceptance = process.env.EOAT_FIT_CHECK_LIVE_ACCEPTANCE === "1";

test.describe("Fit Check live compatibility discovery", () => {
  test.skip(
    !runLiveAcceptance,
    "Requires the isolated production-shaped MySQL rehearsal API; do not replace it with a mocked options response.",
  );

  test("selecting a real machine discovers its known Tool and EOAT before evaluation", async ({
    page,
  }) => {
    await page.goto("/fit-check");

    await page.getByRole("combobox", { name: "Machine" }).click();
    await page.getByRole("option", { name: /^Machine 1 · P4/ }).click();
    await page.getByRole("combobox", { name: "Tool" }).click();
    await expect(
      page.getByRole("option", { name: /Tool 5620030010/ }),
    ).toBeVisible();
    await page.getByRole("option", { name: /Tool 5620030010/ }).click();
    await page.getByRole("combobox", { name: "EOAT" }).click();
    await expect(
      page.getByRole("option", { name: /P4-EOAT-0004/ }),
    ).toBeVisible();
    await page.getByRole("option", { name: /P4-EOAT-0004/ }).click();

    await page.getByRole("button", { name: "Evaluate without saving" }).click();
    await expect(
      page.getByRole("heading", { name: "COMPATIBLE" }),
    ).toBeVisible();
  });
});
