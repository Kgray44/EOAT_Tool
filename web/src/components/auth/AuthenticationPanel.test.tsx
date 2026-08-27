import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { apiClient } from "@/api/client";
import { AuthenticationPanel } from "./AuthenticationPanel";

function renderPanel() {
  return render(
    <MemoryRouter>
      <AuthenticationPanel />
    </MemoryRouter>,
  );
}

describe("AuthenticationPanel", () => {
  afterEach(() => vi.restoreAllMocks());

  it("offers a corporate sign-in form without retaining the submitted password", async () => {
    vi.spyOn(apiClient, "getAuthenticatedSession").mockRejectedValue(
      new Error("signed out"),
    );
    const login = vi.spyOn(apiClient, "kerberosFormLogin").mockResolvedValue({
      authenticated: true,
      identity: { display_name: "Corporate Administrator" },
      roles: ["ADMINISTRATOR"],
      permissions: ["*"],
      scope: "application",
    });
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Sign in" }));
    const password = screen.getByLabelText("Password");
    expect(password).toHaveAttribute("type", "password");
    await user.type(screen.getByLabelText("Username"), "corp.user");
    await user.type(password, "not-retained");
    await user.click(
      within(
        screen.getByRole("form", { name: "EOAT Atlas sign in" }),
      ).getByRole("button", { name: "Sign in" }),
    );

    await waitFor(() =>
      expect(login).toHaveBeenCalledWith("corp.user", "not-retained"),
    );
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(screen.getByText("Corporate Administrator")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Admin" })).toHaveAttribute(
      "href",
      "/admin",
    );
  });

  it("does not expose Administrator navigation to a non-admin corporate session", async () => {
    vi.spyOn(apiClient, "getAuthenticatedSession").mockResolvedValue({
      authenticated: true,
      identity: { display_name: "Corporate User" },
      roles: [],
      permissions: [],
      scope: "application",
    });
    renderPanel();

    expect(await screen.findByText("Corporate User")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Admin" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Sign out" }),
    ).toBeInTheDocument();
  });

  it("keeps the safe unavailable message when the provider cannot sign in", async () => {
    vi.spyOn(apiClient, "getAuthenticatedSession").mockRejectedValue(
      new Error("signed out"),
    );
    vi.spyOn(apiClient, "kerberosFormLogin").mockRejectedValue(
      new Error("provider unavailable"),
    );
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "Sign in" }));
    await user.type(screen.getByLabelText("Username"), "corp.user");
    await user.type(screen.getByLabelText("Password"), "not-retained");
    await user.click(
      within(
        screen.getByRole("form", { name: "EOAT Atlas sign in" }),
      ).getByRole("button", { name: "Sign in" }),
    );

    expect(
      await screen.findByText(
        "Sign-in is unavailable. Please try again shortly.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });
});
