import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { apiClient } from "@/api/client";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "@/components/feedback/StateViews";

type PacketRecord = Record<string, unknown>;

const PACKET_FIELDS: Record<string, Array<[string, string]>> = {
  Machine: [
    ["Machine number", "machine_number"],
    ["Name", "machine_name"],
    ["Plant", "plant_code"],
    ["Area", "area"],
    ["Manufacturer", "manufacturer"],
    ["Model", "model"],
    ["Controller", "controller_type"],
    ["Press capacity", "press_capacity_tons"],
    ["Current EOAT", "current_eoat"],
  ],
  Tool: [
    ["Tool number", "tool_number"],
    ["Identifier", "business_identifier"],
    ["Name", "display_name"],
    ["Mold number", "mold_number"],
    ["Type", "tool_type"],
    ["Status", "status"],
    ["Description", "description"],
  ],
  EOAT: [
    ["EOAT identifier", "business_identifier"],
    ["Name", "display_name"],
    ["Type", "eoat_type"],
    ["Connection", "connection_type"],
    ["Status", "status"],
    ["Location", "current_location"],
    ["Description", "description"],
  ],
};

function recordFor(value: unknown): PacketRecord {
  return typeof value === "object" && value !== null
    ? (value as PacketRecord)
    : {};
}

function displayedFields(label: string, value: unknown) {
  const record = recordFor(value);
  return (PACKET_FIELDS[label] ?? [])
    .map(([fieldLabel, key]) => [fieldLabel, record[key]] as const)
    .filter(([, fieldValue]) =>
      ["string", "number", "boolean"].includes(typeof fieldValue),
    );
}

export function SetupPacketPage() {
  const [params] = useSearchParams();
  const machine = params.get("machine") || "";
  const tool = params.get("tool") || "";
  const eoat = params.get("eoat") || "";
  const plant = params.get("plant") || undefined;
  const complete = Boolean(machine && tool && eoat);
  const packet = useQuery({
    queryKey: ["setup-packet", machine, tool, eoat, plant],
    enabled: complete,
    queryFn: () =>
      apiClient.getSetupPacketData({
        machine_number: machine,
        tool_number: tool,
        eoat_identifier: eoat,
        plant_code: plant,
      }),
  });

  if (!complete) {
    return (
      <section className="simple-page">
        <header className="simple-page-heading">
          <h1 id="setup-packet-title">Setup Packet</h1>
        </header>
        <EmptyState title="A compatible Fit Check is required">
          Choose one Machine, Tool, and EOAT, then run a compatible Fit Check
          before opening a setup packet.
        </EmptyState>
        <Link className="simple-page-action" to="/fit-check">
          Run Fit Check
        </Link>
      </section>
    );
  }

  return (
    <section className="setup-packet-page" aria-labelledby="setup-packet-title">
      <header className="page-heading">
        <p className="eyebrow">Setup reference</p>
        <h1 id="setup-packet-title">Setup Packet</h1>
        <p className="lede">
          This browser-safe packet is built from the authoritative API response.
          Use your browser’s print dialog to save it as a PDF; it does not write
          a Fit Check, assignment, audit record, or history event.
        </p>
      </header>
      {packet.isPending ? <LoadingState label="Loading setup packet…" /> : null}
      {packet.isError ? <ErrorState error={packet.error} /> : null}
      {packet.data ? (
        <>
          <div className="setup-packet-actions">
            <button type="button" onClick={() => window.print()}>
              Print or save as PDF
            </button>
            <Link
              className="fit-check-secondary"
              to={`/fit-check?${new URLSearchParams({
                machine,
                tool,
                eoat,
                ...(plant ? { plant } : {}),
              })}`}
            >
              Return to Fit Check
            </Link>
          </div>
          <section className="profile-section">
            <h2>Compatibility result</h2>
            <div className="setup-packet-compatibility">
              <strong>
                {packet.data.fit_check.overall_result.replaceAll("_", " ")}
              </strong>
              <p>{packet.data.fit_check.reasons.join(" ")}</p>
            </div>
            <dl className="setup-packet-pairs">
              {[
                packet.data.fit_check.machine_tool_result,
                packet.data.fit_check.machine_eoat_result,
                packet.data.fit_check.tool_eoat_result,
              ].map((pair) => (
                <div key={pair.pair}>
                  <dt>{pair.pair.replaceAll("_", " to ")}</dt>
                  <dd>{pair.result.replaceAll("_", " ")}</dd>
                  <small>{pair.reason}</small>
                </div>
              ))}
            </dl>
          </section>
          {(
            [
              ["Machine", packet.data.machine],
              ["Tool", packet.data.tool],
              ["EOAT", packet.data.eoat],
            ] as Array<[string, unknown]>
          ).map(([label, record]) => (
            <section
              className="profile-section setup-packet-record"
              key={label}
            >
              <h2>{label}</h2>
              <dl className="setup-packet-fields">
                {displayedFields(label, record).map(([fieldLabel, value]) => (
                  <div key={fieldLabel}>
                    <dt>{fieldLabel}</dt>
                    <dd>{String(value)}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
          <p className="notes">
            API source: {packet.data.source}; generated{" "}
            {new Date(packet.data.generated_at).toLocaleString()}.
          </p>
        </>
      ) : null}
    </section>
  );
}
