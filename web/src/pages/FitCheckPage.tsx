import { useState } from "react";
import { useMutation, useQueries } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { apiClient } from "@/api/client";
import { ErrorState, LoadingState } from "@/components/feedback/StateViews";

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
  });
  const result = evaluation.data;
  return (
    <section className="fit-check-page">
      <p className="eyebrow">Compatibility</p>
      <h2>Read-only Fit Check</h2>
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
      </form>
      {evaluation.isPending && (
        <LoadingState label="Evaluating authoritative compatibility…" />
      )}
      {evaluation.isError && <ErrorState error={evaluation.error} />}
      {result && (
        <section className="fit-result" aria-live="polite">
          <h3>{resultLabel(result.overall_result)}</h3>
          <p>
            {result.reasons.join(" ") ||
              "EOAT Atlas did not provide a conclusive recommendation."}
          </p>
          {result.warnings.length > 0 && (
            <p>
              <strong>Warnings:</strong> {result.warnings.join(" ")}
            </p>
          )}
          {result.unknown_relationships.length > 0 && (
            <p>
              <strong>Unknown / insufficient:</strong>{" "}
              {result.unknown_relationships.join(", ")}
            </p>
          )}
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
          {result.alternative_compatible_eoats.length > 0 && (
            <p>
              <strong>Alternative compatible EOATs:</strong>{" "}
              {result.alternative_compatible_eoats.join(", ")}
            </p>
          )}
        </section>
      )}
    </section>
  );
}
