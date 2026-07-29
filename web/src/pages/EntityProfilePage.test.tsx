import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider } from "react-router-dom";
import { AppProviders } from "@/app/providers";
import { createTestRouter } from "@/app/router";

const machine = {
  plant_code: "P1",
  machine_number: "M-1",
  machine_name: "Press 1",
  area: null,
  manufacturer: null,
  model: null,
  cleanroom_classification: null,
  status: "ACTIVE",
  current_eoat: "UNKNOWN_NOT_VERIFIED",
  is_active: true,
  row_version: 1,
  controller_type: null,
  press_capacity_tons: null,
  notes: null,
  relationships: [],
  robots: [],
  audit_evidence: [],
};
const tool = {
  business_identifier: "T-1",
  tool_number: "T-1",
  mold_number: null,
  display_name: "Mold 1",
  status: "ACTIVE",
  part_status: "NOT_YET_VERIFIED",
  is_active: true,
  row_version: 1,
  description: null,
  tool_type: null,
  customer: null,
  program_name: null,
  notes: null,
  relationships: [],
  audit_evidence: [],
};
const setup = {
  machine_number: "M-1",
  current_eoat: "UNKNOWN_NOT_VERIFIED",
  current_tool: "UNKNOWN_NOT_VERIFIED",
  verified: false,
  location_semantics: "Fixture",
};

function renderAt(path: string) {
  return render(
    <AppProviders>
      <RouterProvider router={createTestRouter([path])} />
    </AppProviders>,
  );
}
function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status });
}
function fetchFor(overrides: Record<string, Response> = {}) {
  return vi.fn((input: RequestInfo | URL) => {
    const path = String(input);
    if (overrides[path]) return Promise.resolve(overrides[path]);
    if (path.endsWith("/current-setup")) return Promise.resolve(json(setup));
    if (
      path.endsWith("/web-documents") ||
      path.endsWith("/web-photos") ||
      path.endsWith("/relationships") ||
      path.endsWith("/history")
    )
      return Promise.resolve(json([]));
    return Promise.resolve(json(path.includes("/machines/") ? machine : tool));
  });
}

describe("machine and tool profile routes", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("loads a machine and preserves identity after a secondary failure with retry", async () => {
    const failingPath = "/api/v1/machines/M-1/web-photos";
    const fetcher = fetchFor({
      [failingPath]: json({ message: "offline" }, 503),
    });
    vi.stubGlobal("fetch", fetcher);
    renderAt("/machines/M-1");
    expect(
      await screen.findByRole("heading", { name: "M-1" }),
    ).toBeInTheDocument();
    await userEvent
      .setup()
      .click(screen.getByRole("link", { name: "Docs & Photos" }));
    expect(await screen.findByText("Photos unavailable")).toBeInTheDocument();
    await userEvent
      .setup()
      .click(screen.getAllByRole("button", { name: "Retry" })[0]);
    await waitFor(() =>
      expect(
        fetcher.mock.calls.filter(([path]) => path === failingPath).length,
      ).toBeGreaterThan(1),
    );
  });
  it("renders truthful machine values, human-readable setup states, and empty media states", async () => {
    vi.stubGlobal("fetch", fetchFor());
    renderAt("/machines/M-1");
    expect((await screen.findAllByText("Not verified")).length).toBeGreaterThan(
      0,
    );
    expect(
      screen.queryByText("Unknown / not verified"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText(/Not recorded:/)).toBeInTheDocument();
    await userEvent
      .setup()
      .click(screen.getByRole("link", { name: "Docs & Photos" }));
    expect(await screen.findByText("No photos recorded")).toBeInTheDocument();
    expect(
      await screen.findByText("No documents recorded"),
    ).toBeInTheDocument();
  });
  it("shows a truthful tool not-found state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(json({ detail: { message: "missing" } }, 404)),
    );
    renderAt("/tools/MISSING");
    expect(
      await screen.findByRole("heading", { name: "Tool not found" }),
    ).toBeInTheDocument();
  });
  it("loads a tool profile and keeps the Fit Check shortcut registered", async () => {
    vi.stubGlobal("fetch", fetchFor());
    renderAt("/tools/T-1");
    expect(
      await screen.findByRole("heading", { name: "T-1" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Run a read-only Fit Check" }),
    ).toHaveAttribute("href", "/fit-check?tool=T-1");
  });
});
