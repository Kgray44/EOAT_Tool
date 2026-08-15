import { expect, test, type Page } from "@playwright/test";

const liveBaseUrl = process.env.EOAT_LIVE_BASE_URL;

test.skip(
  !liveBaseUrl,
  "EOAT_LIVE_BASE_URL is required for the all-machine live-browser gate",
);

type MachineSummary = { machine_number: string };
type MachineList = { items: MachineSummary[]; pagination: { total: number } };

async function productionMachines(): Promise<string[]> {
  const response = await fetch(
    `${liveBaseUrl}/api/v1/machines?page=1&page_size=250`,
  );
  expect(response.ok).toBeTruthy();
  const body = (await response.json()) as MachineList;
  expect(body.items).toHaveLength(body.pagination.total);
  return body.items.map((item) => item.machine_number);
}

async function assertTruthfulMachinePage(page: Page, number: string) {
  const mutationRequests: string[] = [];
  const tokenRequests: string[] = [];
  const consoleErrors: string[] = [];
  page.on("request", (request) => {
    if (!["GET", "HEAD"].includes(request.method())) {
      mutationRequests.push(`${request.method()} ${request.url()}`);
    }
    if (request.headers()["x-eoat-device-token"])
      tokenRequests.push(request.url());
  });
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.goto(`/machines/${encodeURIComponent(number)}`, {
    waitUntil: "domcontentloaded",
  });
  await expect(
    page.getByRole("heading", { name: number, exact: true }),
  ).toBeVisible();
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(
    page.getByRole("heading", { name: number, exact: true }),
  ).toBeVisible();
  await expect(page.locator(".state--loading")).toHaveCount(0);

  const text = await page.locator("main").innerText();
  expect(text).not.toContain("UNKNOWN_NOT_VERIFIED");
  expect(text).not.toContain("OBSERVATION_OR_LATER_LIFECYCLE_EVENT");
  expect(text).not.toMatch(/\b(true|false)\b/);
  expect(text).not.toContain("Tool Tool");
  expect(text).not.toContain("EOAT EOAT");
  expect(text).not.toMatch(/([^\n]+)\s+—\s+\1/);
  expect(text).not.toContain("Unable to load status");
  expect(text).not.toContain("Unexpected Application Error");

  const setupResponse = await page.request.get(
    `/api/v1/machines/${encodeURIComponent(number)}/current-setup`,
  );
  expect(setupResponse.ok()).toBeTruthy();
  const setup = (await setupResponse.json()) as { current_tool?: unknown };
  if (setup.current_tool === "UNKNOWN_NOT_VERIFIED") {
    await expect(
      page
        .getByLabel("Relationship overview")
        .getByText("Current tool / mold not verified"),
    ).toBeVisible();
    await expect(page.getByText("No verified tools recorded")).toHaveCount(0);
    await expect(
      page.locator('a[href="/tools/UNKNOWN_NOT_VERIFIED"]'),
    ).toHaveCount(0);
  }
  if (setup.current_tool === "NONE_OBSERVED") {
    await expect(
      page
        .getByLabel("Relationship overview")
        .getByText("No current tool / mold assignment observed"),
    ).toBeVisible();
  }

  const relationshipItems = page.locator(".relationship-list li");
  const relationshipCount = await relationshipItems.count();
  if (relationshipCount === 0) {
    await expect(page.getByText("No current relationships")).toBeVisible();
  } else {
    const identities = await relationshipItems.evaluateAll((items) =>
      items.map((item) => {
        const type = item.querySelector("small")?.textContent?.trim() ?? "";
        const identifier = item.querySelector("a")?.textContent?.trim() ?? "";
        return `${type}\u0000${identifier}`;
      }),
    );
    expect(new Set(identities).size).toBe(identities.length);
  }

  expect(mutationRequests).toEqual([]);
  expect(tokenRequests).toEqual([]);
  expect(consoleErrors).toEqual([]);
}

test("every production machine profile is truthful, read-only, and refresh-safe", async ({
  page,
}) => {
  test.setTimeout(10 * 60_000);
  const machines = await productionMachines();
  expect(machines.length).toBeGreaterThan(0);
  for (const number of machines) await assertTruthfulMachinePage(page, number);
});

test("representative production machine profiles remain usable on tablet and phone", async ({
  browser,
}) => {
  test.setTimeout(3 * 60_000);
  const machines = await productionMachines();
  const samples = [
    ...new Set([
      machines[0],
      machines[Math.floor(machines.length / 2)],
      machines.at(-1),
    ]),
  ];
  for (const [index, number] of samples.entries()) {
    const context = await browser.newContext({
      viewport:
        index % 2 === 0
          ? { width: 820, height: 1180 }
          : { width: 390, height: 844 },
    });
    const page = await context.newPage();
    await assertTruthfulMachinePage(page, number);
    await context.close();
  }
});
