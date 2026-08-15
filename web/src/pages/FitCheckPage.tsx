import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { apiClient } from "@/api/client";
import { AtlasSelector } from "@/components/inputs/AtlasSelector";
import { ErrorState, LoadingState } from "@/components/feedback/StateViews";

function resultLabel(value: string) {
  return value === "INVALID_INPUT"
    ? "Insufficient data / unresolved input"
    : value.replaceAll("_", " ");
}
function resultTone(value: string) {
  if (value === "COMPATIBLE") return "success";
  if (value === "WARNING") return "warning";
  if (value === "INVALID_INPUT" || value === "NOT_EVALUATED") return "neutral";
  return "danger";
}

/** The desktop workflow is three named records, never three interchangeable slots. */
export function FitCheckPage() {
  const [params] = useSearchParams();
  const [machine, setMachine] = useState(params.get("machine") || "");
  const [tool, setTool] = useState(params.get("tool") || "");
  const [eoat, setEoat] = useState(params.get("eoat") || "");
  const [plantCode, setPlantCode] = useState(params.get("plant") || "");
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
  const evaluation = useMutation({
    mutationFn: () =>
      apiClient.evaluateWebFitCheck({
        machine_number: machine,
        plant_code: plantCode || undefined,
        tool_number: tool,
        eoat_identifier: eoat,
      }),
  });
  useEffect(() => {
    if (!options.data) return;
    const unresolved = new Set(options.data.unresolved_inputs || []);
    if (
      machine &&
      !unresolved.has("machine") &&
      !(options.data.machines || []).some((item) => item.identifier === machine)
    )
      setMachine("");
    if (
      tool &&
      !unresolved.has("tool") &&
      !(options.data.tools || []).some((item) => item.identifier === tool)
    )
      setTool("");
    if (
      eoat &&
      !unresolved.has("eoat") &&
      !(options.data.eoats || []).some((item) => item.identifier === eoat)
    )
      setEoat("");
  }, [eoat, machine, options.data, tool]);
  const result = evaluation.data;
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
            Choose the actual Machine, Tool, and EOAT for this setup. Plant is
            retained with a selected machine when its number is shared.
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
          onChange={(value, option) => {
            setMachine(value);
            setPlantCode(option?.context?.match(/^Plant ([^ ·]+)/)?.[1] || "");
          }}
        />
        <AtlasSelector
          label="Tool"
          value={tool}
          options={choices(options.data?.tools || [])}
          onChange={setTool}
        />
        <AtlasSelector
          label="EOAT"
          value={eoat}
          options={choices(options.data?.eoats || [])}
          onChange={setEoat}
        />
        <button
          type="submit"
          disabled={evaluation.isPending || !machine || !tool || !eoat}
        >
          Evaluate without saving
        </button>
      </form>
      {options.isPending && (
        <p className="notes">Loading compatible options…</p>
      )}
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
          <header className="fit-result__summary">
            <span
              className={`fit-result__status fit-result__status--${resultTone(result.overall_result)}`}
              aria-hidden="true"
            >
              {result.overall_result === "COMPATIBLE" ? "✓" : "!"}
            </span>
            <div>
              <p className="fit-result__label">Fit Check result</p>
              <h3>{resultLabel(result.overall_result)}</h3>
              <p>
                {result.reasons.join(" ") ||
                  "EOAT Atlas did not provide a conclusive recommendation."}
              </p>
            </div>
            <div className="fit-result__selection">
              <span>Selected EOAT</span>
              <strong>{eoat || "Not selected"}</strong>
              <small>Match: {resultLabel(result.overall_result)}</small>
            </div>
            {result.overall_result === "COMPATIBLE" ? (
              <Link
                className="simple-page-action fit-result__packet-action"
                to={`/setup-packet?${new URLSearchParams({ machine, tool, eoat, ...(plantCode ? { plant: plantCode } : {}) })}`}
              >
                Create packet
              </Link>
            ) : null}
          </header>
          <section className="fit-result__path" aria-label="Evaluated setup">
            <div>
              <span>Machine</span>
              <strong>{machine}</strong>
            </div>
            <div>
              <span>Tool</span>
              <strong>{tool}</strong>
            </div>
            <div>
              <span>EOAT</span>
              <strong>{eoat}</strong>
            </div>
          </section>
          <section className="fit-result__requirements">
            <h4>Requirements check</h4>
            <ul>
              {[
                result.machine_tool_result,
                result.machine_eoat_result,
                result.tool_eoat_result,
              ].map((pair) => (
                <li key={pair.pair}>
                  <span
                    className={`fit-result__dot fit-result__dot--${resultTone(pair.result)}`}
                  />
                  <div>
                    <strong>{pair.pair.replaceAll("_", " to ")}</strong>
                    <small>{pair.reason}</small>
                  </div>
                  <em>{resultLabel(pair.result)}</em>
                </li>
              ))}
            </ul>
          </section>
          <section className="fit-result__warnings">
            <h4>Warnings and requirements</h4>
            <p>
              {result.warnings.length
                ? result.warnings.join(" ")
                : "No setup warnings from the authoritative evaluation."}
            </p>
            {result.unknown_relationships.length ? (
              <p>
                <strong>Unknown / insufficient:</strong>{" "}
                {result.unknown_relationships.join(", ")}
              </p>
            ) : null}
          </section>
        </section>
      ) : null}
    </section>
  );
}
