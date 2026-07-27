import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { SettingsPage } from "./SettingsPage";

describe("SettingsPage", () => {
  afterEach(() => localStorage.clear());

  it("keeps desktop-only controls unavailable and persists browser display preferences", async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    expect(
      screen.getByRole("heading", {
        name: "Data Services and Engineering Files",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Read-only browser endpoint")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /^Display & Accessibility/ }),
    );
    await user.selectOptions(screen.getByLabelText("Theme"), "light");
    await user.click(screen.getByLabelText("Reduce motion"));

    expect(
      JSON.parse(
        localStorage.getItem("eoat-atlas-mirrorline-settings-v1") || "{}",
      ),
    ).toMatchObject({ theme: "light", reduceMotion: true });
  });
});
