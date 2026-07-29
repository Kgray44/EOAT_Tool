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

function resultLabel(value: string) {
  return value === "INVALID_INPUT"
    ? "Insufficient data / unresolved input"
    : value.replaceAll("_", " ");
}

export function FitCheckPage() {
  const [params] = useSearchParams();
  const [machine, setMachine] = useState(params.get("machine") || "");
  const [plantCode, setPlantCode] = useState(params.get("plant") || "");
  const [tool, setTool] = useState(params.get("tool") || "");
  const [eoat, setEoat] = useState(params.get("eoat") || "");
  const [lastChanged, setLastChanged] = useState<
    "machine" | "tool" | "eoat" | null
  >(null);
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
    if (invalid.machine && lastChanged !== "machine") setMachine("");
    if (invalid.tool && lastChanged !== "tool") setTool("");
    if (invalid.eoat && lastChanged !== "eoat") setEoat("");
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
  const recordSelection = (label: string, value: string) => {
    if (!value.trim()) return;
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
        <label>
          Machine
          <input
            aria-label="Machine"
            list="fit-machines"
            value={machine}
            onChange={(event) => {
              setMachine(event.target.value);
              setLastChanged("machine");
              recordSelection("Machine", event.target.value);
            }}
          />
          <datalist id="fit-machines">
            {(options.data?.machines ?? []).map((item) => (
              <option
                key={`${item.plant_code}-${item.identifier}`}
                value={item.identifier}
              >
                {item.plant_code
                  ? `${item.label} (${item.plant_code})`
                  : item.label}
              </option>
            ))}
          </datalist>
        </label>
        <label>
          Plant code{" "}
          <span className="optional">
            (only when the machine number is shared)
          </span>
          <input
            aria-label="Plant code"
            value={plantCode}
            onChange={(event) => setPlantCode(event.target.value)}
          />
        </label>
        <label>
          Tool
          <input
            aria-label="Tool"
            list="fit-tools"
            value={tool}
            onChange={(event) => {
              setTool(event.target.value);
              setLastChanged("tool");
              recordSelection("Tool", event.target.value);
            }}
          />
          <datalist id="fit-tools">
            {(options.data?.tools ?? []).map((item) => (
              <option key={item.identifier} value={item.identifier}>
                {item.label}
              </option>
            ))}
          </datalist>
        </label>
        <label>
          EOAT
          <input
            aria-label="EOAT"
            list="fit-eoats"
            value={eoat}
            onChange={(event) => {
              setEoat(event.target.value);
              setLastChanged("eoat");
              recordSelection("EOAT", event.target.value);
            }}
          />
          <datalist id="fit-eoats">
            {(options.data?.eoats ?? []).map((item) => (
              <option key={item.identifier} value={item.identifier}>
                {item.label}
              </option>
            ))}
          </datalist>
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
            setMachine("");
            setPlantCode("");
            setTool("");
            setEoat("");
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
                    setMachine(recent.machine);
                    setPlantCode("");
                    setTool(recent.tool);
                    setEoat(recent.eoat);
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
