import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { apiClient } from "@/api/client";
import { entityPath } from "@/api/routes";
import { readRecentItems } from "@/api/recent";

export function FoundationPage() {
  const [query, setQuery] = useState("");
  const recents = readRecentItems();
  const health = useQuery({
    queryKey: ["health"],
    queryFn: () => apiClient.getHealth(),
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
        <span className={`atlas-status-dot ${health.isError ? "error" : ""}`} />
        {health.isPending
          ? "Checking EOAT Atlas data…"
          : health.isError
            ? "EOAT Atlas API unavailable"
            : health.data
              ? `API connected · Version ${health.data.application_version} · Writes ${health.data.writes_enabled ? "enabled" : "disabled"}`
              : "Data status unavailable"}
      </div>
    </section>
  );
}
