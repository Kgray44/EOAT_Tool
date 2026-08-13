import { expect, test, type Page } from "@playwright/test";

const event = {
  event_id: "event-0002",
  occurred_at_utc: "2026-08-11T18:00:00Z",
  actor: { type: "user", id: "42", display_name: "Development Administrator", directory_name: "dev.admin" },
  action: "UPDATE",
  action_category: "BUSINESS_DATA",
  entity: { type: "EOAT", id: "54", display_id: "CL-EOAT-0054" },
  changed_fields: ["location", "password"],
  before: { location: "Storage", password: { _audit_value: "REDACTED" } },
  after: { location: "Machine 27", password: { _audit_value: "REDACTED" } },
  reason_or_note: "Approved setup change",
  source_client: "web",
  request_id: "request-123",
  correlation_id: "correlation-456",
  transaction_id: "transaction-789",
  operation: "PATCH /api/v1/eoats/54",
  result: "DENIED",
  schema_version: 1,
};

const relatedEvent = {
  ...event,
  event_id: "event-0001",
  occurred_at_utc: "2026-08-11T17:59:00Z",
  action: "LOCATION_CHANGE",
  changed_fields: ["location"],
  result: "SUCCESS",
};

const machineEvent = {
  ...event,
  event_id: "event-machine-0001",
  entity: { type: "Machine", id: "machine-27", display_id: "27" },
};

const toolEvent = {
  ...event,
  event_id: "event-tool-0001",
  entity: { type: "Tool", id: "tool-88", display_id: "4611380030" },
};

async function mockAdminApi(page: Page) {
  await page.route("**/api/v1/admin/**", async (route) => {
    const url = new URL(route.request().url());
    const detail = [event, machineEvent, toolEvent].find((candidate) => url.pathname.endsWith(`/audit/events/${candidate.event_id}`));
    const body = url.pathname.endsWith("/audit/catalog")
      ? { actions: ["UPDATE", "LOCATION_CHANGE"], action_categories: ["BUSINESS_DATA", "SYSTEM_OPERATIONS"], entity_types: ["EOAT", "Machine", "Tool"], results: ["DENIED", "SUCCESS"], sources: ["web"] }
      : url.pathname.endsWith("/overview")
        ? { api_version: "1.4.0", schema_revision: "20260811_0006", audit_schema_version: 1, observation_time_utc: event.occurred_at_utc, writes_enabled: false, environment: "development", api_status: "healthy", database_status: "healthy", audit_status: "healthy", metrics: { events_today: 2, events_last_24_hours: 2, successful_events_last_24_hours: 1, failed_events_last_24_hours: 0, denied_events_last_24_hours: 1, security_events_last_24_hours: 1, administrative_events_last_24_hours: 0, unique_actors_last_24_hours: 1 }, recent_events: [event] }
        : detail
          ? detail
          : { items: [event, relatedEvent], page: 1, page_size: 50, total: 2, sort: "occurred_at_utc:desc,persisted_sequence:desc" };
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
  });
}

test("administrator can deep-link to the overview and ledger investigation", async ({ page }) => {
  await mockAdminApi(page);
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Administrative overview" })).toBeVisible();
  await expect(page.getByText("Events today (UTC)")).toBeVisible();
  await expect(page.getByText("Events today (UTC)").locator("..").getByText("2", { exact: true })).toBeVisible();
  await page.goto("/admin/audit?result=DENIED&correlation_id=correlation-456");
  await expect(page.getByRole("heading", { name: "Global Audit Ledger" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Development Administrator" }).first()).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Result")).toHaveValue("DENIED");
  await expect(page.getByLabel("Correlation ID")).toHaveValue("correlation-456");
  await page.getByRole("button", { name: "My activity" }).click();
  await expect(page).toHaveURL(/current_user_changes=true/);
  await page.getByLabel("Page size").selectOption("100");
  await expect(page).toHaveURL(/page_size=100/);
  await page.getByLabel("Entity type").selectOption("EOAT");
  await expect(page).toHaveURL(/entity_type=EOAT/);
  await page.getByRole("button", { name: "Administrative operations" }).click();
  await expect(page).toHaveURL(/administrative_events_only=true/);
  await page.getByLabel("Action").selectOption("UPDATE");
  await expect(page).toHaveURL(/action=UPDATE/);
  await page.getByLabel("Source").selectOption("web");
  await expect(page).toHaveURL(/source=web/);
  await page.getByLabel("Actor").fill("dev.admin");
  await expect(page).toHaveURL(/actor=dev.admin/);
  await page.getByLabel("Entity ID").fill("54");
  await expect(page).toHaveURL(/entity_id=54/);
  await page.getByLabel("Request ID").fill("request-123");
  await expect(page).toHaveURL(/request_id=request-123/);
  await page.goBack();
  await expect(page.getByLabel("Request ID")).toHaveValue("");
  await expect(page.getByLabel("Entity ID")).toHaveValue("54");
});

test("event detail renders structured redaction and correlation navigation without mutation controls", async ({ page }) => {
  await mockAdminApi(page);
  await page.goto(`/admin/audit/events/${event.event_id}`);
  await expect(page.getByRole("heading", { name: "Audit event detail" })).toBeVisible();
  await expect(page.getByText("Development Administrator")).toBeVisible();
  await expect(page.getByText("UTC: 2026-08-11T18:00:00Z")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open normal profile" })).toHaveAttribute("href", "/eoats/CL-EOAT-0054");
  await expect(page.getByRole("link", { name: "request-123" })).toHaveAttribute("href", "/admin/audit?request_id=request-123");
  await expect(page.getByText("Redacted").first()).toBeVisible();
  await expect(page.getByRole("link", { name: /LOCATION_CHANGE.*CL-EOAT-0054/ })).toBeVisible();
  await expect(page.getByRole("link", { name: "View all events with this correlation ID" })).toHaveAttribute("href", "/admin/audit?correlation_id=correlation-456");
  await expect(page.getByRole("button", { name: /delete|edit|archive|restore/i })).toHaveCount(0);
});

test("Machine and Tool evidence links remain normal-profile navigation", async ({ page }) => {
  await mockAdminApi(page);
  await page.goto(`/admin/audit/events/${machineEvent.event_id}`);
  await expect(page.getByRole("link", { name: "Open normal profile" })).toHaveAttribute("href", "/machines/27");
  await page.goto(`/admin/audit/events/${toolEvent.event_id}`);
  await expect(page.getByRole("link", { name: "Open normal profile" })).toHaveAttribute("href", "/tools/4611380030");
  await expect(page.getByRole("link", { name: /Audit ledger/ })).toHaveCount(1);
});

test("historical events without a canonical profile identifier do not invent a normal-profile link", async ({ page }) => {
  await mockAdminApi(page);
  await page.route("**/api/v1/admin/audit/events/event-0002", async (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ ...event, entity: { type: "EOAT", id: "historical-only", display_id: null } }) }));
  await page.goto("/admin/audit/events/event-0002");
  await expect(page.getByText("No canonical normal-profile link is available for this entity type.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open normal profile" })).toHaveCount(0);
});

test("narrow audit view retains accessible navigation and evidence", async ({ page }) => {
  await mockAdminApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/admin/audit");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#admin-content")).toBeFocused();
  await expect(page.getByRole("navigation", { name: "Administration" })).toBeVisible();
  await expect(page.getByRole("link", { name: /UPDATE.*CL-EOAT-0054/ })).toBeVisible();
});

test("denied and spoofed browser state cannot reveal Administrator evidence", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("role", "ADMINISTRATOR"));
  await page.route("**/api/v1/admin/**", async (route) => route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ message: "Administrator access required", request_id: "request-denied" }) }));
  await page.goto("/admin/audit");
  await expect(page.getByRole("heading", { name: "Administrator access required" })).toBeVisible();
  await expect(page.getByText("Administrator data was not returned.")).toBeVisible();
  await expect(page.getByRole("table")).toHaveCount(0);
});

test("detail not-found and backend-failure states are controlled", async ({ page }) => {
  await page.route("**/api/v1/admin/audit/events/not-recorded", async (route) => route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ message: "not found", request_id: "request-missing" }) }));
  await page.goto("/admin/audit/events/not-recorded");
  await expect(page.getByRole("heading", { name: "Audit event not found" })).toBeVisible();
  await expect(page.getByText("request-missing")).toBeVisible();

  await page.unrouteAll();
  await page.route("**/api/v1/admin/**", async (route) => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ message: "Database unavailable", request_id: "request-outage" }) }));
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Administrator data could not load" })).toBeVisible();
  await expect(page.getByText("request-outage")).toBeVisible();
});

test("server pagination and intentional empty results remain readable", async ({ page }) => {
  await page.route("**/api/v1/admin/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/audit/catalog")) {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ actions: ["UPDATE"], action_categories: ["BUSINESS_DATA"], entity_types: ["EOAT"], results: ["SUCCESS"], sources: ["web"] }) });
      return;
    }
    const pageNumber = Number(url.searchParams.get("page") ?? "1");
    const empty = url.searchParams.get("search") === "no-match";
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ items: empty ? [] : [pageNumber === 1 ? event : relatedEvent], page: pageNumber, page_size: 1, total: empty ? 0 : 2, sort: "occurred_at_utc:desc,persisted_sequence:desc" }) });
  });
  await page.goto("/admin/audit?page_size=1");
  await expect(page.getByRole("link", { name: /UPDATE.*CL-EOAT-0054/ })).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page).toHaveURL(/page=2/);
  await expect(page.getByRole("link", { name: /LOCATION_CHANGE.*CL-EOAT-0054/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /UPDATE.*CL-EOAT-0054/ })).toHaveCount(0);
  await page.goto("/admin/audit?search=no-match");
  await expect(page.getByText("No audit events match these filters.")).toBeVisible();
});
