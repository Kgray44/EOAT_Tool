import { useState } from "react";
import {
  defaultBrowserSettings,
  readBrowserSettings,
  saveBrowserSettings,
  type BrowserSettings,
} from "@/app/browserSettings";

type SettingsSectionKey =
  | "data_sources"
  | "refresh_cache"
  | "read_only_safety"
  | "search_navigation"
  | "fit_check"
  | "library"
  | "display_accessibility"
  | "setup_packet_pdf"
  | "validation_health"
  | "reference_documents"
  | "diagnostics_support"
  | "about";

type SettingsSection = {
  key: SettingsSectionKey;
  label: string;
  description: string;
  browserSummary: string;
};

const sections: SettingsSection[] = [
  {
    key: "data_sources",
    label: "Data Services and Engineering Files",
    description: "API, network documents, and controlled imports",
    browserSummary:
      "The browser reads only the published API and browser-safe document metadata. Source paths and local engineering files are not exposed.",
  },
  {
    key: "refresh_cache",
    label: "Server, Synchronization, and Cache",
    description: "Server refresh and disposable cache behavior",
    browserSummary:
      "Freshness is reported from the API. Browser cache and refresh policy stay under the service and browser security boundaries.",
  },
  {
    key: "read_only_safety",
    label: "Server Write Safety",
    description: "Transactions, authorization, conflicts, and offline behavior",
    browserSummary:
      "This browser remains read-only. It cannot enable writes, update operational records, or change server authorization.",
  },
  {
    key: "search_navigation",
    label: "Search & Navigation",
    description: "Search behavior and navigation",
    browserSummary:
      "Global search uses the authoritative read-only API with the desktop debounce, keyboard navigation, and browser-local recents.",
  },
  {
    key: "fit_check",
    label: "Fit Check",
    description: "Compatibility and flow behavior",
    browserSummary:
      "The browser evaluates the server-authoritative compatibility result without storing a Fit Check, assignment, audit, or history event.",
  },
  {
    key: "library",
    label: "Library",
    description: "Library display and defaults",
    browserSummary:
      "Library context, filters, sorting, and scroll restoration stay in the URL and browser session without changing catalog data.",
  },
  {
    key: "display_accessibility",
    label: "Display & Accessibility",
    description: "Theme, appearance, and readability",
    browserSummary:
      "These browser-local preferences are safe to change immediately and never alter desktop settings or shared data.",
  },
  {
    key: "setup_packet_pdf",
    label: "Setup Packet / PDF",
    description: "PDF defaults and output settings",
    browserSummary:
      "Packet generation is a desktop-local file workflow. The browser offers a read-only Fit Check instead of a simulated export.",
  },
  {
    key: "validation_health",
    label: "Validation & Data Health",
    description: "Data checks and validation rules",
    browserSummary:
      "The browser preserves API freshness and visible validation warnings but cannot run privileged local validation controls.",
  },
  {
    key: "reference_documents",
    label: "Reference Documents",
    description: "Guidelines and reference files",
    browserSummary:
      "Only documents explicitly delivered through browser-safe API routes can open here; local and network paths stay private.",
  },
  {
    key: "diagnostics_support",
    label: "Diagnostics & Support",
    description: "Logs, tools, and troubleshooting",
    browserSummary:
      "Browser diagnostics preserve safe status information. Administrator sessions, local logs, and diagnostic bundles remain desktop-only.",
  },
  {
    key: "about",
    label: "About",
    description: "App information and version",
    browserSummary:
      "EOAT Atlas browser information is read-only. Release activation and application administration are intentionally unavailable.",
  },
];

const dataRows = [
  ["EOAT Atlas API", "Read-only browser endpoint"],
  ["Source workbooks", "Not exposed to browser"],
  ["Engineering documents and photos", "Browser-safe profile media only"],
  ["Legacy Excel source", "Desktop-local controlled import"],
] as const;

export function SettingsPage() {
  const [section, setSection] = useState<SettingsSectionKey>("data_sources");
  const [settings, setSettings] = useState<BrowserSettings>(() =>
    readBrowserSettings(),
  );
  const activeSection = sections.find((item) => item.key === section)!;
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
          {sections.map((item) => (
            <button
              key={item.key}
              type="button"
              className={section === item.key ? "is-active" : ""}
              aria-current={section === item.key ? "page" : undefined}
              onClick={() => setSection(item.key)}
            >
              <strong>{item.label}</strong>
              <span>{item.description}</span>
            </button>
          ))}
        </aside>
        <div className="settings-content">
          <header className="settings-panel-heading">
            <div>
              <h2>{activeSection.label}</h2>
              <p>{activeSection.description}</p>
            </div>
            <span>Administrator access required to edit</span>
          </header>
          {section === "display_accessibility" ? (
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
          ) : (
            <section className="settings-desktop-boundary">
              <h2>Browser-safe status</h2>
              <p>{activeSection.browserSummary}</p>
              {section === "data_sources" && (
                <dl className="settings-status-list">
                  {dataRows.map(([label, value]) => (
                    <div key={label}>
                      <dt>{label}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>
              )}
              <p className="notes">
                This browser never changes data sources, operational records,
                local files, server settings, or administrator access.
              </p>
            </section>
          )}
        </div>
      </div>
    </section>
  );
}
