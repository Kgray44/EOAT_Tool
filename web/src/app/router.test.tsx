import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider } from "react-router-dom";
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
  it("accounts for desktop-only auxiliary pages with explicit browser-safe routes", () => {
    const setupPacket = renderAt("/setup-packet");
    expect(
      screen.getByRole("heading", { name: "Setup Packet" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Run a read-only Fit Check" }),
    ).toHaveAttribute("href", "/fit-check");
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
  it("opens global search for Ctrl+K and ordinary type-ahead", async () => {
    const user = userEvent.setup();
    renderAt("/");
    await user.keyboard("{Control>}k{/Control}");
    expect(
      screen.getByRole("dialog", { name: "Search EOAT Atlas" }),
    ).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await user.keyboard("m");
    expect(
      screen.getByRole("textbox", { name: "Search EOAT Atlas" }),
    ).toHaveValue("m");
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
