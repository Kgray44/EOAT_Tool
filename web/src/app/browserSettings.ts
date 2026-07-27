export type AtlasThemePreference = "dark" | "light" | "system";
export type AnimationSpeed = "reduced" | "standard" | "smooth";

export type BrowserSettings = {
  theme: AtlasThemePreference;
  accent: "atlas_blue" | "neutral_gray" | "high_contrast_blue";
  animationSpeed: AnimationSpeed;
  reduceMotion: boolean;
  enhancedContrast: boolean;
};

const storageKey = "eoat-atlas-mirrorline-settings-v1";

export const defaultBrowserSettings: BrowserSettings = {
  theme: "dark",
  accent: "atlas_blue",
  animationSpeed: "standard",
  reduceMotion: false,
  enhancedContrast: true,
};

export function readBrowserSettings(): BrowserSettings {
  try {
    const stored = JSON.parse(
      localStorage.getItem(storageKey) || "{}",
    ) as Partial<BrowserSettings>;
    return { ...defaultBrowserSettings, ...stored };
  } catch {
    return defaultBrowserSettings;
  }
}

export function saveBrowserSettings(settings: BrowserSettings) {
  localStorage.setItem(storageKey, JSON.stringify(settings));
}

export function resolvedTheme(
  preference: AtlasThemePreference,
): "dark" | "light" {
  if (preference !== "system") return preference;
  return typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}
