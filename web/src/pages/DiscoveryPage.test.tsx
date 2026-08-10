import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider } from "react-router-dom";
import { AppProviders } from "@/app/providers";
import { createTestRouter } from "@/app/router";
import { rememberItem } from "@/api/recent";

const pagination = { page: 1, page_size: 24, total: 1, pages: 1 };
function renderAt(path: string) {
  return render(
    <AppProviders>
      <RouterProvider router={createTestRouter([path])} />
    </AppProviders>,
  );
}
function json(value: unknown) {
  return new Response(JSON.stringify(value), { status: 200 });
}
function mockFetch() {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    void init;
    const path = String(input);
    if (path.includes("/api/v1/catalog-options/"))
      return Promise.resolve(json([{ value: "P1", label: "Plant 1" }]));
    if (path.includes("/api/v1/setup-packets/data"))
      return Promise.resolve(
        json({
          machine: { machine_number: "M-1", machine_name: "Press 1" },
          tool: { business_identifier: "T-1", display_name: "Tool 1" },
          eoat: { business_identifier: "E-1", display_name: "EOAT 1" },
          fit_check: {
            overall_result: "COMPATIBLE",
            machine_tool_result: {
              pair: "machine_tool",
              result: "COMPATIBLE",
              reason: "Verified",
            },
            machine_eoat_result: {
              pair: "machine_eoat",
              result: "COMPATIBLE",
              reason: "Verified",
            },
            tool_eoat_result: {
              pair: "tool_eoat",
              result: "COMPATIBLE",
              reason: "Verified",
            },
            reasons: ["All relationships are verified."],
            warnings: [],
            unknown_relationships: [],
            alternative_compatible_eoats: [],
            stored: false,
          },
          generated_at: "2026-08-10T12:00:00Z",
          source: "mysql_api",
        }),
      );
    if (path.includes("/api/v1/web-fit-checks/options"))
      return Promise.resolve(
        json({
          machines: [{ identifier: "M-1", label: "Press 1", plant_code: "P1" }],
          tools: [{ identifier: "T-1", label: "Tool 1" }],
          eoats: [{ identifier: "E-1", label: "EOAT 1" }],
          warnings: [],
          unresolved_inputs: [],
        }),
      );
    if (path.includes("web-fit-checks"))
      return Promise.resolve(
        json({
          overall_result: "INVALID_INPUT",
          machine_tool_result: {
            pair: "machine_tool",
            result: "NOT_EVALUATED",
            reason: "Unknown",
          },
          machine_eoat_result: {
            pair: "machine_eoat",
            result: "NOT_EVALUATED",
            reason: "Unknown",
          },
          tool_eoat_result: {
            pair: "tool_eoat",
            result: "NOT_EVALUATED",
            reason: "Unknown",
          },
          reasons: ["Insufficient data"],
          warnings: [],
          unknown_relationships: ["machine"],
          alternative_compatible_eoats: [],
          stored: false,
        }),
      );
    if (path.includes("/api/v1/search"))
      return Promise.resolve(
        json([
          {
            category: "machine",
            identifier: "M-1",
            title: "Press 1",
            subtitle: "Area",
            matched_field: "fixture",
          },
        ]),
      );
    if (path.includes("/machines?"))
      return Promise.resolve(
        json({
          items: [
            {
              machine_number: "M-1",
              machine_name: "Press 1",
              area: "Area",
              plant_code: "P1",
              current_eoat: "UNKNOWN_NOT_VERIFIED",
              is_active: true,
              row_version: 1,
            },
          ],
          pagination,
        }),
      );
    if (path.includes("/tools?"))
      return Promise.resolve(json({ items: [], pagination }));
    return Promise.resolve(
      json({
        items: [
          {
            business_identifier: "E-1",
            display_name: "EOAT 1",
            current_location: "STORED",
            is_active: true,
            row_version: 1,
            photo_document_uuid: "hero-photo",
            photo_available_through_web: true,
          },
        ],
        pagination,
      }),
    );
  });
}

describe("Library and Fit Check", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });
  it("shows recents alongside the default server-paginated catalog", async () => {
    rememberItem({ category: "eoat", identifier: "E-1", label: "Recent EOAT" });
    const fetcher = mockFetch();
    vi.stubGlobal("fetch", fetcher);
    renderAt("/library");
    expect(
      await screen.findByText("Recently viewed on this browser"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Recent EOAT/ })).toHaveAttribute(
      "href",
      "/eoats/E-1",
    );
    expect(await screen.findByAltText("")).toHaveAttribute(
      "src",
      "/api/v1/web-photos/hero-photo/thumbnail",
    );
    await waitFor(() =>
      expect(fetcher.mock.calls.map(([path]) => path)).toEqual(
        expect.arrayContaining([
          "/api/v1/eoats?search=&page=1&page_size=24",
          "/api/v1/machines?search=&page=1&page_size=24",
          "/api/v1/tools?search=&page=1&page_size=24",
        ]),
      ),
    );
  });
  it("explains insufficient Fit Check data and uses the browser-safe POST", async () => {
    const fetcher = mockFetch();
    vi.stubGlobal("fetch", fetcher);
    renderAt("/fit-check");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Machine"), "M-1");
    await user.type(screen.getByLabelText("Tool"), "T-1");
    await user.type(screen.getByLabelText("EOAT"), "E-1");
    await user.click(
      screen.getByRole("button", { name: /Evaluate without saving/ }),
    );
    expect(
      await screen.findByRole("heading", { name: /Insufficient data/ }),
    ).toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(
        ([path, init]) =>
          path === "/api/v1/web-fit-checks/evaluate" && init?.method === "POST",
      ),
    ).toBe(true);
  });

  it("accepts every machine, tool, and EOAT selection order", async () => {
    const permutations = [
      ["Machine", "Tool", "EOAT"],
      ["Machine", "EOAT", "Tool"],
      ["Tool", "Machine", "EOAT"],
      ["Tool", "EOAT", "Machine"],
      ["EOAT", "Machine", "Tool"],
      ["EOAT", "Tool", "Machine"],
    ] as const;
    const valueFor = { Machine: "M-1", Tool: "T-1", EOAT: "E-1" } as const;

    for (const order of permutations) {
      const fetcher = mockFetch();
      vi.stubGlobal("fetch", fetcher);
      const view = renderAt("/fit-check");
      const user = userEvent.setup();
      for (const label of order) {
        await user.type(screen.getByLabelText(label), valueFor[label]);
      }
      const evaluate = screen.getByRole("button", {
        name: /Evaluate without saving/,
      });
      expect(evaluate).toBeEnabled();
      await user.click(evaluate);
      expect(
        await screen.findByRole("heading", { name: /Insufficient data/ }),
      ).toBeInTheDocument();
      expect(
        fetcher.mock.calls.some(
          ([path, init]) =>
            path === "/api/v1/web-fit-checks/evaluate" &&
            init?.method === "POST",
        ),
      ).toBe(true);
      view.unmount();
    }
  });

  it("allows each universal entity slot to take a different role", async () => {
    vi.stubGlobal("fetch", mockFetch());
    renderAt("/fit-check");
    const user = userEvent.setup();
    const first = screen.getByRole("group", { name: "Setup item 1" });
    const second = screen.getByRole("group", { name: "Setup item 2" });
    const third = screen.getByRole("group", { name: "Setup item 3" });

    await user.selectOptions(
      within(first).getByRole("combobox", { name: "Entity slot 1 type" }),
      "eoat",
    );
    await user.selectOptions(
      within(third).getByRole("combobox", { name: "Entity slot 3 type" }),
      "machine",
    );
    await user.type(
      within(first).getByRole("combobox", { name: "EOAT" }),
      "E-1",
    );
    await user.type(
      within(second).getByRole("combobox", { name: "Tool" }),
      "T-1",
    );
    await user.type(
      within(third).getByRole("combobox", { name: "Machine" }),
      "M-1",
    );

    expect(
      screen.getByRole("button", { name: /Evaluate without saving/ }),
    ).toBeEnabled();
  });

  it("renders a browser-safe setup packet that can be printed as a PDF", async () => {
    vi.stubGlobal("fetch", mockFetch());
    renderAt("/setup-packet?machine=M-1&tool=T-1&eoat=E-1&plant=P1");

    expect(
      await screen.findByRole("heading", { name: "Setup Packet" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("All relationships are verified."),
    ).toBeInTheDocument();
    expect(screen.getByText("Machine number")).toBeInTheDocument();
    expect(screen.queryByText(/\"machine_number\"/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Print or save as PDF" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Return to Fit Check" }),
    ).toHaveAttribute(
      "href",
      "/fit-check?machine=M-1&tool=T-1&eoat=E-1&plant=P1",
    );
  });

  it("uses server-side advanced Library filters rather than client-side filtering", async () => {
    const fetcher = mockFetch();
    vi.stubGlobal("fetch", fetcher);
    renderAt("/library?type=machine");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Advanced Filters" }));
    await user.type(screen.getByLabelText("Plant"), "P4");

    await waitFor(() =>
      expect(fetcher.mock.calls.map(([path]) => path)).toEqual(
        expect.arrayContaining([
          "/api/v1/machines?search=&page=1&page_size=24&plant=P4",
        ]),
      ),
    );
  });
});
