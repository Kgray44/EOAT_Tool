import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { apiClient, type SearchResult } from "@/api/client";
import { entityPath, type EntityCategory } from "@/api/routes";
import { readRecentItems, rememberItem } from "@/api/recent";
import {
  isRoutableAuthoritativeIdentifier,
  presentationText,
} from "@/api/presentation";
import {
  searchableDestinations,
  type NavigationDestination,
} from "@/app/navigation";

type Props = { open: boolean; initialQuery: string; onClose: () => void };
type SearchEntry =
  | { kind: "entity"; value: SearchResult }
  | { kind: "destination"; value: NavigationDestination };

function resultLabel(result: SearchResult) {
  return `${result.category}: ${presentationText(result.title)} ${presentationText(result.identifier)}`;
}

function destinationLabel(destination: NavigationDestination) {
  return `${destination.group}: ${destination.label}`;
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
  const session = useQuery({
    queryKey: ["authentication-session"],
    queryFn: () => apiClient.getAuthenticatedSession(),
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

  const entityResults = (search.data || []).filter((result) =>
    isRoutableAuthoritativeIdentifier(result.identifier),
  );
  const destinations = searchableDestinations(debouncedQuery, session.data);
  const results: SearchEntry[] = [
    ...entityResults.map((value) => ({ kind: "entity" as const, value })),
    ...destinations.map((value) => ({ kind: "destination" as const, value })),
  ];
  const resultIdentity = results
    .map((result) =>
      result.kind === "entity"
        ? `entity:${result.value.category}:${result.value.identifier}`
        : `destination:${result.value.path}`,
    )
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
    const path = entityPath(category, result.identifier);
    if (path) navigate(path);
  };
  const openDestination = (destination: NavigationDestination) => {
    onClose();
    navigate(destination.path);
  };
  const openRecent = (category: EntityCategory, identifier: string) => {
    onClose();
    const path = entityPath(category, identifier);
    if (path) navigate(path);
  };
  const openHighlightedOrExact = () => {
    const normalized = query.trim().toLocaleLowerCase();
    const exact = entityResults.find(
      (result) =>
        result.identifier.toLocaleLowerCase() === normalized ||
        result.title.toLocaleLowerCase() === normalized,
    );
    if (exact) openResult(exact);
    else if (results[highlight]) {
      const result = results[highlight];
      if (result.kind === "entity") openResult(result.value);
      else openDestination(result.value);
    }
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
            placeholder="Search entities, pages, or settings"
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
            {(["Entities", "Pages", "Settings", "Administration"] as const).map(
              (group) => {
                const groupResults = results.filter((result) =>
                  result.kind === "entity"
                    ? group === "Entities"
                    : result.value.group === group,
                );
                if (!groupResults.length) return null;
                return (
                  <section
                    className="atlas-search-group"
                    key={group}
                    aria-label={`${group} results`}
                  >
                    <p className="atlas-section-label">{group}</p>
                    {groupResults.map((result) => {
                      const index = results.indexOf(result);
                      const entity =
                        result.kind === "entity" ? result.value : undefined;
                      const destination =
                        result.kind === "destination"
                          ? result.value
                          : undefined;
                      return (
                        <button
                          className="atlas-search-result"
                          data-highlighted={index === highlight}
                          key={
                            entity
                              ? `${entity.category}-${entity.identifier}`
                              : destination!.path
                          }
                          type="button"
                          onMouseEnter={() => setHighlight(index)}
                          onClick={() =>
                            entity
                              ? openResult(entity)
                              : openDestination(destination!)
                          }
                        >
                          <span
                            className="atlas-result-icon"
                            aria-hidden="true"
                          >
                            {entity
                              ? entity.category === "machine"
                                ? "◫"
                                : entity.category === "tool"
                                  ? "◇"
                                  : "◉"
                              : "↗"}
                          </span>
                          <span>
                            <strong>
                              {entity
                                ? presentationText(
                                    entity.title || entity.identifier,
                                  )
                                : destination!.label}
                            </strong>
                            <small>
                              {entity
                                ? presentationText(
                                    entity.subtitle || entity.identifier,
                                  )
                                : destination!.path}
                            </small>
                          </span>
                          <em>
                            {entity ? entity.category : destination!.group}
                          </em>
                          <span className="visually-hidden">
                            {entity
                              ? resultLabel(entity)
                              : destinationLabel(destination!)}
                          </span>
                        </button>
                      );
                    })}
                  </section>
                );
              },
            )}
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
