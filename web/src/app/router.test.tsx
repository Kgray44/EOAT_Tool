import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider } from "react-router-dom";
import { afterEach, vi } from "vitest";
import { AppProviders } from "@/app/providers";
import { createTestRouter } from "@/app/router";

function renderAt(path: string) {
  return render(
    <AppProviders>
      <RouterProvider router={createTestRouter([path])} />
    </AppProviders>,
  );
}

describe("router", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("registers a machine deep route as a real profile route", () => {
    renderAt("/machines/test-machine");
    expect(screen.getByRole("status")).toHaveTextContent(
      "Loading machine profile",
    );
  });
  it("shows a not-found page for unknown routes", () => {
    renderAt("/not-a-route");
    expect(
      screen.getByRole("heading", { name: "Page not found" }),
    ).toBeInTheDocument();
  });
  it("keeps the governed Admin application outside the normal application shell", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        if (String(input).endsWith("/api/v1/auth/status")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                provider: null,
                status: "unavailable",
                mapping_configured: false,
              }),
            ),
          );
        }
        return Promise.resolve(new Response(JSON.stringify({ items: [] })));
      }),
    );
    renderAt("/admin/data");
    expect(
      await screen.findByRole("heading", {
        name: "Start development/test Administrator session",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Open navigation menu" }),
    ).not.toBeInTheDocument();
  });
  it("routes auxiliary pages to explicit browser-safe screens", () => {
    const setupPacket = renderAt("/setup-packet");
    expect(
      screen.getByRole("heading", { name: "Setup Packet" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Run Fit Check" })).toHaveAttribute(
      "href",
      "/fit-check",
    );
    setupPacket.unmount();
    const standards = renderAt("/standards");
    expect(
      screen.getByRole("heading", { name: "Standards & WI" }),
    ).toBeInTheDocument();
    standards.unmount();
    renderAt("/data-health");
    expect(
      screen.getByRole("heading", { name: "Data Health" }),
    ).toBeInTheDocument();
  });
  it("opens the keyboard-accessible desktop-style navigation overlay", async () => {
    const user = userEvent.setup();
    renderAt("/");
    const menu = screen.getByRole("button", { name: "Open navigation menu" });
    await user.click(menu);
    expect(
      screen.getByRole("dialog", { name: "Atlas navigation" }),
    ).toBeInTheDocument();
    expect(
      within(
        screen.getByRole("dialog", { name: "Atlas navigation" }),
      ).getByRole("button", { name: "Close navigation menu" }),
    ).toHaveFocus();
    const library = screen.getByRole("link", { name: "Library" });
    expect(library).toHaveAttribute("href", "/library");
    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("link", { name: "Library" }),
    ).not.toBeInTheDocument();
    expect(menu).toHaveFocus();
  });
  it("keeps keyboard focus inside the global search dialog", async () => {
    const user = userEvent.setup();
    renderAt("/");
    await user.click(screen.getByRole("button", { name: "Open search" }));
    const input = screen.getByRole("textbox", { name: "Search EOAT Atlas" });
    expect(input).toHaveFocus();
    await user.tab();
    expect(input).toHaveFocus();
  });
  it("keeps Home search local while Ctrl+K alone opens the global search", async () => {
    const user = userEvent.setup();
    renderAt("/");
    const homeSearch = screen.getByRole("textbox", {
      name: "Search the EOAT Atlas Library",
    });
    await user.click(homeSearch);
    await user.keyboard("m");
    expect(homeSearch).toHaveValue("m");
    expect(
      screen.queryByRole("dialog", { name: "Search EOAT Atlas" }),
    ).not.toBeInTheDocument();
    await user.keyboard("{Control>}k{/Control}");
    expect(
      screen.getByRole("dialog", { name: "Search EOAT Atlas" }),
    ).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("dialog", { name: "Search EOAT Atlas" }),
    ).not.toBeInTheDocument();
    expect(homeSearch).toHaveFocus();
    await user.keyboard("m");
    expect(homeSearch).toHaveValue("mm");
  });
  it("routes ordinary Home typing to the center search without reopening global search", async () => {
    const user = userEvent.setup();
    renderAt("/");
    const homeSearch = screen.getByRole("textbox", {
      name: "Search the EOAT Atlas Library",
    });
    await user.click(screen.getByRole("heading", { name: "Home" }));
    await user.keyboard("m");
    expect(homeSearch).toHaveFocus();
    expect(homeSearch).toHaveValue("m");
    expect(
      screen.queryByRole("dialog", { name: "Search EOAT Atlas" }),
    ).not.toBeInTheDocument();
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("heading", { name: "Home" }));
    expect(
      screen.queryByRole("dialog", { name: "Search EOAT Atlas" }),
    ).not.toBeInTheDocument();
  });
  it("does not open type-ahead search from an editable field", async () => {
    const user = userEvent.setup();
    renderAt("/fit-check");
    await user.click(screen.getByRole("combobox", { name: "Machine" }));
    await user.keyboard("m");
    expect(
      screen.queryByRole("dialog", { name: "Search EOAT Atlas" }),
    ).not.toBeInTheDocument();
  });
  it("treats entity routes as Library navigation", async () => {
    const user = userEvent.setup();
    renderAt("/machines/test-machine");
    await user.click(
      screen.getByRole("button", { name: "Open navigation menu" }),
    );
    expect(screen.getByRole("link", { name: "Library" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});
