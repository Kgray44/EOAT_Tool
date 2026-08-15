import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { apiClient, type AuthenticatedSession } from "@/api/client";
import {
  defaultBrowserSettings,
  readBrowserSettings,
  saveBrowserSettings,
  type BrowserSettings,
} from "@/app/browserSettings";

export function SettingsPage() {
  const [session, setSession] = useState<AuthenticatedSession | null>(null);
  const [settings, setSettings] = useState<BrowserSettings>(() =>
    readBrowserSettings(),
  );

  useEffect(() => {
    const refreshSession = () => {
      void apiClient
        .getAuthenticatedSession()
        .then(setSession)
        .catch(() => setSession(null));
    };
    refreshSession();
    window.addEventListener("atlas-authentication-changed", refreshSession);
    return () =>
      window.removeEventListener("atlas-authentication-changed", refreshSession);
  }, []);
  const update = <K extends keyof BrowserSettings>(
    key: K,
    value: BrowserSettings[K],
  ) => {
    const next = { ...settings, [key]: value };
    setSettings(next);
    saveBrowserSettings(next);
    window.dispatchEvent(new Event("atlas-settings-changed"));
  };
  const restoreBrowserDefaults = () => {
    setSettings(defaultBrowserSettings);
    saveBrowserSettings(defaultBrowserSettings);
    window.dispatchEvent(new Event("atlas-settings-changed"));
  };
  const exportBrowserSettings = () => {
    const blob = new Blob([JSON.stringify(settings, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "eoat-atlas-browser-settings.json";
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section className="settings-page" aria-labelledby="settings-title">
      <header className="settings-heading">
        <h1 id="settings-title">Settings</h1>
        <p>Personal display and accessibility preferences for this browser.</p>
      </header>
      <div className="settings-workspace">
        <div className="settings-content">
          <section className="profile-section settings-preferences">
            <h2>Theme</h2>
            <div className="attribute-grid">
              <label>
                Theme
                <select
                  value={settings.theme}
                  onChange={(event) =>
                    update(
                      "theme",
                      event.target.value as BrowserSettings["theme"],
                    )
                  }
                >
                  <option value="dark">Dark</option>
                  <option value="light">Light</option>
                  <option value="system">System</option>
                </select>
              </label>
              <label>
                Accent
                <select
                  value={settings.accent}
                  onChange={(event) =>
                    update(
                      "accent",
                      event.target.value as BrowserSettings["accent"],
                    )
                  }
                >
                  <option value="atlas_blue">Atlas Blue</option>
                  <option value="neutral_gray">Neutral Gray</option>
                  <option value="high_contrast_blue">High Contrast Blue</option>
                </select>
              </label>
              <label>
                Animation speed
                <select
                  value={settings.animationSpeed}
                  onChange={(event) =>
                    update(
                      "animationSpeed",
                      event.target.value as BrowserSettings["animationSpeed"],
                    )
                  }
                >
                  <option value="reduced">Reduced</option>
                  <option value="standard">Standard</option>
                  <option value="smooth">Smooth</option>
                </select>
              </label>
            </div>
          </section>
          <section className="profile-section settings-preferences">
            <h2>Accessibility</h2>
            <div className="attribute-grid">
              <label>
                <input
                  type="checkbox"
                  checked={settings.reduceMotion}
                  onChange={(event) => update("reduceMotion", event.target.checked)}
                />{" "}
                Reduce motion
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={settings.enhancedContrast}
                  onChange={(event) =>
                    update("enhancedContrast", event.target.checked)
                  }
                />{" "}
                Enhanced small-label contrast
              </label>
            </div>
          </section>
          <section className="profile-section settings-preferences">
            <h2>Governed configuration</h2>
            <p>
              Server configuration and operational changes are available only
              through the audited Administrator workflow.
            </p>
            {session?.roles?.includes("ADMINISTRATOR") ? (
              <Link className="simple-page-action" to="/admin/settings">
                Open Administrator Settings
              </Link>
            ) : null}
          </section>
        </div>
      </div>
      <footer className="settings-action-bar">
        <button type="button" onClick={restoreBrowserDefaults}>
          Restore browser defaults
        </button>
        <button type="button" onClick={exportBrowserSettings}>
          Export browser settings
        </button>
      </footer>
    </section>
  );
}
