import { useEffect, useId, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import {
  apiClient,
  type CatalogActivity,
  type CatalogFilters,
  type CatalogOptionKind,
  type SearchResult,
} from "@/api/client";
import { entityPath, type EntityCategory } from "@/api/routes";
import {
  isRoutableAuthoritativeIdentifier,
  presentationText,
} from "@/api/presentation";
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
type LibraryResult = (SearchResult | RecentItem) & {
  photo_document_uuid?: string | null;
  photo_available_through_web?: boolean;
};

function ResultCard({ result }: { result: LibraryResult }) {
  const location = useLocation();
  const category = result.category as EntityCategory;
  const title = "title" in result ? result.title : result.label;
  const subtitle =
    "subtitle" in result
      ? result.subtitle
      : new Date(result.viewedAt).toLocaleDateString();
  const path = entityPath(category, result.identifier);
  if (!path) return null;
  return (
    <Link
      className="result-card"
      to={path}
      state={{
        libraryContext: captureLibraryContext(location, result.identifier),
      }}
      onClick={() =>
        saveLibraryContext(captureLibraryContext(location, result.identifier))
      }
    >
      <span className="result-card__media" aria-hidden="true">
        {category === "eoat" ? "◇" : category === "machine" ? "▣" : "▤"}
        {category === "eoat" &&
        result.photo_document_uuid &&
        result.photo_available_through_web ? (
          <img
            src={apiClient.photoThumbnailUrl(result.photo_document_uuid)}
            alt=""
            loading="lazy"
            onError={(event) => {
              event.currentTarget.remove();
            }}
          />
        ) : null}
      </span>
      <span className="result-card__body">
        <small className="result-card__status">In Service</small>
        <strong>{presentationText(title)}</strong>
        <span>{category === "eoat" ? "Vacuum" : category}</span>
      </span>
      <small>
        {presentationText(result.identifier)}
        {subtitle ? ` · ${subtitle}` : ""}
      </small>
    </Link>
  );
}

function CatalogSelector({
  label,
  kind,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  kind: CatalogOptionKind;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  const listId = `catalog-option-${kind}-${useId().replaceAll(":", "")}`;
  const options = useQuery({
    queryKey: ["catalog-options", kind, value],
    queryFn: () => apiClient.getCatalogOptions(kind, value),
  });
  return (
    <label>
      {label}
      <span className="library-selector-control">
        <input
          list={listId}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          aria-label={label}
          placeholder={placeholder || `Select or search ${label.toLowerCase()}`}
          aria-describedby={options.isError ? `${listId}-error` : undefined}
        />
        {value ? (
          <button
            type="button"
            aria-label={`Clear ${label}`}
            onClick={() => onChange("")}
          >
            Clear
          </button>
        ) : null}
      </span>
      <datalist id={listId}>
        {(options.data || []).map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </datalist>
      {options.isError ? (
        <small id={`${listId}-error`}>
          Options are temporarily unavailable.
        </small>
      ) : null}
    </label>
  );
}

export function LibraryPage() {
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const query = params.get("q") || "";
  const filter = (params.get("type") || "all") as Filter;
  const activity = (params.get("status") || "active") as CatalogActivity;
  const page = Math.max(1, Number(params.get("page") || "1"));
  const [draft, setDraft] = useState(query);
  const [locationDraft, setLocationDraft] = useState(
    params.get("machine") || "",
  );
  const [advancedOpen, setAdvancedOpen] = useState(() =>
    [
      "eoatType",
      "plant",
      "area",
      "cleanroom",
      "tool",
      "mold",
      "robot",
      "eoat",
    ].some((key) => Boolean(params.get(key))),
  );
  const [recent, setRecent] = useState<RecentItem[]>([]);
  useEffect(() => {
    setDraft(query);
    setLocationDraft(params.get("machine") || "");
    setRecent(readRecentItems());
  }, [params, query]);
  useEffect(() => {
    const context = readLibraryContext(location.state);
    if (!context) return;
    const frame = window.requestAnimationFrame(() =>
      window.scrollTo(0, context.scrollY),
    );
    return () => window.cancelAnimationFrame(frame);
  }, [location.state]);
  const catalogFilters = useMemo<CatalogFilters>(
    () => ({
      eoatType: params.get("eoatType") || undefined,
      plant: params.get("plant") || undefined,
      area: params.get("area") || undefined,
      cleanroom: params.get("cleanroom") || undefined,
      machine: params.get("machine") || undefined,
      tool: params.get("tool") || undefined,
      mold: params.get("mold") || undefined,
      robot: params.get("robot") || undefined,
      eoat: params.get("eoat") || undefined,
      sort: params.get("sort") || undefined,
    }),
    [params],
  );
  const hasCatalogFilters = Object.values(catalogFilters).some(Boolean);
  const searchUsesGlobalIndex = Boolean(query) && !hasCatalogFilters;
  const search = useQuery({
    queryKey: ["library", "search", query],
    queryFn: () => apiClient.search(query),
    enabled: searchUsesGlobalIndex,
  });
  const browseEoats = useQuery({
    queryKey: ["library", "eoats", query, page, activity, catalogFilters],
    queryFn: () => apiClient.getEoats(query, page, activity, catalogFilters),
    enabled: !searchUsesGlobalIndex && (filter === "eoat" || filter === "all"),
  });
  const browseMachines = useQuery({
    queryKey: ["library", "machines", query, page, activity, catalogFilters],
    queryFn: () => apiClient.getMachines(query, page, activity, catalogFilters),
    enabled:
      !searchUsesGlobalIndex && (filter === "machine" || filter === "all"),
  });
  const browseTools = useQuery({
    queryKey: ["library", "tools", query, page, activity, catalogFilters],
    queryFn: () => apiClient.getTools(query, page, activity, catalogFilters),
    enabled: !searchUsesGlobalIndex && (filter === "tool" || filter === "all"),
  });
  const results = useMemo(
    () =>
      (search.data || []).filter(
        (result) =>
          (filter === "all" || result.category === filter) &&
          isRoutableAuthoritativeIdentifier(result.identifier),
      ),
    [filter, search.data],
  );
  const eoatResults: LibraryResult[] = browseEoats.data
    ? browseEoats.data.items.map((item) => ({
        category: "eoat",
        identifier: item.business_identifier,
        title: item.display_name || item.business_identifier,
        subtitle: item.current_location,
        matched_field: "catalog",
        photo_document_uuid: item.photo_document_uuid,
        photo_available_through_web: item.photo_available_through_web,
      }))
    : [];
  const machineResults: SearchResult[] = browseMachines.data
    ? browseMachines.data.items.map((item) => ({
        category: "machine",
        identifier: item.machine_number,
        title: item.machine_name || item.machine_number,
        subtitle: item.area || "Machine",
        matched_field: "catalog",
      }))
    : [];
  const toolResults: SearchResult[] = browseTools.data
    ? browseTools.data.items.map((item) => ({
        category: "tool",
        identifier: item.business_identifier,
        title: item.display_name || item.business_identifier,
        subtitle: item.mold_number || item.tool_number || "Tool",
        matched_field: "catalog",
      }))
    : [];
  const browseResults =
    filter === "eoat"
      ? eoatResults
      : filter === "machine"
        ? machineResults
        : filter === "tool"
          ? toolResults
          : [...eoatResults, ...machineResults, ...toolResults];
  const enabledBrowseQueries =
    filter === "eoat"
      ? [browseEoats]
      : filter === "machine"
        ? [browseMachines]
        : filter === "tool"
          ? [browseTools]
          : [browseEoats, browseMachines, browseTools];
  const pending = searchUsesGlobalIndex
    ? search.isPending
    : enabledBrowseQueries.some((value) => value.isPending);
  const error = searchUsesGlobalIndex
    ? search.error
    : enabledBrowseQueries.find((value) => value.error)?.error;
  const browsePagination = enabledBrowseQueries
    .map((value) => value.data?.pagination)
    .filter((value): value is NonNullable<typeof value> => Boolean(value))
    .sort((left, right) => right.pages - left.pages)[0];
  const update = (next: Record<string, string>) => {
    const values = new URLSearchParams(params);
    Object.entries(next).forEach(([key, value]) =>
      value ? values.set(key, value) : values.delete(key),
    );
    setParams(values);
  };

  return (
    <section className="library-page">
      <h2>Library</h2>
      <span className="library-title-accent" aria-hidden="true" />
      <form
        className="library-controls"
        onSubmit={(event) => {
          event.preventDefault();
          update({
            q: draft.trim(),
            machine: locationDraft.trim(),
            page: "1",
          });
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
        <label>
          Status{" "}
          <select
            value={activity}
            onChange={(event) =>
              update({ status: event.target.value, page: "1" })
            }
          >
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
            <option value="all">All records</option>
          </select>
        </label>
        <CatalogSelector
          label="Location / Machine"
          kind="machine"
          value={locationDraft}
          onChange={setLocationDraft}
        />
        <button
          type="button"
          className="library-secondary-control"
          aria-expanded={advancedOpen}
          onClick={() => setAdvancedOpen((current) => !current)}
        >
          Advanced Filters
        </button>
        <button type="submit">Search</button>
      </form>
      {advancedOpen && (
        <section
          className="library-advanced-filters"
          aria-label="Advanced Filters"
        >
          <CatalogSelector
            label="EOAT type"
            kind="eoat_type"
            value={catalogFilters.eoatType || ""}
            onChange={(eoatType) => update({ eoatType, page: "1" })}
          />
          <CatalogSelector
            label="Plant"
            kind="plant"
            value={catalogFilters.plant || ""}
            onChange={(plant) => update({ plant, page: "1" })}
          />
          <CatalogSelector
            label="Area"
            kind="area"
            value={catalogFilters.area || ""}
            onChange={(area) => update({ area, page: "1" })}
          />
          <CatalogSelector
            label="Cleanroom"
            kind="cleanroom"
            value={catalogFilters.cleanroom || ""}
            onChange={(cleanroom) => update({ cleanroom, page: "1" })}
          />
          <CatalogSelector
            label="Tool"
            kind="tool"
            value={catalogFilters.tool || ""}
            onChange={(tool) => update({ tool, page: "1" })}
          />
          <CatalogSelector
            label="Mold number"
            kind="mold"
            value={catalogFilters.mold || ""}
            onChange={(mold) => update({ mold, page: "1" })}
          />
          <CatalogSelector
            label="Robot"
            kind="robot"
            value={catalogFilters.robot || ""}
            onChange={(robot) => update({ robot, page: "1" })}
          />
          <CatalogSelector
            label="Related EOAT"
            kind="eoat"
            value={catalogFilters.eoat || ""}
            onChange={(eoat) => update({ eoat, page: "1" })}
          />
          <label>
            Sort
            <select
              value={catalogFilters.sort || ""}
              onChange={(event) =>
                update({ sort: event.target.value, page: "1" })
              }
            >
              <option value="">Default</option>
              <option value="updated_desc">Last updated</option>
              <option value="status">Status</option>
              <option value="business_identifier_desc">
                Identifier descending
              </option>
              <option value="machine_number_desc">Machine descending</option>
              <option value="mold">Mold</option>
            </select>
          </label>
          <button
            type="button"
            onClick={() =>
              update({
                eoatType: "",
                plant: "",
                area: "",
                cleanroom: "",
                machine: "",
                tool: "",
                mold: "",
                robot: "",
                eoat: "",
                sort: "",
                page: "1",
              })
            }
          >
            Reset filters
          </button>
        </section>
      )}
      <div className="library-category-rail" aria-label="Library category">
        {(
          [
            ["eoat", "EOATs"],
            ["tool", "Tools"],
            ["machine", "Machines"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            className={filter === value ? "is-active" : ""}
            aria-pressed={filter === value}
            onClick={() => update({ type: value, page: "1" })}
          >
            <span aria-hidden="true">
              {value === "eoat" ? "◇" : value === "tool" ? "▤" : "▣"}
            </span>
            {label}
          </button>
        ))}
      </div>
      {!query &&
        !hasCatalogFilters &&
        filter === "all" &&
        recent.length > 0 && (
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
                      setRecent(
                        removeRecentItem(item.category, item.identifier),
                      )
                    }
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
          </section>
        )}
      {pending && <LoadingState label="Searching EOAT Atlas…" />}
      {error && <ErrorState error={error} />}
      {!pending && !error && searchUsesGlobalIndex && results.length === 0 && (
        <EmptyState title="No matching records">
          No EOAT Atlas records matched this search.
        </EmptyState>
      )}
      {!pending &&
        !error &&
        (searchUsesGlobalIndex ? results : browseResults).length > 0 && (
          <div className="result-deck">
            {(searchUsesGlobalIndex ? results : browseResults).map((result) => (
              <ResultCard
                key={`${result.category}-${result.identifier}`}
                result={result}
              />
            ))}
          </div>
        )}
      {!searchUsesGlobalIndex &&
        browsePagination &&
        browsePagination.pages > 1 && (
          <nav className="pagination" aria-label="Catalog pagination">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => update({ page: String(page - 1) })}
            >
              Previous
            </button>
            <span>
              Page {browsePagination.page} of {browsePagination.pages}
            </span>
            <button
              type="button"
              disabled={page >= browsePagination.pages}
              onClick={() => update({ page: String(page + 1) })}
            >
              Next
            </button>
          </nav>
        )}
    </section>
  );
}
