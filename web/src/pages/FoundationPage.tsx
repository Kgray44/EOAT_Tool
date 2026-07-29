import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiClient, type SearchResult } from "@/api/client";
import { entityPath, type EntityCategory } from "@/api/routes";
import { readRecentItems, rememberItem } from "@/api/recent";
import {
  isRoutableAuthoritativeIdentifier,
  presentationText,
} from "@/api/presentation";

export function FoundationPage() {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [highlight, setHighlight] = useState(0);
  const searchRootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const recents = readRecentItems();
  const dataStatus = useQuery({
    queryKey: ["data-status"],
    queryFn: () => apiClient.getDataStatus(),
  });
  const search = useQuery({
    queryKey: ["mirrorline", "home-search", debouncedQuery],
    queryFn: () => apiClient.search(debouncedQuery),
    enabled: open && Boolean(debouncedQuery),
  });
  const results = (search.data || []).filter((result) =>
    isRoutableAuthoritativeIdentifier(result.identifier),
  );
  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 125);
    return () => window.clearTimeout(timer);
  }, [open, query]);
  useEffect(() => setHighlight(0), [debouncedQuery, results.length]);
  useEffect(() => {
    const handler = (event: Event) => {
      const text = String((event as CustomEvent<string>).detail || "");
      inputRef.current?.focus();
      setOpen(true);
      if (text) setQuery((value) => value + text);
    };
    window.addEventListener("atlas-focus-home-search", handler);
    return () => window.removeEventListener("atlas-focus-home-search", handler);
  }, []);
  useEffect(() => {
    const closeWhenOutside = (event: MouseEvent) => {
      if (!searchRootRef.current?.contains(event.target as Node))
        setOpen(false);
    };
    document.addEventListener("mousedown", closeWhenOutside);
    return () => document.removeEventListener("mousedown", closeWhenOutside);
  }, []);
  const openResult = (result: SearchResult) => {
    const category = result.category as EntityCategory;
    rememberItem({
      category,
      identifier: result.identifier,
      label: result.title || result.identifier,
    });
    setOpen(false);
    const path = entityPath(category, result.identifier);
    if (path) navigate(path);
  };
  const openRecent = (category: EntityCategory, identifier: string) => {
    setOpen(false);
    const path = entityPath(category, identifier);
    if (path) navigate(path);
  };
  const openSelectedOrExact = () => {
    const normalized = query.trim().toLocaleLowerCase();
    const exact = results.find(
      (result) =>
        result.identifier.toLocaleLowerCase() === normalized ||
        result.title.toLocaleLowerCase() === normalized,
    );
    if (exact) openResult(exact);
    else if (results[highlight]) openResult(results[highlight]);
  };
  const dataAgeMs = dataStatus.data
    ? Date.now() - new Date(dataStatus.data.data_last_modified_at).valueOf()
    : 0;
  const staleData =
    Number.isFinite(dataAgeMs) && dataAgeMs > 24 * 60 * 60 * 1000;
  return (
    <section className="atlas-home-page" aria-labelledby="home-title">
      <header className="atlas-page-title">
        <h1 id="home-title">Home</h1>
        <span />
      </header>
      <section className="atlas-home-card">
        <h2>Get Started</h2>
        <p>Find the right EOAT for your application</p>
        <div ref={searchRootRef} className="atlas-home-search-root">
          <form
            className="atlas-home-search"
            onSubmit={(event) => {
              event.preventDefault();
              openSelectedOrExact();
            }}
          >
            <label className="visually-hidden" htmlFor="home-search">
              Search the EOAT Atlas Library
            </label>
            <span aria-hidden="true">⌕</span>
            <input
              id="home-search"
              ref={inputRef}
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setOpen(true);
              }}
              onFocus={() => setOpen(true)}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.preventDefault();
                  setOpen(false);
                } else if (event.key === "ArrowDown" && results.length) {
                  event.preventDefault();
                  setHighlight((value) => (value + 1) % results.length);
                } else if (event.key === "ArrowUp" && results.length) {
                  event.preventDefault();
                  setHighlight(
                    (value) => (value - 1 + results.length) % results.length,
                  );
                }
              }}
              placeholder="Enter Tool #, Mold #, Machine #, or EOAT ID…"
            />
            <button type="submit" aria-label="Search EOAT Atlas">
              →
            </button>
          </form>
          {open && (
            <div className="atlas-home-search-dropdown" aria-live="polite">
              {query.trim() ? (
                <>
                  {search.isPending && (
                    <p className="atlas-empty">
                      Searching the authoritative catalog…
                    </p>
                  )}
                  {search.isError && (
                    <p className="atlas-empty">
                      Search is unavailable. Check the EOAT Atlas API and try
                      again.
                    </p>
                  )}
                  {!search.isPending &&
                    !search.isError &&
                    results.length === 0 && (
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
                        <strong>
                          {presentationText(result.title || result.identifier)}
                        </strong>
                        <small>
                          {presentationText(
                            result.subtitle || result.identifier,
                          )}
                        </small>
                      </span>
                      <em>{result.category}</em>
                    </button>
                  ))}
                </>
              ) : (
                <>
                  <p className="atlas-section-label">Recent searches</p>
                  {recents.length ? (
                    recents.map((item) => (
                      <button
                        className="atlas-search-result"
                        key={`${item.category}-${item.identifier}`}
                        type="button"
                        onClick={() =>
                          openRecent(item.category, item.identifier)
                        }
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
                </>
              )}
            </div>
          )}
        </div>
        <div className="atlas-recents">
          <h3>Recent Searches</h3>
          {recents.length ? (
            <div className="atlas-recent-links">
              {recents.slice(0, 3).flatMap((item) => {
                const path = entityPath(item.category, item.identifier);
                return path
                  ? [
                      <Link
                        key={`${item.category}-${item.identifier}`}
                        to={path}
                      >
                        {item.label}
                      </Link>,
                    ]
                  : [];
              })}
            </div>
          ) : (
            <p>No recent searches yet</p>
          )}
        </div>
      </section>
      <div className="atlas-data-status" aria-live="polite">
        <span
          className={`atlas-status-dot ${dataStatus.isError ? "error" : ""}`}
        />
        {dataStatus.isPending
          ? "Read-only browser · checking API freshness…"
          : dataStatus.isError
            ? "Read-only browser · API unavailable · data freshness unknown"
            : dataStatus.data && staleData
              ? "Read-only browser · API available · data may be stale · use the shown modification time before relying on this view"
              : dataStatus.data
                ? `Read-only browser · API available · data modified ${new Date(dataStatus.data.data_last_modified_at).toLocaleString()} · fetched ${new Date(dataStatus.dataUpdatedAt).toLocaleTimeString()}`
                : "Read-only browser · data status unavailable"}
      </div>
    </section>
  );
}
