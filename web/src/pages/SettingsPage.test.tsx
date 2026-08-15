import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { SettingsPage } from "./SettingsPage";
import { apiClient } from "@/api/client";

describe("SettingsPage", () => {
  afterEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("keeps personal preferences local and hides governed navigation while signed out", async () => {
    vi.spyOn(apiClient, "getAuthenticatedSession").mockRejectedValue(
      new Error("signed out"),
    );
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>,
    );

    await user.selectOptions(screen.getByLabelText("Theme"), "light");
    expect(screen.getByLabelText("Theme")).toHaveValue("light");
    await waitFor(() =>
      expect(
        screen.queryByRole("link", { name: "Open Administrator Settings" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("shows governed navigation only for an Administrator session", async () => {
    vi.spyOn(apiClient, "getAuthenticatedSession").mockResolvedValue({
      authenticated: true,
      roles: ["ADMINISTRATOR"],
      permissions: [],
      scope: "application",
    });
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>,
    );

    expect(
      await screen.findByRole("link", { name: "Open Administrator Settings" }),
    ).toHaveAttribute("href", "/admin/settings");
  });
});
