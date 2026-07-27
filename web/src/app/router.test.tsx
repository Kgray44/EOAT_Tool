import { render, screen } from "@testing-library/react";
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
  it("opens the keyboard-accessible desktop-style navigation overlay", async () => {
    const user = userEvent.setup();
    renderAt("/");
    const menu = screen.getByRole("button", { name: "Open navigation menu" });
    await user.click(menu);
    const library = screen.getByRole("link", { name: "Library" });
    expect(library).toHaveAttribute("href", "/library");
    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("link", { name: "Library" }),
    ).not.toBeInTheDocument();
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
});
