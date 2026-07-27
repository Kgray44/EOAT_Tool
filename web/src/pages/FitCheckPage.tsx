import { useState } from "react";
import { useMutation, useQueries } from "@tanstack/react-query";
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
  const [tool, setTool] = useState(params.get("tool") || "");
  const [eoat, setEoat] = useState(params.get("eoat") || "");
  const [recents, setRecents] = useState<BrowserFitCheckRecent[]>(() =>
    readFitCheckRecents(),
  );
  const [machines, tools, eoats] = useQueries({
    queries: [
      {
        queryKey: ["fit-check", "machines"],
        queryFn: () => apiClient.getMachines(),
      },
      { queryKey: ["fit-check", "tools"], queryFn: () => apiClient.getTools() },
      { queryKey: ["fit-check", "eoats"], queryFn: () => apiClient.getEoats() },
    ],
  });
  const evaluation = useMutation({
    mutationFn: () =>
      apiClient.evaluateWebFitCheck({
        machine_number: machine,
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
            list="fit-machines"
            required
            value={machine}
            onChange={(event) => setMachine(event.target.value)}
          />
          <datalist id="fit-machines">
            {machines.data?.items.map((item) => (
              <option key={item.machine_number} value={item.machine_number}>
                {item.machine_name || item.machine_number}
              </option>
            ))}
          </datalist>
        </label>
        <label>
          Tool
          <input
            list="fit-tools"
            required
            value={tool}
            onChange={(event) => setTool(event.target.value)}
          />
          <datalist id="fit-tools">
            {tools.data?.items.map((item) => (
              <option
                key={item.business_identifier}
                value={item.business_identifier}
              >
                {item.display_name || item.tool_number}
              </option>
            ))}
          </datalist>
        </label>
        <label>
          EOAT
          <input
            list="fit-eoats"
            required
            value={eoat}
            onChange={(event) => setEoat(event.target.value)}
          />
          <datalist id="fit-eoats">
            {eoats.data?.items.map((item) => (
              <option
                key={item.business_identifier}
                value={item.business_identifier}
              >
                {item.display_name || item.business_identifier}
              </option>
            ))}
          </datalist>
        </label>
        <button type="submit" disabled={evaluation.isPending}>
          Evaluate without saving
        </button>
        <button
          type="button"
          className="fit-check-secondary"
          onClick={() => {
            setMachine("");
            setTool("");
            setEoat("");
            evaluation.reset();
          }}
        >
          Clear
        </button>
      </form>
      <section
        className="fit-selection-flow"
        aria-label="Selected fit check setup"
      >
        {[
          ["Tool", tool || "Choose a tool"],
          ["Machine", machine || "Choose a machine"],
          ["EOAT", eoat || "Choose an EOAT"],
        ].map(([label, value]) => (
          <div key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
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
                    setTool(recent.tool);
                    setEoat(recent.eoat);
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
