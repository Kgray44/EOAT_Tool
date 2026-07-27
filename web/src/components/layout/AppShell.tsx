import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PropsWithChildren,
} from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  readBrowserSettings,
  resolvedTheme,
  type BrowserSettings,
} from "@/app/browserSettings";
import { GlobalSearchOverlay } from "@/components/search/GlobalSearchOverlay";

const navigation = [
  ["/", "Home", "⌂"],
  ["/fit-check", "Fit Check", "◉"],
  ["/library", "Library", "▦"],
  ["/settings", "Settings", "⚙"],
] as const;

function isEditable(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  return Boolean(
    target.closest(
      "input, textarea, select, [contenteditable='true'], [role='combobox']",
    ),
  );
}

export function AppShell({ children }: PropsWithChildren) {
  const location = useLocation();
  const navigate = useNavigate();
  const restoreFocus = useRef<HTMLElement | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [initialQuery, setInitialQuery] = useState("");
  const [settings, setSettings] = useState<BrowserSettings>(() =>
    readBrowserSettings(),
  );
  const theme = resolvedTheme(settings.theme);
  const profileRoute = /^\/(eoats|machines|tools)\//.test(location.pathname);
  const openSearch = (text = "") => {
    restoreFocus.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    setMenuOpen(false);
    setInitialQuery(text);
    setSearchOpen(true);
  };
  const closeSearch = () => {
    setSearchOpen(false);
    window.setTimeout(() => restoreFocus.current?.focus(), 0);
  };
  const closeMenu = () => setMenuOpen(false);

  useEffect(() => {
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
  }, [settings, theme]);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(prefers-color-scheme: light)");
    const refresh = () => setSettings((value) => ({ ...value }));
    media.addEventListener("change", refresh);
    return () => media.removeEventListener("change", refresh);
  }, []);
  useEffect(() => {
    const handler = (event: Event) =>
      openSearch((event as CustomEvent<string>).detail || "");
    window.addEventListener("atlas-open-search", handler);
    return () => window.removeEventListener("atlas-open-search", handler);
  });
  useEffect(() => {
    const handler = () => setSettings(readBrowserSettings());
    window.addEventListener("atlas-settings-changed", handler);
    return () => window.removeEventListener("atlas-settings-changed", handler);
  }, []);
  useEffect(() => {
    closeMenu();
    if (searchOpen) closeSearch();
    // Route changes must not leave an active overlay above a new page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname, location.search]);
  useEffect(() => {
    const handler = (event: globalThis.KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        openSearch();
        return;
      }
      if (event.key === "Escape") {
        if (searchOpen) closeSearch();
        else if (menuOpen) closeMenu();
        return;
      }
      if (
        !searchOpen &&
        !menuOpen &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey &&
        !isEditable(event.target) &&
        event.key.length === 1 &&
        event.key.trim()
      ) {
        openSearch(event.key);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  });
  const onOverlayKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeMenu();
    }
  };
  return (
    <div
      className="atlas-app-shell"
      data-motion-reduced={settings.reduceMotion || undefined}
    >
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <div className="atlas-ambient" aria-hidden="true">
        <i />
        <i />
        <i />
      </div>
      <header className="atlas-topbar">
        <button
          className="atlas-icon-button atlas-menu-button"
          type="button"
          aria-label={
            menuOpen ? "Close navigation menu" : "Open navigation menu"
          }
          aria-expanded={menuOpen}
          onClick={() => {
            setSearchOpen(false);
            setMenuOpen((value) => !value);
          }}
        >
          <span />
          <span />
          <span />
        </button>
        {profileRoute && (
          <button
            className="atlas-back-button"
            type="button"
            onClick={() => navigate("/library")}
          >
            ← Back to Library
          </button>
        )}
        <Link className="atlas-logo" to="/" aria-label="EOAT Atlas home">
          <span className="atlas-logo-mark" aria-hidden="true">
            ◈
          </span>
          <span>
            <b>EOAT</b>
            <em>Atlas</em>
          </span>
        </Link>
        <button
          className="atlas-icon-button atlas-search-button"
          type="button"
          aria-label={searchOpen ? "Close search" : "Open search"}
          aria-expanded={searchOpen}
          onClick={() => (searchOpen ? closeSearch() : openSearch())}
        >
          <span aria-hidden="true">⌕</span>
        </button>
      </header>
      {menuOpen && (
        <div
          className="atlas-menu-layer"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeMenu();
          }}
        >
          <nav
            className="atlas-menu-overlay"
            aria-label="Atlas navigation"
            onKeyDown={onOverlayKeyDown}
          >
            <button
              className="atlas-menu-close"
              type="button"
              onClick={closeMenu}
              aria-label="Close navigation menu"
            >
              ×
            </button>
            {navigation.map(([to, label, icon]) => (
              <Link
                key={to}
                to={to}
                className={location.pathname === to ? "active" : ""}
                onClick={closeMenu}
              >
                <span aria-hidden="true">{icon}</span>
                {label}
              </Link>
            ))}
          </nav>
        </div>
      )}
      <main id="main-content" className="atlas-main">
        {children}
      </main>
      <footer className="atlas-footer">
        <span className="atlas-status-dot" />
        Read-only browser interface · Data is authoritative only when confirmed
        by the EOAT Atlas API.
      </footer>
      <GlobalSearchOverlay
        open={searchOpen}
        initialQuery={initialQuery}
        onClose={closeSearch}
      />
    </div>
  );
}
