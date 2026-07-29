import {
  useCallback,
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
import { readLibraryContext } from "@/app/libraryContext";
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

function trapFocus(
  event: KeyboardEvent<HTMLElement>,
  root: HTMLElement | null,
) {
  if (event.key !== "Tab" || !root) return;
  const focusable = root.querySelectorAll<HTMLElement>(
    "button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex='-1'])",
  );
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function isActiveNavigation(pathname: string, destination: string) {
  if (destination === "/library")
    return (
      pathname === "/library" || /^\/(eoats|machines|tools)\//.test(pathname)
    );
  return pathname === destination;
}

export function AppShell({ children }: PropsWithChildren) {
  const location = useLocation();
  const navigate = useNavigate();
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLElement>(null);
  const restoreSearchFocus = useRef<HTMLElement | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [initialQuery, setInitialQuery] = useState("");
  const [scrolled, setScrolled] = useState(false);
  const [settings, setSettings] = useState<BrowserSettings>(() =>
    readBrowserSettings(),
  );
  const theme = resolvedTheme(settings.theme);
  const profileRoute = /^\/(eoats|machines|tools)\//.test(location.pathname);

  const closeMenu = useCallback((restore = true) => {
    setMenuOpen(false);
    if (restore) window.setTimeout(() => menuButtonRef.current?.focus(), 0);
  }, []);
  const openMenu = useCallback(() => {
    setSearchOpen(false);
    setMenuOpen(true);
    window.setTimeout(
      () => menuRef.current?.querySelector<HTMLElement>("button")?.focus(),
      0,
    );
  }, []);
  const openSearch = useCallback((text = "") => {
    restoreSearchFocus.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    setMenuOpen(false);
    setInitialQuery(text);
    setSearchOpen(true);
  }, []);
  const closeSearch = useCallback(() => {
    setSearchOpen(false);
    window.setTimeout(() => restoreSearchFocus.current?.focus(), 0);
  }, []);

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
  }, [openSearch]);
  useEffect(() => {
    const handler = () => setSettings(readBrowserSettings());
    window.addEventListener("atlas-settings-changed", handler);
    return () => window.removeEventListener("atlas-settings-changed", handler);
  }, []);
  useEffect(() => {
    const refresh = () => setScrolled(window.scrollY > 10);
    refresh();
    window.addEventListener("scroll", refresh, { passive: true });
    return () => window.removeEventListener("scroll", refresh);
  }, []);
  useEffect(() => {
    setMenuOpen(false);
    setSearchOpen(false);
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
        if (location.pathname === "/") {
          event.preventDefault();
          window.dispatchEvent(
            new CustomEvent("atlas-focus-home-search", { detail: event.key }),
          );
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [
    closeMenu,
    closeSearch,
    location.pathname,
    menuOpen,
    openSearch,
    searchOpen,
  ]);

  const returnToLibrary = () => {
    const context = readLibraryContext(location.state);
    const historyIndex =
      (window.history.state as { idx?: number } | null)?.idx || 0;
    if (context && historyIndex > 0) {
      navigate(-1);
      return;
    }
    navigate(`/library${context?.search || ""}`, {
      replace: true,
      state: context ? { restoreLibraryContext: context } : undefined,
    });
  };

  return (
    <div
      className="atlas-app-shell"
      data-motion-reduced={settings.reduceMotion || undefined}
      data-scrolled={scrolled || undefined}
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
          ref={menuButtonRef}
          className="atlas-icon-button atlas-menu-button"
          type="button"
          aria-label={
            menuOpen ? "Close navigation menu" : "Open navigation menu"
          }
          aria-expanded={menuOpen}
          aria-haspopup="dialog"
          onClick={() => (menuOpen ? closeMenu(false) : openMenu())}
        >
          <span />
          <span />
          <span />
        </button>
        {profileRoute && (
          <button
            className="atlas-back-button"
            type="button"
            onClick={returnToLibrary}
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
          aria-haspopup="dialog"
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
          <section
            ref={menuRef}
            className="atlas-menu-overlay"
            role="dialog"
            aria-modal="true"
            aria-label="Atlas navigation"
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                closeMenu();
                return;
              }
              trapFocus(event, menuRef.current);
            }}
          >
            <button
              className="atlas-menu-close"
              type="button"
              onClick={() => closeMenu()}
              aria-label="Close navigation menu"
            >
              ×
            </button>
            <nav aria-label="Atlas navigation">
              {navigation.map(([to, label, icon]) => (
                <Link
                  key={to}
                  to={to}
                  className={
                    isActiveNavigation(location.pathname, to) ? "active" : ""
                  }
                  aria-current={
                    isActiveNavigation(location.pathname, to)
                      ? "page"
                      : undefined
                  }
                  onClick={() => closeMenu(false)}
                >
                  <span aria-hidden="true">{icon}</span>
                  {label}
                </Link>
              ))}
            </nav>
          </section>
        </div>
      )}
      <main id="main-content" className="atlas-main">
        {children}
      </main>
      <GlobalSearchOverlay
        open={searchOpen}
        initialQuery={initialQuery}
        onClose={closeSearch}
      />
    </div>
  );
}
