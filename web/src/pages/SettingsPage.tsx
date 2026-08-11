import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  apiClient,
  type AuthenticatedSession,
  type SettingsAction,
} from "@/api/client";
import { ErrorState, LoadingState } from "@/components/feedback/StateViews";
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
};

const sections: SettingsSection[] = [
  {
    key: "data_sources",
    label: "Data Services and Engineering Files",
  },
  {
    key: "refresh_cache",
    label: "Server, Synchronization, and Cache",
  },
  {
    key: "read_only_safety",
    label: "Server Write Safety",
  },
  {
    key: "search_navigation",
    label: "Search & Navigation",
  },
  {
    key: "fit_check",
    label: "Fit Check",
  },
  {
    key: "library",
    label: "Library",
  },
  {
    key: "display_accessibility",
    label: "Display & Accessibility",
  },
  {
    key: "setup_packet_pdf",
    label: "Setup Packet / PDF",
  },
  {
    key: "validation_health",
    label: "Validation & Data Health",
  },
  {
    key: "reference_documents",
    label: "Reference Documents",
  },
  {
    key: "diagnostics_support",
    label: "Diagnostics & Support",
  },
  {
    key: "about",
    label: "About",
  },
];

function canonicalValue(value: unknown): string {
  if (value === true) return "Enabled";
  if (value === false) return "Disabled";
  return value === "" || value === null || value === undefined
    ? "Not recorded"
    : String(value);
}

function CanonicalSettingsControl({
  item,
  value,
  editable,
  onChange,
}: {
  item: {
    key: string;
    label: string;
    control: string;
    default: unknown;
    description?: string;
    options?: { value?: unknown; label?: string }[];
    locked?: boolean;
  };
  value: unknown;
  editable: boolean;
  onChange: (value: unknown) => void;
}) {
  const statusOnly =
    item.locked ||
    ["locked", "locked_text", "status", "path"].includes(item.control);
  return (
    <div className="settings-control-row">
      <div>
        <strong>{item.label}</strong>
        {item.description ? <p>{item.description}</p> : null}
      </div>
      {statusOnly ? (
        <output>
          {item.control === "path" ? "Server-managed" : canonicalValue(value)}
        </output>
      ) : item.control === "checkbox" ? (
        <label className="settings-locked-control">
          <input
            aria-label={item.label}
            type="checkbox"
            checked={value === true}
            disabled={!editable}
            onChange={(event) => onChange(event.target.checked)}
          />
          <span>{value === true ? "Enabled" : "Disabled"}</span>
        </label>
      ) : item.control === "text" ? (
        <input
          value={value == null ? "" : String(value)}
          readOnly={!editable}
          aria-label={item.label}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <select
          value={String(value ?? item.default)}
          disabled={!editable}
          aria-label={item.label}
          onChange={(event) =>
            onChange(
              (item.options ?? []).find(
                (option) => String(option.value) === event.target.value,
              )?.value ?? event.target.value,
            )
          }
        >
          {(item.options ?? []).map((option) => (
            <option key={String(option.value)} value={String(option.value)}>
              {option.label ?? String(option.value)}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}

export function SettingsPage() {
  const [section, setSection] = useState<SettingsSectionKey>("data_sources");
  const [settings, setSettings] = useState<BrowserSettings>(() =>
    readBrowserSettings(),
  );
  const [session, setSession] = useState<AuthenticatedSession | null>(null);
  const [authError, setAuthError] = useState<unknown>(null);
  const [draftShared, setDraftShared] = useState<Record<string, unknown>>({});
  const [pendingAction, setPendingAction] = useState<SettingsAction | null>(
    null,
  );
  const [confirmation, setConfirmation] = useState("");
  const catalog = useQuery({
    queryKey: ["settings", "catalog"],
    queryFn: () => apiClient.getSettingsCatalog(),
  });
  const shared = useQuery({
    queryKey: ["settings", "shared"],
    queryFn: () => apiClient.getSharedSettings(),
  });
  useEffect(() => {
    const refresh = () =>
      void apiClient
        .getAuthenticatedSession()
        .then(setSession)
        .catch(() => setSession(null));
    refresh();
    window.addEventListener("atlas-authentication-changed", refresh);
    return () =>
      window.removeEventListener("atlas-authentication-changed", refresh);
  }, []);
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
  const editableSharedSettings = Boolean(
    session?.permissions?.includes("settings.edit"),
  );
  const canResetSettings = Boolean(
    session?.permissions?.includes("settings.restore"),
  );
  const canSetDefaults = Boolean(
    session?.permissions?.includes("settings.set_default"),
  );
  const valueFor = (item: { key: string; default: unknown }) =>
    draftShared[item.key] ??
    shared.data?.find((setting) => setting.key === item.key)?.value ??
    item.default;
  const queueShared = (item: { key: string }, value: unknown) => {
    if (!editableSharedSettings) return;
    setDraftShared((current) => ({ ...current, [item.key]: value }));
  };
  const saveShared = () => {
    if (!editableSharedSettings || !Object.keys(draftShared).length) return;
    setAuthError(null);
    void Promise.all(
      Object.entries(draftShared).map(([key, value]) =>
        apiClient.updateSharedSetting(
          key,
          value,
          catalog.data?.items.find((item) => item.key === key)?.description,
        ),
      ),
    )
      .then(() => {
        setDraftShared({});
        return shared.refetch();
      })
      .catch(setAuthError);
  };
  const discardShared = () => {
    setDraftShared({});
    void shared.refetch();
  };
  const actionConfirmation: Record<SettingsAction, string> = {
    "reset-section": "RESET SECTION",
    "reset-all": "RESET ALL SETTINGS",
    "set-defaults": "SET DEFAULTS",
    "factory-reset": "FACTORY RESET",
  };
  const executeSettingsAction = () => {
    if (
      !pendingAction ||
      confirmation !== actionConfirmation[pendingAction] ||
      !session
    )
      return;
    setAuthError(null);
    void apiClient
      .applySettingsAction(
        pendingAction,
        confirmation,
        pendingAction === "reset-section" ? section : undefined,
      )
      .then(() => {
        setPendingAction(null);
        setConfirmation("");
        setDraftShared({});
        return shared.refetch();
      })
      .catch(setAuthError);
  };
  const signOut = () => {
    setAuthError(null);
    void apiClient
      .logout()
      .then(() => {
        setSession(null);
        window.dispatchEvent(new Event("atlas-authentication-changed"));
      })
      .catch(setAuthError);
  };
  return (
    <section className="settings-page" aria-labelledby="settings-title">
      <header className="settings-heading">
        <h1 id="settings-title">Settings</h1>
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
            </button>
          ))}
        </aside>
        <div className="settings-content">
          <header className="settings-panel-heading">
            <div>
              <h2>{activeSection.label}</h2>
            </div>
            <span>
              {section === "display_accessibility"
                ? "Browser preferences"
                : editableSharedSettings
                  ? "Administrator session"
                  : "Administrator lock"}
            </span>
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
                  These controls apply only to this browser. Shared settings
                  retain their server-side authorization requirements.
                </p>
                <button type="button" onClick={restoreBrowserDefaults}>
                  Restore browser defaults
                </button>
              </section>
            </>
          ) : (
            <section className="settings-canonical-controls">
              {catalog.isPending && (
                <LoadingState label="Loading Settings controls…" />
              )}
              {catalog.isError && <ErrorState error={catalog.error} />}
              {catalog.data?.items
                .filter((item) => item.section === section)
                .map((item) => (
                  <CanonicalSettingsControl
                    key={item.key}
                    item={item}
                    value={valueFor(item)}
                    editable={editableSharedSettings}
                    onChange={(value) => queueShared(item, value)}
                  />
                ))}
              {catalog.data && (
                <p className="notes">
                  Shared controls remain locked until a configured Settings
                  administrator session authorizes a real server-side change.
                  Filesystem paths are deliberately server-managed and never
                  exposed to the browser.
                </p>
              )}
            </section>
          )}
          {section === "diagnostics_support" ? (
            <section
              className="settings-danger-zone"
              aria-labelledby="settings-danger-zone-title"
            >
              <h2 id="settings-danger-zone-title">Danger Zone</h2>
              <p>
                Destructive actions require typed confirmation and never modify
                operational EOAT records.
              </p>
              <div>
                <button
                  type="button"
                  disabled={!canSetDefaults}
                  onClick={() => setPendingAction("set-defaults")}
                >
                  Set Current Configuration as Defaults
                </button>
                <button
                  type="button"
                  disabled={!canResetSettings}
                  onClick={() => setPendingAction("reset-all")}
                >
                  Reset All Settings
                </button>
                <button
                  type="button"
                  disabled={!canResetSettings}
                  onClick={() => setPendingAction("factory-reset")}
                >
                  Factory Reset
                </button>
              </div>
            </section>
          ) : null}
        </div>
      </div>
      <footer className="settings-action-bar">
        <span>
          {session
            ? `Administrator: ${session.identity?.display_name || "authenticated"}`
            : "Shared settings require administrator authentication."}
        </span>
        {session ? (
          <button type="button" onClick={signOut}>
            Sign out
          </button>
        ) : (
          <output>
            Sign in with an EOAT Atlas administrator account to edit shared
            Settings.
          </output>
        )}
        <button type="button" onClick={exportBrowserSettings}>
          Export browser settings
        </button>
        <span aria-live="polite">
          {Object.keys(draftShared).length ? "Unsaved changes" : ""}
        </span>
        <button
          type="button"
          disabled={!Object.keys(draftShared).length}
          onClick={discardShared}
        >
          Reload Settings
        </button>
        <button
          type="button"
          disabled={
            !canResetSettings ||
            section === "data_sources" ||
            section === "about"
          }
          onClick={() => setPendingAction("reset-section")}
        >
          Reset Section
        </button>
        <button
          type="button"
          disabled={!editableSharedSettings || !Object.keys(draftShared).length}
          onClick={saveShared}
        >
          Save Settings
        </button>
      </footer>
      {pendingAction ? (
        <section
          className="settings-confirmation"
          role="dialog"
          aria-modal="true"
          aria-labelledby="settings-confirmation-title"
        >
          <h2 id="settings-confirmation-title">
            {pendingAction === "reset-section"
              ? "Reset Section"
              : pendingAction === "reset-all"
                ? "Reset All Settings"
                : pendingAction === "set-defaults"
                  ? "Set Current Configuration as Defaults"
                  : "Factory Reset"}
          </h2>
          <p>
            Type <strong>{actionConfirmation[pendingAction]}</strong> to
            confirm. This changes Settings only; operational EOAT data is never
            modified.
          </p>
          <input
            aria-label="Confirmation"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
          />
          <button
            type="button"
            onClick={() => {
              setPendingAction(null);
              setConfirmation("");
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={confirmation !== actionConfirmation[pendingAction]}
            onClick={executeSettingsAction}
          >
            Confirm
          </button>
        </section>
      ) : null}
      {authError ? <ErrorState error={authError} /> : null}
    </section>
  );
}
