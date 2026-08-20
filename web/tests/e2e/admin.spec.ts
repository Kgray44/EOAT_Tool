import { expect, test, type Page } from "@playwright/test";

const event = {
  event_id: "event-0002",
  occurred_at_utc: "2026-08-11T18:00:00Z",
  actor: {
    type: "user",
    id: "42",
    display_name: "Development Administrator",
    directory_name: "dev.admin",
  },
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
  await page.route("**/api/v1/auth/session", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        authenticated: true,
        identity: { display_name: "Corporate Administrator" },
        roles: ["ADMINISTRATOR"],
        permissions: ["*"],
        scope: "application",
      }),
    });
  });
  await page.route("**/api/v1/auth/status", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        provider: "kerberos_form",
        status: "ready",
        mapping_configured: true,
      }),
    });
  });
  await page.route("**/api/v1/admin/**", async (route) => {
    const url = new URL(route.request().url());
    const detail = [event, machineEvent, toolEvent].find((candidate) =>
      url.pathname.endsWith(`/audit/events/${candidate.event_id}`),
    );
    const body = url.pathname.endsWith("/audit/catalog")
      ? {
          actions: ["UPDATE", "LOCATION_CHANGE"],
          action_categories: ["BUSINESS_DATA", "SYSTEM_OPERATIONS"],
          entity_types: ["EOAT", "Machine", "Tool"],
          results: ["DENIED", "SUCCESS"],
          sources: ["web"],
        }
      : url.pathname.endsWith("/overview")
        ? {
            api_version: "1.4.0",
            schema_revision: "20260811_0006",
            audit_schema_version: 1,
            observation_time_utc: event.occurred_at_utc,
            writes_enabled: false,
            environment: "development",
            api_status: "healthy",
            database_status: "healthy",
            audit_status: "healthy",
            metrics: {
              events_today: 2,
              events_last_24_hours: 2,
              successful_events_last_24_hours: 1,
              failed_events_last_24_hours: 0,
              denied_events_last_24_hours: 1,
              security_events_last_24_hours: 1,
              administrative_events_last_24_hours: 0,
              unique_actors_last_24_hours: 1,
            },
            recent_events: [event],
          }
        : detail
          ? detail
          : {
              items: [event, relatedEvent],
              page: 1,
              page_size: 50,
              total: 2,
              sort: "occurred_at_utc:desc,persisted_sequence:desc",
            };
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
}

test("existing corporate Administrator session opens a governed page without a second login", async ({
  page,
}) => {
  await mockAdminApi(page);
  await page.goto("/admin/data");
  await expect(
    page.getByRole("heading", { name: "Governed data management" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Corporate Administrator sign-in" }),
  ).not.toBeVisible();
});

test("administrator can deep-link to the overview and ledger investigation", async ({
  page,
}) => {
  await mockAdminApi(page);
  await page.goto("/admin");
  await expect(
    page.getByRole("heading", { name: "Administrative overview" }),
  ).toBeVisible();
  await expect(page.getByText("Events today (UTC)")).toBeVisible();
  await expect(
    page
      .getByText("Events today (UTC)")
      .locator("..")
      .getByText("2", { exact: true }),
  ).toBeVisible();
  await page.goto("/admin/audit?result=DENIED&correlation_id=correlation-456");
  await expect(
    page.getByRole("heading", { name: "Global Audit Ledger" }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "Development Administrator" }).first(),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Result")).toHaveValue("DENIED");
  await expect(page.getByLabel("Correlation ID")).toHaveValue(
    "correlation-456",
  );
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

test("event detail renders structured redaction and correlation navigation without mutation controls", async ({
  page,
}) => {
  await mockAdminApi(page);
  await page.goto(`/admin/audit/events/${event.event_id}`);
  await expect(
    page.getByRole("heading", { name: "Audit event detail" }),
  ).toBeVisible();
  await expect(page.getByText("Development Administrator")).toBeVisible();
  await expect(page.getByText("UTC: 2026-08-11T18:00:00Z")).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Open normal profile" }),
  ).toHaveAttribute("href", "/eoats/CL-EOAT-0054");
  await expect(page.getByRole("link", { name: "request-123" })).toHaveAttribute(
    "href",
    "/admin/audit?request_id=request-123",
  );
  await expect(page.getByText("Redacted").first()).toBeVisible();
  await expect(
    page.getByRole("link", { name: /LOCATION_CHANGE.*CL-EOAT-0054/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", {
      name: "View all events with this correlation ID",
    }),
  ).toHaveAttribute("href", "/admin/audit?correlation_id=correlation-456");
  await expect(
    page.getByRole("button", { name: /delete|edit|archive|restore/i }),
  ).toHaveCount(0);
});

test("Machine and Tool evidence links remain normal-profile navigation", async ({
  page,
}) => {
  await mockAdminApi(page);
  await page.goto(`/admin/audit/events/${machineEvent.event_id}`);
  await expect(
    page.getByRole("link", { name: "Open normal profile" }),
  ).toHaveAttribute("href", "/machines/27");
  await page.goto(`/admin/audit/events/${toolEvent.event_id}`);
  await expect(
    page.getByRole("link", { name: "Open normal profile" }),
  ).toHaveAttribute("href", "/tools/4611380030");
  await expect(page.getByRole("link", { name: /Audit ledger/ })).toHaveCount(1);
});

test("historical events without a canonical profile identifier do not invent a normal-profile link", async ({
  page,
}) => {
  await mockAdminApi(page);
  await page.route("**/api/v1/admin/audit/events/event-0002", async (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ...event,
        entity: { type: "EOAT", id: "historical-only", display_id: null },
      }),
    }),
  );
  await page.goto("/admin/audit/events/event-0002");
  await expect(
    page.getByText(
      "No canonical normal-profile link is available for this entity type.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Open normal profile" }),
  ).toHaveCount(0);
});

test("narrow audit view retains accessible navigation and evidence", async ({
  page,
}) => {
  await mockAdminApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/admin/audit");
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("link", { name: "Skip to main content" }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#admin-content")).toBeFocused();
  await expect(
    page.getByRole("navigation", { name: "Administration" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: /UPDATE.*CL-EOAT-0054/ }),
  ).toBeVisible();
});

test("denied and spoofed browser state cannot reveal Administrator evidence", async ({
  page,
}) => {
  await page.addInitScript(() => localStorage.setItem("role", "ADMINISTRATOR"));
  await page.route("**/api/v1/admin/**", async (route) =>
    route.fulfill({
      status: 403,
      contentType: "application/json",
      body: JSON.stringify({
        message: "Administrator access required",
        request_id: "request-denied",
      }),
    }),
  );
  await page.goto("/admin/audit");
  await expect(
    page.getByRole("heading", { name: "Administrator access required" }),
  ).toBeVisible();
  await expect(
    page.getByText("Administrator data was not returned."),
  ).toBeVisible();
  await expect(page.getByRole("table")).toHaveCount(0);
});

test("governed Viewer assignment commits, refreshes authoritative access, and preserves directory navigation", async ({
  page,
}) => {
  await page.context().addCookies([
    {
      name: "eoat_corporate_csrf",
      value: "test-csrf-proof",
      url: "http://127.0.0.1:4173",
    },
  ]);
  await mockAdminApi(page);
  let role = "VIEWER";
  let source = "default";
  let rowVersion = 1;
  let committed = false;
  const summary = () => ({
    user_id: "wyatt-1",
    name: "Wyatt Jones",
    corporate_identity: "wyatt.jones@gwplastics.com",
    provider: "kerberos_form",
    effective_role: role,
    access_source: source,
    group_roles: [],
    explicit_role: role === "VIEWER" ? null : role,
    explicit_denied: false,
    status: "active",
    first_sign_in: "2026-08-20T12:00:00Z",
    last_sign_in: "2026-08-20T12:30:00Z",
    sign_in_count: 1,
    active_sessions: role === "VIEWER" ? 1 : 0,
    row_version: rowVersion,
  });
  await page.route("**/api/v1/admin/users**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.endsWith("/access/preview")) {
      const body = request.postDataJSON();
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          user_id: "wyatt-1",
          action: body.action,
          before: summary(),
          after: {
            ...summary(),
            effective_role: body.role_code,
            access_source: "explicit_user_assignment",
          },
          confirmation: "USER ACCESS ASSIGN wyatt-1",
        }),
      });
      return;
    }
    if (url.pathname.endsWith("/access/commit")) {
      const body = request.postDataJSON();
      expect(request.method()).toBe("POST");
      expect(body).toMatchObject({
        action: "assign",
        role_code: "ADMINISTRATOR",
        reason: "Testing",
        expected_row_version: 1,
        confirmation: "USER ACCESS ASSIGN wyatt-1",
      });
      expect(request.headers()["idempotency-key"]).toBeTruthy();
      role = "ADMINISTRATOR";
      source = "explicit_user_assignment";
      rowVersion += 1;
      committed = true;
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          user: summary(),
          audit_event_id: "role-assignment-receipt",
          revoked_session_count: 1,
        }),
      });
      return;
    }
    if (url.pathname === "/api/v1/admin/users/wyatt-1") {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          ...summary(),
          sessions: [],
          access_history: committed
            ? [
                {
                  event_id: "role-assignment-receipt",
                  occurred_at: "2026-08-20T12:31:00Z",
                  action: "ROLE_MAPPING_CHANGE",
                  result: "SUCCESS",
                  reason: "Testing",
                  actor: "Corporate Administrator",
                },
              ]
            : [],
        }),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [summary()],
        page: 2,
        page_size: 50,
        total: 1,
        sort: "name:asc",
      }),
    });
  });

  await page.goto(
    "/admin/users/wyatt-1?search=Wyatt&sort=name&direction=asc&page=2",
  );
  await expect(page.getByText("VIEWER", { exact: true }).first()).toBeVisible();
  await page
    .getByRole("combobox", { name: "Role", exact: true })
    .selectOption("ADMINISTRATOR");
  await page.getByLabel("Reason").fill("Testing");
  await page.getByRole("button", { name: "Preview change" }).click();
  await page.getByRole("textbox").nth(1).fill("USER ACCESS ASSIGN wyatt-1");
  await page.getByRole("button", { name: "Confirm governed change" }).click();
  await expect.poll(() => committed).toBe(true);
  await expect(
    page.getByText("ADMINISTRATOR", { exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByText("explicit user assignment", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("ROLE_MAPPING_CHANGE")).toBeVisible();
  await page.getByRole("link", { name: "← Back to Users & Access" }).click();
  await expect(page).toHaveURL(
    /search=Wyatt.*sort=name.*direction=asc.*page=2/,
  );
  await expect(page.getByRole("cell", { name: "ADMINISTRATOR" })).toBeVisible();
  await page.goto("/admin/users/wyatt-1");
  await expect(
    page.getByText("ADMINISTRATOR", { exact: true }).first(),
  ).toBeVisible();
});

test("direct Admin navigation honors the saved Atlas Light preference", async ({
  page,
}) => {
  await page.addInitScript(() =>
    localStorage.setItem(
      "eoat-atlas-mirrorline-settings-v1",
      JSON.stringify({ theme: "light" }),
    ),
  );
  await mockAdminApi(page);
  await page.goto("/admin");
  await expect(page.locator("html")).toHaveAttribute(
    "data-atlas-theme",
    "light",
  );
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute(
    "data-atlas-theme",
    "light",
  );
});

test("detail not-found and backend-failure states are controlled", async ({
  page,
}) => {
  await page.route("**/api/v1/admin/audit/events/not-recorded", async (route) =>
    route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({
        message: "not found",
        request_id: "request-missing",
      }),
    }),
  );
  await page.goto("/admin/audit/events/not-recorded");
  await expect(
    page.getByRole("heading", { name: "Audit event not found" }),
  ).toBeVisible();
  await expect(page.getByText("request-missing")).toBeVisible();

  await page.unrouteAll();
  await page.route("**/api/v1/admin/**", async (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        message: "Database unavailable",
        request_id: "request-outage",
      }),
    }),
  );
  await page.goto("/admin");
  await expect(
    page.getByRole("heading", { name: "Administrator data could not load" }),
  ).toBeVisible();
  await expect(page.getByText("request-outage")).toBeVisible();
});

test("server pagination and intentional empty results remain readable", async ({
  page,
}) => {
  await page.route("**/api/v1/admin/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/audit/catalog")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          actions: ["UPDATE"],
          action_categories: ["BUSINESS_DATA"],
          entity_types: ["EOAT"],
          results: ["SUCCESS"],
          sources: ["web"],
        }),
      });
      return;
    }
    const pageNumber = Number(url.searchParams.get("page") ?? "1");
    const empty = url.searchParams.get("search") === "no-match";
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: empty ? [] : [pageNumber === 1 ? event : relatedEvent],
        page: pageNumber,
        page_size: 1,
        total: empty ? 0 : 2,
        sort: "occurred_at_utc:desc,persisted_sequence:desc",
      }),
    });
  });
  await page.goto("/admin/audit?page_size=1");
  await expect(
    page.getByRole("link", { name: /UPDATE.*CL-EOAT-0054/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page).toHaveURL(/page=2/);
  await expect(
    page.getByRole("link", { name: /LOCATION_CHANGE.*CL-EOAT-0054/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: /UPDATE.*CL-EOAT-0054/ }),
  ).toHaveCount(0);
  await page.goto("/admin/audit?search=no-match");
  await expect(
    page.getByText("No audit events match these filters."),
  ).toBeVisible();
});

async function mockPhase4Api(page: Page) {
  const checks = [
    {
      check_id: "api.self",
      subsystem: "api",
      state: "HEALTHY",
      safe_detail: "API responds.",
      remediation_hint: "None.",
      source: "server",
      observed_at_utc: "2026-08-13T19:00:00Z",
      timeout_seconds: 5,
      request_id: "req-phase4",
    },
    {
      check_id: "operations.ledger",
      subsystem: "operations",
      state: "FAILED",
      safe_detail: "Operation ledger is unavailable.",
      remediation_hint: "Restore the approved runtime grant.",
      source: "server",
      observed_at_utc: "2026-08-13T19:00:00Z",
      timeout_seconds: 5,
      request_id: "req-phase4",
    },
  ];
  await page.route("**/api/v1/auth/status", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        provider: null,
        status: "unavailable",
        mapping_configured: false,
      }),
    });
  });
  await page.route("**/api/v1/admin/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/session/rehearsal")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          session_reference: "phase4-session",
          expires_at: "2026-08-13T20:00:00Z",
          csrf_token: "phase4-csrf",
          actor: {
            display_name: "Development Administrator",
            role: "ADMINISTRATOR",
          },
          environment: "development",
        }),
      });
      return;
    }
    if (url.pathname.endsWith("/diagnostics")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          observation_time_utc: "2026-08-13T19:00:00Z",
          checks,
          by_subsystem: Object.fromEntries(
            checks.map((check) => [check.subsystem, check]),
          ),
        }),
      });
      return;
    }
    if (url.pathname.endsWith("/integrity/scans")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          operation_id: "integrity-1",
          status: "COMPLETED",
          finding_count: 1,
          findings: [
            {
              finding_id: "finding-1",
              severity: "WARNING",
              category: "DUPLICATE_ACTIVE_RELATIONSHIP",
              explanation: "Synthetic controlled finding.",
              recommended_next_step: "Review through a governed workflow.",
            },
          ],
          audit_event_id: "audit-integrity-1",
        }),
      });
      return;
    }
    if (url.pathname.endsWith("/fixture-recovery/step-up")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          step_up_reference: "step-up-1",
          expires_at: "2026-08-13T19:05:00Z",
          rehearsal_only: true,
        }),
      });
      return;
    }
    if (url.pathname.endsWith("/fixture-recovery/preview")) {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          operation_id: "danger-1",
          preview_reference: "preview-1",
          expires_at: "2026-08-13T19:10:00Z",
          target: { fixture_namespace: "phase4-browser-test", target_count: 2 },
          typed_confirmation: "PURGE PHASE4 TEST FIXTURES phase4-browser-test",
          preconditions: [
            {
              name: "fresh_step_up",
              state: "PASS",
              detail: "Scoped proof is current.",
            },
            {
              name: "recovery_point",
              state: "PASS",
              detail: "Validated test recovery point is available.",
            },
          ],
        }),
      });
      return;
    }
    if (url.pathname.endsWith("/fixture-recovery/commit")) {
      const body = route.request().postDataJSON();
      if (
        body.confirmation !== "PURGE PHASE4 TEST FIXTURES phase4-browser-test"
      ) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            operation_id: "danger-1",
            status: "DENIED",
            message:
              "Typed confirmation does not exactly match the test-only target.",
            audit_event_id: "audit-danger-denied",
          }),
        });
        return;
      }
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          operation_id: "danger-1",
          status: "COMPLETED",
          removed_count: 2,
          audit_event_id: "audit-danger-complete",
        }),
      });
      return;
    }
    if (
      url.pathname.endsWith("/audit/exports") ||
      url.pathname.endsWith("/support-bundles")
    ) {
      await route.fulfill({
        contentType: "application/json",
        headers: {
          "Content-Disposition": 'attachment; filename="phase4-evidence.json"',
          "X-EOAT-Export-Id": "export-1",
        },
        body: JSON.stringify({ manifest: { export_id: "export-1" } }),
      });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [],
        page: 1,
        page_size: 50,
        total: 0,
        sort: "occurred_at_utc:desc",
      }),
    });
  });
}

test("Phase 4 diagnostics isolate a failure and the keyboard Danger rehearsal requires exact confirmation", async ({
  page,
}) => {
  await mockPhase4Api(page);
  await page.goto("/admin/diagnostics");
  await expect(
    page.getByRole("heading", { name: "Diagnostics" }),
  ).toBeVisible();
  await expect(
    page.getByText("Operation ledger is unavailable."),
  ).toBeVisible();
  await expect(page.getByText("API responds.")).toBeVisible();

  await page.goto("/admin/danger-zone");
  await page
    .getByLabel("Development/test rehearsal secret")
    .fill("phase4-browser-secret");
  await page.getByRole("button", { name: "Start governed session" }).click();
  await expect(
    page.getByRole("heading", { name: "Danger Zone" }),
  ).toBeVisible();
  await page
    .getByLabel("Phase 4 fixture namespace")
    .fill("phase4-browser-test");
  await page
    .getByLabel("Development/test step-up secret")
    .fill("phase4-browser-secret");
  await page
    .getByRole("button", { name: "Verify fresh rehearsal step-up" })
    .click();
  await page
    .getByRole("button", { name: "Preview exact test fixture impact" })
    .click();
  const confirmation = page.getByLabel("Typed confirmation");
  await expect(confirmation).toBeFocused();
  const execute = page.getByRole("button", {
    name: "Execute test-only fixture recovery",
  });
  await expect(execute).toBeDisabled();
  await confirmation.fill("wrong target");
  await page.getByLabel("Reason").fill("Verify typed confirmation is required");
  await expect(execute).toBeDisabled();
  await confirmation.fill("PURGE PHASE4 TEST FIXTURES phase4-browser-test");
  await expect(execute).toBeEnabled();
  await execute.click();
  await expect(
    page.getByText("COMPLETED: removed 2 fixture record(s)."),
  ).toBeVisible();
});

test("Phase 4 integrity evidence is explicit and remains usable at tablet width", async ({
  page,
}) => {
  await mockPhase4Api(page);
  await page.setViewportSize({ width: 768, height: 900 });
  await page.goto("/admin/integrity");
  await page
    .getByLabel("Development/test rehearsal secret")
    .fill("phase4-browser-secret");
  await page.getByRole("button", { name: "Start governed session" }).click();
  await page
    .getByRole("button", { name: "Run explicit integrity scan" })
    .click();
  await expect(page.getByText("Synthetic controlled finding.")).toBeVisible();
  await expect(
    page.getByRole("link", { name: "View Audit Event" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Download Audit CSV" }),
  ).toBeVisible();
});
