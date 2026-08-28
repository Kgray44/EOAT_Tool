import { expect, test, type Page } from "@playwright/test";

async function openAdminShell(page: Page) {
  await page.route("**/api/v1/auth/session", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        authenticated: true,
        identity: { display_name: "Theme Test Administrator" },
        roles: ["ADMINISTRATOR"],
        permissions: ["*"],
        scope: "application",
      }),
    }),
  );
  await page.route("**/api/v1/admin/**", (route) => {
    const url = new URL(route.request().url());
    const body = url.pathname.endsWith("/overview")
      ? {
          api_version: "1.4.0",
          schema_revision: "20260827_0016",
          audit_schema_version: 1,
          observation_time_utc: "2026-08-28T20:00:00Z",
          writes_enabled: true,
          environment: "production-fixture",
          api_status: "healthy",
          database_status: "healthy",
          audit_status: "healthy",
          metrics: {
            events_today: 0,
            events_last_24_hours: 0,
            successful_events_last_24_hours: 0,
            failed_events_last_24_hours: 0,
            denied_events_last_24_hours: 0,
            security_events_last_24_hours: 0,
            administrative_events_last_24_hours: 0,
            unique_actors_last_24_hours: 0,
          },
          recent_events: [],
        }
      : url.pathname.endsWith("/system")
        ? {
            observation_time_utc: "2026-08-28T20:00:00Z",
            checks: [],
          }
        : { items: [], page: 1, page_size: 50, total: 0 };
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
  await page.route("**/api/v1/data-status", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        server_time: "2026-08-28T20:00:00Z",
        data_last_modified_at: "2026-08-28T20:00:00Z",
      }),
    }),
  );
  await page.goto("/admin/audit");
}

function luminance(color: string) {
  const channels = color
    .match(/\d+(?:\.\d+)?/g)
    ?.slice(0, 3)
    .map(Number);
  if (!channels || channels.length !== 3)
    throw new Error(`Expected RGB color, got ${color}`);
  const normalized = channels.map((channel) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return (
    0.2126 * normalized[0] + 0.7152 * normalized[1] + 0.0722 * normalized[2]
  );
}

function contrast(foreground: string, background: string) {
  const [lighter, darker] = [luminance(foreground), luminance(background)].sort(
    (left, right) => right - left,
  );
  return (lighter + 0.05) / (darker + 0.05);
}

async function sharedSurfaceColors(page: Page, theme: "dark" | "light") {
  return page.evaluate((selectedTheme) => {
    document.documentElement.dataset.atlasTheme = selectedTheme;
    const fixture = document.createElement("section");
    fixture.setAttribute("data-testid", "admin-theme-fixture");
    fixture.innerHTML = `
      <div class="audit-table-wrap"><table><thead><tr><th>Header</th></tr></thead><tbody><tr><td><a href="#theme">Ordinary row link</a></td></tr><tr><td>Alternate row</td></tr></tbody></table></div>
      <section class="record-list"><button type="button">Group Access row</button></section>
      <section class="editor-card health-check"><div class="state-note">System Health diagnostic panel</div></section>
      <section class="editor-card"><div class="integrity-summary">Integrity status and help panel</div></section>
      <section class="preview-panel">Nested evidence and <small>secondary metadata</small> info panel</section>
      <section class="state-panel"><h1>Shared error state</h1></section>
      <ol class="workflow-steps"><li>Inactive step</li><li class="active">Active step</li></ol>
      <button class="secondary-button" disabled>Disabled confirmation control</button>
      <span class="result result-success">Success status</span>
    `;
    document.querySelector("#admin-content")?.append(fixture);
    const color = (selector: string, property = "backgroundColor") => {
      const element = fixture.querySelector(selector);
      if (!element) throw new Error(`Missing ${selector}`);
      const styles = getComputedStyle(element);
      return property === "color" ? styles.color : styles.backgroundColor;
    };
    return {
      header: color("thead"),
      ordinaryRow: color("tbody tr"),
      alternateRow: color("tbody tr:nth-child(even)"),
      groupAccessRow: color(".record-list button"),
      healthDiagnostic: color(".health-check .state-note"),
      integrityPanel: color(".integrity-summary"),
      evidencePanel: color(".preview-panel"),
      inactiveWorkflow: color(".workflow-steps li"),
      disabledControl: color("button:disabled"),
      headerText: color("th", "color"),
      tableText: color("tbody td", "color"),
      tableLink: color("tbody a", "color"),
      secondaryText: color(".preview-panel small", "color"),
      disabledText: color("button:disabled", "color"),
      successText: color(".result-success", "color"),
      successSurface: color(".result-success"),
      stateHeading: color(".state-panel h1", "color"),
      statePanel: color(".state-panel"),
    };
  }, theme);
}

test("shared Admin dark surfaces keep tables, diagnostics, and workflow controls dark", async ({
  page,
}) => {
  await openAdminShell(page);
  const colors = await sharedSurfaceColors(page, "dark");
  await page.screenshot({
    path: "test-results/admin-theme-sweep/dark-shared-primitives.png",
    fullPage: true,
  });

  for (const surface of [
    "header",
    "ordinaryRow",
    "alternateRow",
    "groupAccessRow",
    "healthDiagnostic",
    "integrityPanel",
    "evidencePanel",
    "inactiveWorkflow",
    "disabledControl",
    "successSurface",
  ] as const) {
    const color = colors[surface];
    expect(luminance(color), `${surface}: ${color}`).toBeLessThan(0.13);
  }
  expect(colors.header).not.toBe("rgb(255, 255, 255)");
  expect(colors.ordinaryRow).not.toBe(colors.alternateRow);
  expect(contrast(colors.headerText, colors.header)).toBeGreaterThanOrEqual(
    4.5,
  );
  expect(contrast(colors.tableText, colors.ordinaryRow)).toBeGreaterThanOrEqual(
    4.5,
  );
  expect(contrast(colors.tableLink, colors.ordinaryRow)).toBeGreaterThanOrEqual(
    4.5,
  );
  expect(
    contrast(colors.secondaryText, colors.evidencePanel),
  ).toBeGreaterThanOrEqual(4.5);
  expect(
    contrast(colors.disabledText, colors.disabledControl),
  ).toBeGreaterThanOrEqual(4.5);
  expect(
    contrast(colors.successText, colors.successSurface),
  ).toBeGreaterThanOrEqual(4.5);
  expect(
    contrast(colors.stateHeading, colors.statePanel),
  ).toBeGreaterThanOrEqual(4.5);
});

test("shared Admin light surfaces retain their light hierarchy", async ({
  page,
}) => {
  await openAdminShell(page);
  const colors = await sharedSurfaceColors(page, "light");
  await page.screenshot({
    path: "test-results/admin-theme-sweep/light-shared-primitives.png",
    fullPage: true,
  });

  expect(luminance(colors.groupAccessRow)).toBeGreaterThan(0.8);
  expect(luminance(colors.healthDiagnostic)).toBeGreaterThan(0.8);
  expect(luminance(colors.evidencePanel)).toBeGreaterThan(0.8);
  expect(luminance(colors.inactiveWorkflow)).toBeGreaterThan(0.75);
  expect(luminance(colors.disabledControl)).toBeGreaterThan(0.75);
});

test("captures the complete Admin route sweep in dark mode", async ({
  page,
}) => {
  await openAdminShell(page);
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.evaluate(() => {
    document.documentElement.dataset.atlasTheme = "dark";
  });

  const routes = [
    ["admin", "/admin"],
    ["audit", "/admin/audit"],
    ["relationships", "/admin/data/relationships"],
    ["documents", "/admin/data/documents"],
    ["photos", "/admin/data/photos"],
    ["bulk", "/admin/data/bulk"],
    ["settings", "/admin/settings"],
    ["users", "/admin/users"],
    ["group-policies", "/admin/group-policies"],
    ["system", "/admin/system"],
    ["integrity", "/admin/integrity"],
  ] as const;

  for (const [name, route] of routes) {
    await page.goto(route);
    await expect(page.locator(".admin-layout")).toBeVisible();
    await page.screenshot({
      path: `test-results/admin-theme-sweep/dark-${name}.png`,
      fullPage: true,
    });
  }
});
