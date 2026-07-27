import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { apiClient, type SearchResult } from "@/api/client";
import { entityPath, type EntityCategory } from "@/api/routes";
import { readRecentItems, rememberItem } from "@/api/recent";

type Props = { open: boolean; initialQuery: string; onClose: () => void };

function resultLabel(result: SearchResult) {
  return `${result.category}: ${result.title} ${result.identifier}`;
}

export function GlobalSearchOverlay({ open, initialQuery, onClose }: Props) {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [highlight, setHighlight] = useState(0);
  const [recents, setRecents] = useState(readRecentItems());
  const search = useQuery({
    queryKey: ["mirrorline", "global-search", debouncedQuery],
    queryFn: () => apiClient.search(debouncedQuery),
    enabled: open && Boolean(debouncedQuery),
  });

  useEffect(() => {
    if (!open) return;
    setQuery(initialQuery);
    setDebouncedQuery("");
    setHighlight(0);
    setRecents(readRecentItems());
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }, [initialQuery, open]);

  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 125);
    return () => window.clearTimeout(timer);
  }, [open, query]);

  const results = search.data || [];
  const resultIdentity = results
    .map((result) => `${result.category}:${result.identifier}`)
    .join("|");
  useEffect(() => {
    setHighlight(0);
  }, [debouncedQuery, resultIdentity, results.length]);
  const openResult = (result: SearchResult) => {
    const category = result.category as EntityCategory;
    rememberItem({
      category,
      identifier: result.identifier,
      label: result.title || result.identifier,
    });
    onClose();
    navigate(entityPath(category, result.identifier));
  };
  const openRecent = (category: EntityCategory, identifier: string) => {
    onClose();
    navigate(entityPath(category, identifier));
  };
  const openHighlightedOrExact = () => {
    const normalized = query.trim().toLocaleLowerCase();
    const exact = results.find(
      (result) =>
        result.identifier.toLocaleLowerCase() === normalized ||
        result.title.toLocaleLowerCase() === normalized,
    );
    if (exact) openResult(exact);
    else if (results[highlight]) openResult(results[highlight]);
  };
  const trapFocus = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Tab") return;
    const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
      "button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex='-1'])",
    );
    if (!focusable?.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  if (!open) return null;
  return (
    <div
      className="atlas-overlay-layer"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={dialogRef}
        className="atlas-search-overlay"
        role="dialog"
        aria-modal="true"
        aria-label="Search EOAT Atlas"
        onKeyDown={trapFocus}
      >
        <label className="visually-hidden" htmlFor="atlas-global-search">
          Search EOAT Atlas
        </label>
        <div className="atlas-search-input-wrap">
          <span aria-hidden="true">⌕</span>
          <input
            id="atlas-global-search"
            ref={inputRef}
            value={query}
            placeholder="Search EOATs, machines, or tools"
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                onClose();
              }
              if (event.key === "ArrowDown" && results.length) {
                event.preventDefault();
                setHighlight((value) => (value + 1) % results.length);
              }
              if (event.key === "ArrowUp" && results.length) {
                event.preventDefault();
                setHighlight(
                  (value) => (value - 1 + results.length) % results.length,
                );
              }
              if (event.key === "Enter" && results.length) {
                event.preventDefault();
                openHighlightedOrExact();
              }
            }}
          />
          <kbd>ESC</kbd>
        </div>
        {query.trim() ? (
          <div className="atlas-search-results" aria-live="polite">
            {!search.isPending && !search.isError && (
              <p className="visually-hidden">
                {results.length} search results available.
              </p>
            )}
            {search.isPending && (
              <p className="atlas-empty">
                Searching the authoritative catalog…
              </p>
            )}
            {search.isError && (
              <p className="atlas-empty">
                Search is unavailable. Check the EOAT Atlas API and try again.
              </p>
            )}
            {!search.isPending && !search.isError && results.length === 0 && (
              <p className="atlas-empty">No Library profile found.</p>
            )}
            {results.map((result, index) => (
              <button
                className="atlas-search-result"
                data-highlighted={index === highlight}
                key={`${result.category}-${result.identifier}`}
                type="button"
                onMouseEnter={() => setHighlight(index)}
                onClick={() => openResult(result)}
              >
                <span className="atlas-result-icon" aria-hidden="true">
                  {result.category === "machine"
                    ? "◫"
                    : result.category === "tool"
                      ? "◇"
                      : "◉"}
                </span>
                <span>
                  <strong>{result.title || result.identifier}</strong>
                  <small>{result.subtitle || result.identifier}</small>
                </span>
                <em>{result.category}</em>
                <span className="visually-hidden">{resultLabel(result)}</span>
              </button>
            ))}
          </div>
        ) : (
          <div className="atlas-search-results">
            <p className="atlas-section-label">Recent searches</p>
            {recents.length ? (
              recents.map((item) => (
                <button
                  className="atlas-search-result"
                  key={`${item.category}-${item.identifier}`}
                  type="button"
                  onClick={() => openRecent(item.category, item.identifier)}
                >
                  <span className="atlas-result-icon" aria-hidden="true">
                    ↗
                  </span>
                  <span>
                    <strong>{item.label}</strong>
                    <small>
                      {item.category} · {item.identifier}
                    </small>
                  </span>
                  <em>Recent</em>
                </button>
              ))
            ) : (
              <p className="atlas-empty">No recent searches yet.</p>
            )}
            <p className="atlas-section-label">Suggestions</p>
            <p className="atlas-empty">
              Type an identifier, machine, tool, or EOAT to search the Library.
            </p>
          </div>
        )}
        <footer>
          Use <kbd>↑</kbd> <kbd>↓</kbd> to select · <kbd>Enter</kbd> to open
        </footer>
      </section>
    </div>
  );
}
