import { expect, test } from "@playwright/test";

const liveBaseUrl = process.env.EOAT_LIVE_BASE_URL;

test.skip(
  !liveBaseUrl,
  "EOAT_LIVE_BASE_URL is required for the post-activation live-browser gate",
);

test("live Machine 27 is truthful, read-only, and free of redundant relationship labels", async ({
  page,
}) => {
  const mutationRequests: string[] = [];
  const consoleErrors: string[] = [];
  const exposedTokenRequests: string[] = [];
  page.on("request", (request) => {
    if (!["GET", "HEAD"].includes(request.method())) {
      mutationRequests.push(`${request.method()} ${request.url()}`);
    }
    if (request.headers()["x-eoat-device-token"]) {
      exposedTokenRequests.push(request.url());
    }
  });
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.goto("/machines/27", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "27" })).toBeVisible();
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "27" })).toBeVisible();
  await expect(page.getByText(/Not recorded:/)).toBeVisible();
  await expect(
    page.getByLabel("Overview").getByText("Active", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("UNKNOWN_NOT_VERIFIED")).toHaveCount(0);
  await expect(
    page.getByText("OBSERVATION_OR_LATER_LIFECYCLE_EVENT"),
  ).toHaveCount(0);

  const relationships = page.locator(".relationship-list");
  await expect(
    relationships.getByRole("link", { name: "P4-EOAT-0026", exact: true }),
  ).toHaveCount(1);
  await expect(
    relationships.getByRole("link", { name: "6920150021", exact: true }),
  ).toHaveCount(1);
  const relationshipText = await relationships.innerText();
  expect(relationshipText).not.toContain("Tool Tool");
  expect(relationshipText).not.toContain("6920150021 — Tool 6920150021");
  expect(relationshipText).not.toContain("P4-EOAT-0026 — P4-EOAT-0026");

  await expect(page.getByText("No photos recorded")).toBeVisible();
  await expect(page.getByText("No documents recorded")).toBeVisible();
  const api404 = await page.evaluate(async () => {
    const response = await fetch("/api/v1/not-a-real-route");
    return {
      status: response.status,
      contentType: response.headers.get("content-type"),
      body: await response.json(),
    };
  });
  expect(api404).toMatchObject({
    status: 404,
    contentType: expect.stringContaining("application/json"),
    body: { detail: "Not Found" },
  });
  expect(mutationRequests).toEqual([]);
  expect(exposedTokenRequests).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
