import { useState } from "react";
import {
  defaultBrowserSettings,
  readBrowserSettings,
  saveBrowserSettings,
  type BrowserSettings,
} from "@/app/browserSettings";

export function SettingsPage() {
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
    <section className="profile-page" aria-labelledby="settings-title">
      <header className="profile-header">
        <p className="eyebrow">Browser preferences</p>
        <h1 id="settings-title">Settings</h1>
        <p className="profile-name">
          These preferences are stored only in this browser. Privileged,
          filesystem, data-source, and write controls remain available only in
          EOAT Atlas Desktop.
        </p>
      </header>
      <div className="profile-sections">
        <section className="profile-section">
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
        <section className="profile-section">
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
        <section className="profile-section">
          <h2>Browser boundary</h2>
          <p className="notes">
            This web UI cannot safely change data sources, write operational
            records, manage local files, generate setup packets, or perform
            authenticated administrator actions. Those desktop-only controls are
            intentionally unavailable rather than simulated.
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
      </div>
    </section>
  );
}
