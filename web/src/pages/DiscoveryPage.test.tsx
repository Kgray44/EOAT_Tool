import { render, screen } from "@testing-library/react";
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
    return Promise.resolve(json({ items: [], pagination }));
  });
}

describe("Library and Fit Check", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });
  it("shows local-only recent items before a search", async () => {
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
    expect(fetcher).not.toHaveBeenCalled();
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
});
