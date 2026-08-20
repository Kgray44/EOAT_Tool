import { useEffect, useState } from "react";
import {
  readBrowserSettings,
  resolvedTheme,
  type BrowserSettings,
} from "@/app/browserSettings";

function applyBrowserAppearance(settings: BrowserSettings) {
  const theme = resolvedTheme(settings.theme);
  document.documentElement.dataset.atlasTheme = theme;
  document.documentElement.dataset.atlasAccent = settings.accent;
  document.documentElement.dataset.atlasContrast = String(
    settings.enhancedContrast,
  );
  document.documentElement.style.setProperty(
    "--atlas-motion-scale",
    settings.reduceMotion || settings.animationSpeed === "reduced"
      ? "0.28"
      : settings.animationSpeed === "smooth"
        ? "1.25"
        : "1",
  );
}

/** Applies the one saved Atlas browser preference before any route is shown. */
export function BrowserAppearance() {
  const [settings, setSettings] = useState<BrowserSettings>(() =>
    readBrowserSettings(),
  );

  useEffect(() => applyBrowserAppearance(settings), [settings]);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-color-scheme: light)");
    const refresh = () => setSettings((value) => ({ ...value }));
    media.addEventListener("change", refresh);
    return () => media.removeEventListener("change", refresh);
  }, []);

  useEffect(() => {
    const refresh = () => setSettings(readBrowserSettings());
    window.addEventListener("atlas-settings-changed", refresh);
    return () => window.removeEventListener("atlas-settings-changed", refresh);
  }, []);

  return null;
}
