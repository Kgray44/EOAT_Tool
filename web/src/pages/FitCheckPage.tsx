import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { apiClient } from "@/api/client";
import { ErrorState, LoadingState } from "@/components/feedback/StateViews";
import {
  readFitCheckRecents,
  rememberFitCheck,
  type BrowserFitCheckRecent,
} from "@/app/fitCheckRecents";

type EntityKind = "machine" | "tool" | "eoat";
type EntitySlot = { kind: EntityKind; value: string };

const ENTITY_KINDS: Array<{ kind: EntityKind; label: string }> = [
  { kind: "machine", label: "Machine" },
  { kind: "tool", label: "Tool" },
  { kind: "eoat", label: "EOAT" },
];

function slotsFromValues(
  machine: string,
  tool: string,
  eoat: string,
): EntitySlot[] {
  return [
    { kind: "machine", value: machine },
    { kind: "tool", value: tool },
    { kind: "eoat", value: eoat },
  ];
}

function slotValues(slots: EntitySlot[]) {
  return ENTITY_KINDS.reduce(
    (values, { kind }) => {
      const matching = slots.filter((slot) => slot.kind === kind);
      values[kind] = matching.length === 1 ? matching[0].value : "";
      return values;
    },
    { machine: "", tool: "", eoat: "" } as Record<EntityKind, string>,
  );
}

function resultLabel(value: string) {
  return value === "INVALID_INPUT"
    ? "Insufficient data / unresolved input"
    : value.replaceAll("_", " ");
}

export function FitCheckPage() {
  const [params] = useSearchParams();
  const [slots, setSlots] = useState<EntitySlot[]>(() =>
    slotsFromValues(
      params.get("machine") || "",
      params.get("tool") || "",
      params.get("eoat") || "",
    ),
  );
  const [plantCode, setPlantCode] = useState(params.get("plant") || "");
  const [lastChanged, setLastChanged] = useState<EntityKind | null>(null);
  const { machine, tool, eoat } = slotValues(slots);
  const [selectionOrder, setSelectionOrder] = useState<string[]>(() =>
    [
      params.get("machine") && "Machine",
      params.get("tool") && "Tool",
      params.get("eoat") && "EOAT",
    ].filter((value): value is string => Boolean(value)),
  );
  const [recents, setRecents] = useState<BrowserFitCheckRecent[]>(() =>
    readFitCheckRecents(),
  );
  const options = useQuery({
    queryKey: ["fit-check", "options", plantCode, machine, tool, eoat],
    queryFn: () =>
      apiClient.getWebFitCheckOptions({
        plant_code: plantCode || undefined,
        machine_number: machine || undefined,
        tool_number: tool || undefined,
        eoat_identifier: eoat || undefined,
      }),
  });
  useEffect(() => {
    if (!options.data) return;
    const unresolved = new Set(options.data.unresolved_inputs ?? []);
    const invalid = {
      machine:
        Boolean(machine) &&
        !unresolved.has("machine") &&
        !(options.data.machines ?? []).some(
          (item) => item.identifier === machine,
        ),
      tool:
        Boolean(tool) &&
        !unresolved.has("tool") &&
        !(options.data.tools ?? []).some((item) => item.identifier === tool),
      eoat:
        Boolean(eoat) &&
        !unresolved.has("eoat") &&
        !(options.data.eoats ?? []).some((item) => item.identifier === eoat),
    };
    // Keep the latest typed value visible so an incompatible choice can be explained;
    // discard only earlier selections made invalid by a subsequent valid selection.
    if (invalid.machine && lastChanged !== "machine") clearKind("machine");
    if (invalid.tool && lastChanged !== "tool") clearKind("tool");
    if (invalid.eoat && lastChanged !== "eoat") clearKind("eoat");
  }, [eoat, lastChanged, machine, options.data, tool]);
  const evaluation = useMutation({
    mutationFn: () =>
      apiClient.evaluateWebFitCheck({
        machine_number: machine,
        plant_code: plantCode || undefined,
        tool_number: tool,
        eoat_identifier: eoat,
      }),
    onSuccess: (response) => {
      setRecents(
        rememberFitCheck({
          machine,
          tool,
          eoat,
          result: response.overall_result,
        }),
      );
    },
  });
  const result = evaluation.data;
  const updateSlot = (index: number, update: Partial<EntitySlot>) => {
    setSlots((current) =>
      current.map((slot, currentIndex) =>
        currentIndex === index ? { ...slot, ...update } : slot,
      ),
    );
  };
  const clearKind = (kind: EntityKind) => {
    setSlots((current) =>
      current.map((slot) =>
        slot.kind === kind ? { ...slot, value: "" } : slot,
      ),
    );
  };
  const recordSelection = (kind: EntityKind, value: string) => {
    if (!value.trim()) return;
    const label =
      ENTITY_KINDS.find((item) => item.kind === kind)?.label || kind;
    setSelectionOrder((current) =>
      current.includes(label) ? current : [...current, label],
    );
  };
  const orderedSelections = ["Machine", "Tool", "EOAT"].sort((left, right) => {
    const leftIndex = selectionOrder.indexOf(left);
    const rightIndex = selectionOrder.indexOf(right);
    return (
      (leftIndex < 0 ? 99 : leftIndex) - (rightIndex < 0 ? 99 : rightIndex)
    );
  });
  return (
    <section className="fit-check-page">
      <p className="eyebrow">Compatibility</p>
      <h2>Fit Check</h2>
      <p className="lede">
        This evaluation uses EOAT Atlas compatibility rules and never stores a
        Fit Check, assignment, audit record, or history event.
      </p>
      <form
        className="fit-check-form"
        onSubmit={(event) => {
          event.preventDefault();
          evaluation.mutate();
        }}
      >
        {slots.map((slot, index) => {
          const label =
            ENTITY_KINDS.find((item) => item.kind === slot.kind)?.label ||
            "Entity";
          const listId = `fit-${slot.kind}-slot-${index + 1}`;
          const choices =
            slot.kind === "machine"
              ? (options.data?.machines ?? [])
              : slot.kind === "tool"
                ? (options.data?.tools ?? [])
                : (options.data?.eoats ?? []);
          return (
            <fieldset className="fit-check-slot" key={`slot-${index + 1}`}>
              <legend>Entity slot {index + 1}</legend>
              <label>
                Type
                <select
                  aria-label={`Entity slot ${index + 1} type`}
                  value={slot.kind}
                  onChange={(event) => {
                    const kind = event.target.value as EntityKind;
                    updateSlot(index, { kind, value: "" });
                    setLastChanged(kind);
                    setSelectionOrder((current) =>
                      current.filter(
                        (selected) =>
                          selected !==
                          (ENTITY_KINDS.find((item) => item.kind === slot.kind)
                            ?.label || slot.kind),
                      ),
                    );
                  }}
                >
                  {ENTITY_KINDS.map((item) => (
                    <option key={item.kind} value={item.kind}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {label}
                <input
                  aria-label={label}
                  list={listId}
                  value={slot.value}
                  onChange={(event) => {
                    updateSlot(index, { value: event.target.value });
                    setLastChanged(slot.kind);
                    recordSelection(slot.kind, event.target.value);
                  }}
                />
                <datalist id={listId}>
                  {choices.map((item) => (
                    <option
                      key={`${slot.kind}-${item.plant_code || ""}-${item.identifier}`}
                      value={item.identifier}
                    >
                      {item.plant_code
                        ? `${item.label} (${item.plant_code})`
                        : item.label}
                    </option>
                  ))}
                </datalist>
              </label>
            </fieldset>
          );
        })}
        <label>
          Plant code{" "}
          <span className="optional">
            (only when the selected machine number is shared)
          </span>
          <input
            aria-label="Plant code"
            value={plantCode}
            onChange={(event) => setPlantCode(event.target.value)}
          />
        </label>
        <button
          type="submit"
          disabled={evaluation.isPending || !machine || !tool || !eoat}
        >
          Evaluate without saving
        </button>
        <button
          type="button"
          className="fit-check-secondary"
          onClick={() => {
            setPlantCode("");
            setSlots(slotsFromValues("", "", ""));
            setLastChanged(null);
            setSelectionOrder([]);
            evaluation.reset();
          }}
        >
          Clear
        </button>
      </form>
      {options.isPending && (
        <p className="notes">Loading compatible options…</p>
      )}
      {options.isError && <ErrorState error={options.error} />}
      {(options.data?.warnings ?? []).length ? (
        <section className="fit-option-warnings" aria-live="polite">
          <h3>Selection guidance</h3>
          <p>{options.data?.warnings?.join(" ")}</p>
        </section>
      ) : null}
      <section
        className="fit-selection-flow"
        aria-label="Selected fit check setup"
      >
        {orderedSelections.map((label) => {
          const value =
            label === "Machine"
              ? machine || "Choose a machine"
              : label === "Tool"
                ? tool || "Choose a tool"
                : eoat || "Choose an EOAT";
          return (
            <div key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          );
        })}
      </section>
      {evaluation.isPending && (
        <LoadingState label="Evaluating authoritative compatibility…" />
      )}
      {evaluation.isError && <ErrorState error={evaluation.error} />}
      {result && (
        <section className="fit-result" aria-live="polite">
          <header className="fit-result__headline">
            <span>Match result</span>
            <h3>{resultLabel(result.overall_result)}</h3>
            <p>
              {result.reasons.join(" ") ||
                "EOAT Atlas did not provide a conclusive recommendation."}
            </p>
          </header>
          <dl className="attribute-grid">
            {[
              result.machine_tool_result,
              result.machine_eoat_result,
              result.tool_eoat_result,
            ].map((pair) => (
              <div key={pair.pair}>
                <dt>{pair.pair}</dt>
                <dd>
                  {resultLabel(pair.result)}
                  <br />
                  <small>{pair.reason}</small>
                </dd>
              </div>
            ))}
          </dl>
          <section className="fit-result__warnings">
            <h4>Warnings and requirements</h4>
            {result.warnings.length > 0 ? (
              <p>{result.warnings.join(" ")}</p>
            ) : (
              <p>No setup warnings from the authoritative evaluation.</p>
            )}
            {result.unknown_relationships.length > 0 && (
              <p>
                <strong>Unknown / insufficient:</strong>{" "}
                {result.unknown_relationships.join(", ")}
              </p>
            )}
          </section>
          <section className="fit-result__alternatives">
            <h4>Alternative options</h4>
            <p>
              {result.alternative_compatible_eoats.length > 0
                ? result.alternative_compatible_eoats.join(", ")
                : "No alternative EOAT is required for this result."}
            </p>
          </section>
        </section>
      )}
      <section
        className="fit-check-recents"
        aria-labelledby="recent-fit-checks"
      >
        <h3 id="recent-fit-checks">Recent Fit Checks</h3>
        <p className="notes">
          Stored only in this browser. This list never creates API history.
        </p>
        {recents.length === 0 ? (
          <p>No recent Fit Checks yet.</p>
        ) : (
          <ul>
            {recents.map((recent) => (
              <li key={`${recent.evaluatedAt}-${recent.machine}`}>
                <button
                  type="button"
                  onClick={() => {
                    setPlantCode("");
                    setSlots(
                      slotsFromValues(recent.machine, recent.tool, recent.eoat),
                    );
                    setLastChanged("eoat");
                    setSelectionOrder(["Machine", "Tool", "EOAT"]);
                    evaluation.reset();
                  }}
                >
                  <strong>{resultLabel(recent.result)}</strong>
                  <span>
                    Machine {recent.machine} · Tool {recent.tool} · EOAT{" "}
                    {recent.eoat}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}
