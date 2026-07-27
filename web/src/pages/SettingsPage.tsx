import { useState } from "react";
import {
  defaultBrowserSettings,
  readBrowserSettings,
  saveBrowserSettings,
  type BrowserSettings,
} from "@/app/browserSettings";

export function SettingsPage() {
  const [section, setSection] = useState<"data" | "display">("data");
  const [settings, setSettings] = useState<BrowserSettings>(() =>
    readBrowserSettings(),
  );
  const update = <K extends keyof BrowserSettings>(
    key: K,
    value: BrowserSettings[K],
  ) => {
    const next = { ...settings, [key]: value };
    setSettings(next);
    saveBrowserSettings(next);
    window.dispatchEvent(new Event("atlas-settings-changed"));
  };
  return (
    <section className="settings-page" aria-labelledby="settings-title">
      <header className="settings-heading">
        <h1 id="settings-title">Settings</h1>
        <p>
          Configure browser preferences. Operational controls stay in EOAT Atlas
          Desktop.
        </p>
      </header>
      <div className="settings-workspace">
        <aside className="settings-nav" aria-label="Settings sections">
          <h2>Settings Sections</h2>
          {[
            ["data", "Data Services and Engineering Files"],
            ["unavailable", "Server, Synchronization, and Cache"],
            ["unavailable", "Server Write Safety"],
            ["unavailable", "Search & Navigation"],
            ["unavailable", "Fit Check"],
            ["unavailable", "Library"],
            ["display", "Display & Accessibility"],
            ["unavailable", "Setup Packet / PDF"],
            ["unavailable", "Validation & Data Health"],
            ["unavailable", "Reference Documents"],
            ["unavailable", "Diagnostics & Support"],
            ["unavailable", "About"],
          ].map(([key, label]) => (
            <button
              key={label}
              type="button"
              className={section === key ? "is-active" : ""}
              aria-current={section === key ? "page" : undefined}
              disabled={key === "unavailable"}
              onClick={() => setSection(key === "display" ? "display" : "data")}
            >
              {label}
            </button>
          ))}
        </aside>
        <div className="settings-content">
          {section === "data" ? (
            <section className="settings-desktop-boundary">
              <h2>Data Services and Engineering Files</h2>
              <p>
                Administrator access is required to edit desktop data sources.
                Browser access is read-only.
              </p>
              <p className="notes">
                This web UI cannot safely change data sources, write operational
                records, manage local files, generate setup packets, or perform
                authenticated administrator actions. Those desktop-only controls
                are intentionally unavailable rather than simulated.
              </p>
            </section>
          ) : (
            <>
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
                      <option value="high_contrast_blue">
                        High Contrast Blue
                      </option>
                    </select>
                  </label>
                  <label>
                    Animation speed
                    <select
                      value={settings.animationSpeed}
                      onChange={(event) =>
                        update(
                          "animationSpeed",
                          event.target
                            .value as BrowserSettings["animationSpeed"],
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
                      onChange={(event) =>
                        update("reduceMotion", event.target.checked)
                      }
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
                <h2>Browser preferences</h2>
                <p className="notes">
                  These controls apply only to this browser. Desktop operational
                  controls remain unavailable here.
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setSettings(defaultBrowserSettings);
                    saveBrowserSettings(defaultBrowserSettings);
                    window.dispatchEvent(new Event("atlas-settings-changed"));
                  }}
                >
                  Restore browser defaults
                </button>
              </section>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
