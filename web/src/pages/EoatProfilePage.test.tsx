import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider } from "react-router-dom";
import { AppProviders } from "@/app/providers";
import { createTestRouter } from "@/app/router";

const profile = {
  business_identifier: "EOAT A+1",
  display_name: "Vacuum picker",
  description: "Validated picker",
  status: "ACTIVE",
  eoat_type: "VACUUM",
  connection_type: "QD",
  cleanroom_classification: null,
  number_of_parts_picked: 4,
  is_active: true,
  row_version: 1,
  current_location: "UNKNOWN_NOT_VERIFIED",
  current_location_detail: null,
  relationships: [],
  audit_evidence: [],
  revision: "R2",
  number_of_vacuum_cups: 4,
  number_of_grippers: 0,
  vacuum_present: true,
  sensors_present: null,
  part_present_sensor_present: null,
  vacuum_confirmation_sensor_present: null,
  quick_disconnect_present: true,
  cup_material: "Silicone",
  notes: null,
  part_status: "NOT_YET_VERIFIED",
};
const location = {
  state: "CONFLICTING",
  source: "OBSERVATION",
  machine_number: "M-42",
  storage_location: null,
  observed_at: "2026-07-20T12:00:00Z",
  observed_on: null,
  observation_precision: "TIMESTAMP",
  confidence: "HIGH",
  resolution_status: "REVIEW_REQUIRED",
  evidence: "Two current observations disagree",
  observation_uuid: null,
  conflict_group_uuid: "group-1",
};
const relationships = [
  {
    relationship_type: "machine",
    identifier: "M-42",
    display_name: "Press 42",
    status: "COMPATIBLE",
    reason: null,
  },
  {
    relationship_type: "tool",
    identifier: "TOOL-7",
    display_name: "Mold 7",
    status: "LINKED",
    reason: null,
  },
];
const history = {
  items: [],
  pagination: { page: 1, page_size: 12, total: 0, pages: 0 },
};
const photos = [
  {
    document_uuid: "photo-hero",
    title: "EOAT overview",
    caption: null,
    file_name: "overview.jpg",
    mime_type: "image/jpeg",
    content_delivery_state: "AVAILABLE",
    is_profile_photo: true,
  },
];

function renderProfile(path = "/eoats/EOAT%20A%2B1") {
  return render(
    <AppProviders>
      <RouterProvider router={createTestRouter([path])} />
    </AppProviders>,
  );
}
function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status });
}
function mockApi(overrides: Record<string, Response> = {}) {
  return vi.fn((input: RequestInfo | URL) => {
    const path = String(input);
    const response =
      (path === "/api/v1/auth/session"
        ? json({
            authenticated: false,
            identity: {},
            roles: [],
            permissions: [],
            scope: "application",
          })
        : overrides[path]) ??
      (path.endsWith("/current-location")
        ? json(location)
        : path.endsWith("/relationships")
          ? json(relationships)
          : path.endsWith("/web-documents")
            ? json([])
            : path.endsWith("/web-photos")
              ? json(photos)
              : path.includes("/history?")
                ? json(history)
                : json(profile));
    return Promise.resolve(response);
  });
}

describe("EOAT profile route", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("decodes an encoded QR-style route and loads the expected endpoint families", async () => {
    const fetcher = mockApi();
    vi.stubGlobal("fetch", fetcher);
    renderProfile();
    expect(
      await screen.findByRole("heading", { name: "EOAT A+1" }),
    ).toBeInTheDocument();
    expect((await screen.findAllByText(/Conflicting/)).length).toBeGreaterThan(
      0,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("link", { name: "Relationships" }));
    expect(await screen.findByRole("link", { name: /M-42/ })).toHaveAttribute(
      "href",
      "/machines/M-42?tab=relationships",
    );
    expect(
      await screen.findByRole("link", {
        name: "Open full-resolution photo for EOAT A+1",
      }),
    ).toHaveAttribute("href", "/api/v1/web-photos/photo-hero/content");
    await user.click(screen.getByRole("link", { name: "Docs & Photos" }));
    expect((await screen.findAllByAltText("EOAT overview")).length).toBe(2);
    await waitFor(() =>
      expect(fetcher.mock.calls.map(([path]) => path)).toEqual(
        expect.arrayContaining([
          "/api/v1/eoats/EOAT%20A%2B1",
          "/api/v1/eoats/EOAT%20A%2B1/current-location",
          "/api/v1/eoats/EOAT%20A%2B1/relationships",
          "/api/v1/eoats/EOAT%20A%2B1/web-documents",
          "/api/v1/eoats/EOAT%20A%2B1/web-photos",
          "/api/v1/eoats/EOAT%20A%2B1/history?page_size=12",
        ]),
      ),
    );
  });

  it("keeps loaded identity visible when a secondary endpoint fails", async () => {
    vi.stubGlobal(
      "fetch",
      mockApi({
        "/api/v1/eoats/EOAT%20A%2B1/relationships": json(
          { message: "offline" },
          503,
        ),
      }),
    );
    renderProfile();
    expect(
      await screen.findByRole("heading", { name: "EOAT A+1" }),
    ).toBeInTheDocument();
    await userEvent
      .setup()
      .click(screen.getByRole("link", { name: "Relationships" }));
    expect(await screen.findByText("API unavailable")).toBeInTheDocument();
  });

  it("renders a truthful not-found state and retries only with GET", async () => {
    vi.stubGlobal(
      "fetch",
      mockApi({
        "/api/v1/eoats/MISSING": json({ detail: { message: "missing" } }, 404),
      }),
    );
    renderProfile("/eoats/MISSING");
    expect(
      await screen.findByRole("heading", { name: "EOAT not found" }),
    ).toBeInTheDocument();
    let firstProfileRequest = true;
    const succeeding = mockApi();
    const fetcher = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      void _init;
      if (
        String(input) === "/api/v1/eoats/EOAT%20A%2B1" &&
        firstProfileRequest
      ) {
        firstProfileRequest = false;
        return Promise.resolve(json({ message: "offline" }, 503));
      }
      return succeeding(input);
    });
    vi.stubGlobal("fetch", fetcher);
    const user = userEvent.setup();
    renderProfile();
    await user.click(await screen.findByRole("button", { name: "Retry" }));
    expect(
      await screen.findByRole("heading", { name: "EOAT A+1" }),
    ).toBeInTheDocument();
    expect(fetcher.mock.calls.every(([, init]) => init?.method === "GET")).toBe(
      true,
    );
  });

  it("rejects slash-containing encoded identifiers", async () => {
    vi.stubGlobal("fetch", mockApi());
    renderProfile("/eoats/EOAT%2F1");
    expect(
      await screen.findByRole("heading", { name: "Invalid EOAT identifier" }),
    ).toBeInTheDocument();
  });
});
