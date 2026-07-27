import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "@/api/client";
import { entityPath } from "@/api/routes";
import { readRecentItems } from "@/api/recent";

export function FoundationPage() {
  const [query, setQuery] = useState("");
  const recents = readRecentItems();
  const dataStatus = useQuery({
    queryKey: ["data-status"],
    queryFn: () => apiClient.getDataStatus(),
  });
  const openSearch = (value = query) =>
    window.dispatchEvent(
      new CustomEvent("atlas-open-search", { detail: value }),
    );
  return (
    <section className="atlas-home-page" aria-labelledby="home-title">
      <header className="atlas-page-title">
        <h1 id="home-title">Home</h1>
        <span />
      </header>
      <section className="atlas-home-card">
        <h2>Get Started</h2>
        <p>Find the right EOAT for your application</p>
        <form
          className="atlas-home-search"
          onSubmit={(event) => {
            event.preventDefault();
            openSearch();
          }}
        >
          <label className="visually-hidden" htmlFor="home-search">
            Search the EOAT Atlas Library
          </label>
          <span aria-hidden="true">⌕</span>
          <input
            id="home-search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onFocus={() => openSearch(query)}
            placeholder="Enter Tool #, Mold #, Machine #, or EOAT ID…"
          />
          <button type="submit" aria-label="Search EOAT Atlas">
            →
          </button>
        </form>
        <div className="atlas-recents">
          <h3>Recent Searches</h3>
          {recents.length ? (
            <div className="atlas-recent-links">
              {recents.slice(0, 3).map((item) => (
                <Link
                  key={`${item.category}-${item.identifier}`}
                  to={entityPath(item.category, item.identifier)}
                >
                  {item.label}
                </Link>
              ))}
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
            : dataStatus.data
              ? `Read-only browser · API available · data modified ${new Date(dataStatus.data.data_last_modified_at).toLocaleString()} · fetched ${new Date(dataStatus.dataUpdatedAt).toLocaleTimeString()}`
              : "Read-only browser · data status unavailable"}
      </div>
    </section>
  );
}
