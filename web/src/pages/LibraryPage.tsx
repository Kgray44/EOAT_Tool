import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { apiClient, type SearchResult } from "@/api/client";
import { entityPath, type EntityCategory } from "@/api/routes";
import {
  readRecentItems,
  removeRecentItem,
  type RecentItem,
} from "@/api/recent";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "@/components/feedback/StateViews";
import {
  captureLibraryContext,
  readLibraryContext,
  saveLibraryContext,
} from "@/app/libraryContext";

type Filter = "all" | EntityCategory;

function ResultCard({ result }: { result: SearchResult | RecentItem }) {
  const location = useLocation();
  const category = result.category as EntityCategory;
  const title = "title" in result ? result.title : result.label;
  const subtitle =
    "subtitle" in result
      ? result.subtitle
      : new Date(result.viewedAt).toLocaleDateString();
  return (
    <Link
      className="result-card"
      to={entityPath(category, result.identifier)}
      state={{
        libraryContext: captureLibraryContext(location, result.identifier),
      }}
      onClick={() =>
        saveLibraryContext(captureLibraryContext(location, result.identifier))
      }
    >
      <span>{category}</span>
      <strong>{title}</strong>
      <small>
        {result.identifier}
        {subtitle ? ` · ${subtitle}` : ""}
      </small>
    </Link>
  );
}

export function LibraryPage() {
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const query = params.get("q") || "";
  const filter = (params.get("type") || "all") as Filter;
  const page = Math.max(1, Number(params.get("page") || "1"));
  const [draft, setDraft] = useState(query);
  const [recent, setRecent] = useState<RecentItem[]>([]);
  useEffect(() => {
    setDraft(query);
    setRecent(readRecentItems());
  }, [query]);
  useEffect(() => {
    const context = readLibraryContext(location.state);
    if (!context) return;
    const frame = window.requestAnimationFrame(() =>
      window.scrollTo(0, context.scrollY),
    );
    return () => window.cancelAnimationFrame(frame);
  }, [location.state]);
  const search = useQuery({
    queryKey: ["library", "search", query],
    queryFn: () => apiClient.search(query),
    enabled: !!query,
  });
  const browseEoats = useQuery({
    queryKey: ["library", "eoats", page],
    queryFn: () => apiClient.getEoats("", page),
    enabled: !query && filter === "eoat",
  });
  const browseMachines = useQuery({
    queryKey: ["library", "machines", page],
    queryFn: () => apiClient.getMachines("", page),
    enabled: !query && filter === "machine",
  });
  const browseTools = useQuery({
    queryKey: ["library", "tools", page],
    queryFn: () => apiClient.getTools("", page),
    enabled: !query && filter === "tool",
  });
  const results = useMemo(
    () =>
      (search.data || []).filter(
        (result) => filter === "all" || result.category === filter,
      ),
    [filter, search.data],
  );
  const browse =
    filter === "eoat"
      ? browseEoats.data
      : filter === "machine"
        ? browseMachines.data
        : browseTools.data;
  const browseResults: SearchResult[] =
    filter === "eoat" && browseEoats.data
      ? browseEoats.data.items.map((item) => ({
          category: "eoat",
          identifier: item.business_identifier,
          title: item.display_name || item.business_identifier,
          subtitle: item.current_location,
          matched_field: "catalog",
        }))
      : filter === "machine" && browseMachines.data
        ? browseMachines.data.items.map((item) => ({
            category: "machine",
            identifier: item.machine_number,
            title: item.machine_name || item.machine_number,
            subtitle: item.area || "Machine",
            matched_field: "catalog",
          }))
        : filter === "tool" && browseTools.data
          ? browseTools.data.items.map((item) => ({
              category: "tool",
              identifier: item.business_identifier,
              title: item.display_name || item.business_identifier,
              subtitle: item.mold_number || item.tool_number || "Tool",
              matched_field: "catalog",
            }))
          : [];
  const activeQuery = query
    ? search
    : filter === "eoat"
      ? browseEoats
      : filter === "machine"
        ? browseMachines
        : filter === "tool"
          ? browseTools
          : undefined;
  const pending = activeQuery?.isPending ?? false;
  const error = activeQuery?.error;
  const update = (next: Record<string, string>) => {
    const values = new URLSearchParams(params);
    Object.entries(next).forEach(([key, value]) =>
      value ? values.set(key, value) : values.delete(key),
    );
    setParams(values);
  };

  return (
    <section className="library-page">
      <p className="eyebrow">Discovery</p>
      <h2>Library</h2>
      <p className="lede">
        Search the authoritative EOAT Atlas catalog. Results and filters remain
        in this URL.
      </p>
      <form
        className="library-controls"
        onSubmit={(event) => {
          event.preventDefault();
          update({ q: draft.trim(), page: "1" });
        }}
      >
        <label>
          Search{" "}
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Identifier, name, machine, tool, or mold"
          />
        </label>
        <label>
          Record type{" "}
          <select
            value={filter}
            onChange={(event) =>
              update({ type: event.target.value, page: "1" })
            }
          >
            <option value="all">All types</option>
            <option value="eoat">EOATs</option>
            <option value="machine">Machines</option>
            <option value="tool">Tools</option>
          </select>
        </label>
        <button type="submit">Search</button>
      </form>
      {!query && recent.length > 0 && (
        <section className="recent-items" aria-labelledby="recent-title">
          <h3 id="recent-title">Recently viewed on this browser</h3>
          <div className="result-deck">
            {recent.map((item) => (
              <div
                key={`${item.category}-${item.identifier}`}
                className="recent-card"
              >
                <ResultCard result={item} />
                <button
                  type="button"
                  aria-label={`Remove ${item.label} from recent items`}
                  onClick={() =>
                    setRecent(removeRecentItem(item.category, item.identifier))
                  }
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        </section>
      )}
      {!query && filter === "all" && (
        <EmptyState title="Choose a type or search">
          Select an entity type to browse a paginated catalog, or search across
          EOATs, machines, and tools.
        </EmptyState>
      )}
      {pending && <LoadingState label="Searching EOAT Atlas…" />}
      {error && <ErrorState error={error} />}
      {!pending && !error && query && results.length === 0 && (
        <EmptyState title="No matching records">
          No EOAT Atlas records matched this search.
        </EmptyState>
      )}
      {!pending && !error && (query ? results : browseResults).length > 0 && (
        <div className="result-deck">
          {(query ? results : browseResults).map((result) => (
            <ResultCard
              key={`${result.category}-${result.identifier}`}
              result={result}
            />
          ))}
        </div>
      )}
      {!query && browse && browse.pagination.pages > 1 && (
        <nav className="pagination" aria-label="Catalog pagination">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => update({ page: String(page - 1) })}
          >
            Previous
          </button>
          <span>
            Page {browse.pagination.page} of {browse.pagination.pages}
          </span>
          <button
            type="button"
            disabled={page >= browse.pagination.pages}
            onClick={() => update({ page: String(page + 1) })}
          >
            Next
          </button>
        </nav>
      )}
    </section>
  );
}
