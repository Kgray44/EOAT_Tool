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

async function mockAdminApi(page: Page) {
  await page.route("**/api/v1/admin/**", async (route) => {
    const url = new URL(route.request().url());
    const body = url.pathname.endsWith("/audit/catalog")
      ? { actions: ["UPDATE"], action_categories: ["BUSINESS_DATA"], results: ["DENIED"], sources: ["web"] }
      : url.pathname.endsWith("/overview")
        ? { api_version: "1.4.0", schema_revision: "20260811_0006", audit_schema_version: 1, observation_time_utc: event.occurred_at_utc, writes_enabled: false, environment: "development", api_status: "healthy", database_status: "healthy", audit_status: "healthy", metrics: { events_today: 2, events_last_24_hours: 2, successful_events_last_24_hours: 1, failed_events_last_24_hours: 0, denied_events_last_24_hours: 1, security_events_last_24_hours: 1, administrative_events_last_24_hours: 0, unique_actors_last_24_hours: 1 }, recent_events: [event] }
        : url.pathname.endsWith(`/audit/events/${event.event_id}`)
          ? event
          : { items: [event, relatedEvent], page: 1, page_size: 50, total: 2, sort: "occurred_at_utc:desc,event_id:desc" };
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
  });
}

test("administrator can deep-link to the overview and ledger investigation", async ({ page }) => {
  await mockAdminApi(page);
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Administrative overview" })).toBeVisible();
  await expect(page.getByText("Events today (UTC)")).toBeVisible();
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
});

test("event detail renders structured redaction and correlation navigation without mutation controls", async ({ page }) => {
  await mockAdminApi(page);
  await page.goto(`/admin/audit/events/${event.event_id}`);
  await expect(page.getByRole("heading", { name: "Audit event detail" })).toBeVisible();
  await expect(page.getByText("Redacted").first()).toBeVisible();
  await expect(page.getByRole("link", { name: /LOCATION_CHANGE.*CL-EOAT-0054/ })).toBeVisible();
  await expect(page.getByRole("link", { name: "View all events with this correlation ID" })).toHaveAttribute("href", "/admin/audit?correlation_id=correlation-456");
  await expect(page.getByRole("button", { name: /delete|edit|archive|restore/i })).toHaveCount(0);
});

test("narrow audit view retains accessible navigation and evidence", async ({ page }) => {
  await mockAdminApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/admin/audit");
  await expect(page.getByRole("navigation", { name: "Administration" })).toBeVisible();
  await expect(page.getByRole("link", { name: /UPDATE.*CL-EOAT-0054/ })).toBeVisible();
});
