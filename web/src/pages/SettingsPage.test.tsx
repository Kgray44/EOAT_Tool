import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppProviders } from "@/app/providers";
import { SettingsPage } from "./SettingsPage";

describe("SettingsPage", () => {
  afterEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.unstubAllGlobals();
  });

  it("keeps server controls locked until a real administrator session saves them", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = input.toString();
      if (path === "/api/v1/settings/catalog") {
        return new Response(JSON.stringify({
          sections: [],
          items: [
            { section: "data_sources", key: "paths.eoat_master_tracker", label: "EOAT Master Tracker", control: "path", default: "", options: [], locked: false },
            { section: "refresh_cache", key: "data_loading.refresh_on_launch", label: "Refresh on app launch", control: "checkbox", default: true, options: [], locked: false },
          ],
        }), { status: 200 });
      }
      if (path === "/api/v1/settings") {
        return new Response(JSON.stringify({ items: [] }), { status: 200 });
      }
      if (path === "/api/v1/auth/config") {
        return new Response(JSON.stringify({
          provider: "development",
          settings_authentication_available: true,
          provider_configured: true,
          development_identities: ["dev.admin"],
          message: "Development Settings authentication is available.",
        }), { status: 200 });
      }
      if (path === "/api/v1/auth/development/login") {
        expect(init?.method).toBe("POST");
        return new Response(JSON.stringify({
          access_token: "test-settings-token",
          authenticated: true,
          identity: { display_name: "Development Administrator" },
          permissions: ["settings.edit", "settings.restore", "settings.set_default"],
        }), { status: 200 });
      }
      if (path === "/api/v1/auth/session") {
        return new Response(JSON.stringify({
          authenticated: true,
          identity: { display_name: "Development Administrator" },
          permissions: ["settings.edit", "settings.restore", "settings.set_default"],
        }), { status: 200 });
      }
      if (path === "/api/v1/settings/data_loading.refresh_on_launch") {
        expect(init?.headers).toMatchObject({ Authorization: "Bearer test-settings-token" });
        expect(init?.body).toBe(JSON.stringify({ value: false, description: undefined }));
        return new Response(JSON.stringify({
          key: "data_loading.refresh_on_launch",
          value: false,
          value_type: "boolean",
          description: null,
          row_version: 1,
        }), { status: 200 });
      }
      if (path === "/api/v1/settings/actions/factory-reset") {
        expect(init?.body).toBe(JSON.stringify({ confirmation: "FACTORY RESET", section: undefined }));
        return new Response(JSON.stringify({ action: "factory-reset", updated: 1 }), { status: 200 });
      }
      return new Response(JSON.stringify({ message: `Unexpected request: ${path}` }), { status: 500 });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <AppProviders>
        <SettingsPage />
      </AppProviders>,
    );

    expect(
      screen.getByRole("heading", {
        name: "Data Services and Engineering Files",
      }),
    ).toBeInTheDocument();
    expect(await screen.findByText("EOAT Master Tracker")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^Server, Synchronization/ }));
    expect(await screen.findByLabelText("Refresh on app launch")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Admin Login" }));
    await screen.findByText("Administrator: Development Administrator");
    await vi.waitFor(() => {
      expect(screen.getByLabelText("Refresh on app launch")).toBeEnabled();
    });
    const refreshOnLaunch = screen.getByLabelText("Refresh on app launch");
    await user.click(refreshOnLaunch);
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/v1/settings/data_loading.refresh_on_launch",
      expect.objectContaining({ method: "PUT" }),
    );
    await user.click(screen.getByRole("button", { name: "Save Settings" }));
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/settings/data_loading.refresh_on_launch",
        expect.objectContaining({ method: "PUT" }),
      );
    });

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
    expect(
      screen.getByRole("button", { name: "Export browser settings" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^Diagnostics & Support/ }));
    await user.click(screen.getByRole("button", { name: "Factory Reset" }));
    await user.type(screen.getByLabelText("Confirmation"), "FACTORY RESET");
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/settings/actions/factory-reset",
        expect.objectContaining({ method: "POST" }),
      );
    });
  });
});
