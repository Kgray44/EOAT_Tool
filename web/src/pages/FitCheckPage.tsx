import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import {
  apiClient,
  type FitCheckResult,
  type FitCheckSearchSlot,
} from "@/api/client";
import { AtlasSelector } from "@/components/inputs/AtlasSelector";
import { ErrorState, LoadingState } from "@/components/feedback/StateViews";

type DisplayTone = "success" | "warning" | "danger" | "neutral";

function resultLabel(value: string) {
  return value === "INVALID_INPUT"
    ? "Insufficient data / unresolved input"
    : value.replaceAll("_", " ");
}

function resultTone(value: string): DisplayTone {
  if (value === "COMPATIBLE") return "success";
  if (value === "NEEDS_REVIEW" || value === "WARNING" || value === "UNKNOWN")
    return "warning";
  if (value === "INVALID_INPUT" || value === "NOT_EVALUATED") return "neutral";
  return "danger";
}

function resultIcon(value: string) {
  if (value === "COMPATIBLE") return "✓";
  if (value === "INCOMPATIBLE") return "×";
  return "?";
}

function compactText(value: string, max = 28) {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

function FitCheckDiagram({
  result,
  fallback,
}: {
  result: FitCheckResult;
  fallback: { machine: string; tool: string; eoat: string };
}) {
  const selected = result.selected_entities || [];
  const nodes = [
    selected.find((item) => item.entity_type === "machine") || {
      entity_type: "machine" as const,
      identifier: fallback.machine,
      label: fallback.machine,
      secondary: null,
    },
    selected.find((item) => item.entity_type === "tool") || {
      entity_type: "tool" as const,
      identifier: fallback.tool,
      label: fallback.tool,
      secondary: null,
    },
    selected.find((item) => item.entity_type === "eoat") || {
      entity_type: "eoat" as const,
      identifier: fallback.eoat,
      label: fallback.eoat,
      secondary: null,
    },
  ];
  const edges = [
    {
      pair: result.machine_tool_result,
      label: "Machine ↔ Tool",
      line: [360, 125, 840, 125],
      marker: [600, 125],
    },
    {
      pair: result.machine_eoat_result,
      label: "Machine ↔ EOAT",
      line: [285, 205, 525, 345],
      marker: [405, 275],
    },
    {
      pair: result.tool_eoat_result,
      label: "Tool ↔ EOAT",
      line: [915, 205, 675, 345],
      marker: [795, 275],
    },
  ];
  const positions = [
    [60, 40],
    [840, 40],
    [450, 320],
  ];
  return (
    <section
      className="fit-result__diagram"
      aria-labelledby="fit-relationship-title"
    >
      <div className="fit-result__section-heading">
        <div>
          <p className="fit-result__label">Relationship model</p>
          <h4 id="fit-relationship-title">Selected setup</h4>
        </div>
        <p>Each connection shows its own authoritative result.</p>
      </div>
      <div className="fit-result__diagram-scroll">
        <svg
          className="fit-result__diagram-canvas"
          viewBox="0 0 1200 500"
          role="img"
          aria-label={edges
            .map((edge) => `${edge.label}: ${resultLabel(edge.pair.result)}`)
            .join(". ")}
        >
          {edges.map((edge) => {
            const tone = resultTone(edge.pair.result);
            return (
              <g
                key={edge.pair.pair}
                className={`fit-result__edge fit-result__edge--${tone}`}
              >
                <title>{`${edge.label}: ${resultLabel(edge.pair.result)}. ${edge.pair.reason}`}</title>
                <line
                  x1={edge.line[0]}
                  y1={edge.line[1]}
                  x2={edge.line[2]}
                  y2={edge.line[3]}
                />
                <circle cx={edge.marker[0]} cy={edge.marker[1]} r="24" />
                <text
                  x={edge.marker[0]}
                  y={edge.marker[1] + 8}
                  textAnchor="middle"
                >
                  {resultIcon(edge.pair.result)}
                </text>
              </g>
            );
          })}
          {nodes.map((node, index) => {
            const [x, y] = positions[index];
            return (
              <g
                className="fit-result__node"
                key={node.entity_type}
                transform={`translate(${x} ${y})`}
              >
                <rect width="300" height="140" rx="15" />
                <text className="fit-result__node-type" x="24" y="34">
                  {node.entity_type.toUpperCase()}
                </text>
                <text className="fit-result__node-id" x="24" y="68">
                  {compactText(node.identifier)}
                </text>
                <text className="fit-result__node-label" x="24" y="96">
                  {compactText(node.label, 34)}
                </text>
                {node.secondary ? (
                  <text className="fit-result__node-secondary" x="24" y="121">
                    {compactText(node.secondary, 42)}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
      </div>
      <ul className="fit-result__edge-legend" aria-label="Relationship results">
        {edges.map((edge) => {
          const tone = resultTone(edge.pair.result);
          return (
            <li
              key={edge.pair.pair}
              className={`fit-result__edge-legend-item--${tone}`}
            >
              <span aria-hidden="true">{resultIcon(edge.pair.result)}</span>
              <div>
                <strong>{edge.label}</strong>
                <small>{edge.pair.reason}</small>
              </div>
              <em>{resultLabel(edge.pair.result)}</em>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** The desktop workflow is three named records, never three interchangeable slots. */
export function FitCheckPage() {
  const [params] = useSearchParams();
  const [machine, setMachine] = useState(params.get("machine") || "");
  const [tool, setTool] = useState(params.get("tool") || "");
  const [eoat, setEoat] = useState(params.get("eoat") || "");
  const [plantCode, setPlantCode] = useState(params.get("plant") || "");
  const [selectorQueries, setSelectorQueries] = useState<
    Record<FitCheckSearchSlot, string>
  >({ machine: "", tool: "", eoat: "" });
  const activeSearch = (
    Object.entries(selectorQueries) as Array<[FitCheckSearchSlot, string]>
  ).find(([, query]) => query.trim());
  const catalogSearch = activeSearch?.[1].trim() || "";
  const catalogSearchSlot = catalogSearch ? activeSearch?.[0] : undefined;
  const options = useQuery({
    queryKey: [
      "fit-check",
      "options",
      plantCode,
      machine,
      tool,
      eoat,
      catalogSearchSlot,
      catalogSearch,
    ],
    queryFn: () =>
      apiClient.getWebFitCheckOptions({
        plant_code: plantCode || undefined,
        machine_number: machine || undefined,
        tool_number: tool || undefined,
        eoat_identifier: eoat || undefined,
        search: catalogSearch || undefined,
        search_slot: catalogSearchSlot,
      }),
  });
  const evaluation = useMutation({
    mutationFn: () =>
      apiClient.evaluateWebFitCheck({
        machine_number: machine,
        plant_code: plantCode || undefined,
        tool_number: tool,
        eoat_identifier: eoat,
      }),
  });
  const result = evaluation.data;
  const setSelectorQuery = (slot: FitCheckSearchSlot, query: string) =>
    setSelectorQueries({ machine: "", tool: "", eoat: "", [slot]: query });
  const choices = (
    items: Array<{
      identifier: string;
      label: string;
      plant_code?: string | null;
    }>,
  ) =>
    items.map((item) => ({
      value: item.identifier,
      label: item.plant_code
        ? `${item.label} · ${item.plant_code}`
        : item.label,
      context: item.plant_code
        ? `Plant ${item.plant_code} · ${item.identifier}`
        : item.identifier,
    }));
  const applyAlternative = (
    entityType: "machine" | "eoat",
    identifier: string,
  ) => {
    if (entityType === "machine") setMachine(identifier);
    else setEoat(identifier);
    evaluation.reset();
    setSelectorQuery(entityType, "");
  };

  return (
    <section className="fit-check-page">
      <p className="eyebrow">Compatibility</p>
      <h2>Fit Check</h2>
      <p className="lede">
        Evaluate a Machine, Tool, and EOAT using the authoritative Atlas
        compatibility rules. The evaluation does not create a record.
      </p>
      <form
        className="fit-check-form"
        onSubmit={(event) => {
          event.preventDefault();
          evaluation.mutate();
        }}
      >
        <div className="fit-check-input-hint">
          <span>
            Choose the actual Machine, Tool, and EOAT for this setup. Empty
            fields show compatible recommendations; typing searches the full
            catalog so an unfamiliar combination can be evaluated.
          </span>
          <button
            type="button"
            className="fit-check-secondary"
            onClick={() => {
              setMachine("");
              setTool("");
              setEoat("");
              setPlantCode("");
              evaluation.reset();
            }}
          >
            Clear
          </button>
        </div>
        <AtlasSelector
          label="Machine"
          value={machine}
          options={choices(options.data?.machines || [])}
          searchQuery={selectorQueries.machine}
          onSearchQueryChange={(query) => setSelectorQuery("machine", query)}
          onChange={(value, option) => {
            setMachine(value);
            setPlantCode(option?.context?.match(/^Plant ([^ ·]+)/)?.[1] || "");
            setSelectorQuery("machine", "");
          }}
        />
        <AtlasSelector
          label="Tool"
          value={tool}
          options={choices(options.data?.tools || [])}
          searchQuery={selectorQueries.tool}
          onSearchQueryChange={(query) => setSelectorQuery("tool", query)}
          onChange={(value) => {
            setTool(value);
            setSelectorQuery("tool", "");
          }}
        />
        <AtlasSelector
          label="EOAT"
          value={eoat}
          options={choices(options.data?.eoats || [])}
          searchQuery={selectorQueries.eoat}
          onSearchQueryChange={(query) => setSelectorQuery("eoat", query)}
          onChange={(value) => {
            setEoat(value);
            setSelectorQuery("eoat", "");
          }}
        />
        <button
          type="submit"
          disabled={evaluation.isPending || !machine || !tool || !eoat}
        >
          Evaluate without saving
        </button>
      </form>
      {options.isPending && (
        <p className="notes">
          {catalogSearch
            ? "Searching the entire catalog…"
            : "Loading compatibility recommendations…"}
        </p>
      )}
      {options.data?.query_mode === "global_catalog" ? (
        <p className="notes">
          Showing global catalog results for the typed search.
        </p>
      ) : null}
      {options.isError && <ErrorState error={options.error} />}
      {(options.data?.warnings || []).length ? (
        <section className="fit-option-warnings" aria-live="polite">
          <h3>Selection guidance</h3>
          <p>{options.data?.warnings?.join(" ")}</p>
        </section>
      ) : null}
      {evaluation.isPending && (
        <LoadingState label="Evaluating authoritative compatibility…" />
      )}
      {evaluation.isError && <ErrorState error={evaluation.error} />}
      {result ? (
        <section className="fit-result" aria-live="polite">
          <header
            className={`fit-result__summary fit-result__summary--${resultTone(result.overall_result)}`}
          >
            <span
              className={`fit-result__status fit-result__status--${resultTone(result.overall_result)}`}
              aria-hidden="true"
            >
              {resultIcon(result.overall_result)}
            </span>
            <div>
              <p className="fit-result__label">Fit Check result</p>
              <h3>{resultLabel(result.overall_result)}</h3>
              <p>
                {result.decision_summary ||
                  result.reasons.join(" ") ||
                  "EOAT Atlas did not provide a conclusive recommendation."}
              </p>
            </div>
            <div className="fit-result__selection">
              <span>Decision confidence</span>
              <strong>
                {result.confidence ? resultLabel(result.confidence) : "Unknown"}
              </strong>
              <small>
                Compatibility logic and evidence are evaluated by EOAT Atlas.
              </small>
            </div>
            {result.setup_packet_available ||
            result.overall_result === "COMPATIBLE" ? (
              <Link
                className="simple-page-action fit-result__packet-action"
                to={`/setup-packet?${new URLSearchParams({ machine, tool, eoat, ...(plantCode ? { plant: plantCode } : {}) })}`}
              >
                Create packet
              </Link>
            ) : null}
          </header>
          <FitCheckDiagram result={result} fallback={{ machine, tool, eoat }} />
          <section className="fit-result__requirements">
            <div className="fit-result__section-heading">
              <div>
                <p className="fit-result__label">
                  Desktop-equivalent checklist
                </p>
                <h4>Requirements check</h4>
              </div>
              <p>Every result is returned by the compatibility service.</p>
            </div>
            <ul>
              {(result.requirements || []).map((requirement) => {
                const tone = resultTone(requirement.result);
                return (
                  <li
                    key={requirement.code}
                    className={`fit-result__requirement--${tone}`}
                  >
                    <span
                      className="fit-result__criterion-icon"
                      aria-hidden="true"
                    >
                      {resultIcon(requirement.result)}
                    </span>
                    <div>
                      <strong>{requirement.label}</strong>
                      <small>{requirement.reason}</small>
                      {requirement.evidence_source ? (
                        <i>{requirement.evidence_source}</i>
                      ) : null}
                    </div>
                    <em>{resultLabel(requirement.result)}</em>
                  </li>
                );
              })}
              {!(result.requirements || []).length ? (
                <li className="fit-result__requirement--neutral">
                  <span
                    className="fit-result__criterion-icon"
                    aria-hidden="true"
                  >
                    ?
                  </span>
                  <div>
                    <strong>Detailed requirements unavailable</strong>
                    <small>The server did not return checklist evidence.</small>
                  </div>
                  <em>Needs review</em>
                </li>
              ) : null}
            </ul>
          </section>
          <section className="fit-result__warnings">
            <h4>Warnings and requirements</h4>
            {(result.structured_warnings || []).length ? (
              <ul>
                {result.structured_warnings?.map((warning, index) => (
                  <li
                    key={`${warning.title}-${index}`}
                    className={`fit-result__warning--${warning.severity}`}
                  >
                    <strong>{warning.title}</strong>
                    <span>{warning.message}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p>No setup warnings from the authoritative evaluation.</p>
            )}
          </section>
          <section className="fit-result__alternatives">
            <h4>Alternatives</h4>
            {result.recommended_eoat ? (
              <p className="fit-result__recommended">
                Recommended EOAT:{" "}
                <strong>{result.recommended_eoat.entity.identifier}</strong>
              </p>
            ) : null}
            <div className="fit-result__alternative-columns">
              <AlternativeList
                heading="Other Machines"
                items={result.alternative_machines || []}
                onUse={(item) =>
                  applyAlternative("machine", item.entity.identifier)
                }
              />
              <AlternativeList
                heading="Other EOATs"
                items={result.alternative_eoats || []}
                onUse={(item) =>
                  applyAlternative("eoat", item.entity.identifier)
                }
              />
            </div>
          </section>
          {(result.detail_sections || []).length ? (
            <section className="fit-result__details">
              <h4>Detailed evidence</h4>
              <div>
                {result.detail_sections?.map((section) => (
                  <article key={section.title}>
                    <h5>{section.title}</h5>
                    <ul>
                      {section.entries?.map((entry) => (
                        <li key={entry}>{entry}</li>
                      ))}
                    </ul>
                  </article>
                ))}
              </div>
            </section>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}

function AlternativeList({
  heading,
  items,
  onUse,
}: {
  heading: string;
  items: NonNullable<FitCheckResult["alternative_eoats"]>;
  onUse: (
    item: NonNullable<FitCheckResult["alternative_eoats"]>[number],
  ) => void;
}) {
  return (
    <section>
      <h5>{heading}</h5>
      {items.length ? (
        <ul>
          {items.map((item) => (
            <li key={item.entity.identifier}>
              <div>
                <strong>{item.entity.identifier}</strong>
                <span>
                  {item.entity.label}
                  {item.entity.secondary ? ` · ${item.entity.secondary}` : ""}
                </span>
                <small>{item.reason}</small>
              </div>
              <span
                className={`fit-result__alternative-status fit-result__alternative-status--${item.status}`}
              >
                {item.status_label}
              </span>
              <button
                type="button"
                className="fit-check-secondary"
                onClick={() => onUse(item)}
              >
                Use
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p>
          No alternative compatible choices are recorded for this selected
          setup.
        </p>
      )}
    </section>
  );
}
