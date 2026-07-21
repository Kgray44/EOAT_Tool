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
  it("preserves deferred deep routes as honest phase placeholders", () => {
    renderAt("/machines/test-machine");
    expect(screen.getByText(/Machine profile is planned/i)).toBeInTheDocument();
    expect(screen.getByText("/machines/test-machine")).toBeInTheDocument();
  });
  it("shows a not-found page for unknown routes", () => {
    renderAt("/not-a-route");
    expect(
      screen.getByRole("heading", { name: "Page not found" }),
    ).toBeInTheDocument();
  });
  it("supports keyboard-accessible navigation", async () => {
    const user = userEvent.setup();
    renderAt("/search");
    await user.click(screen.getByRole("link", { name: "Status" }));
    expect(
      screen.getByRole("heading", { name: /secure foundation/i }),
    ).toBeInTheDocument();
  });
});
