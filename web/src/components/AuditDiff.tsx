import { useState } from "react";

import type { AuditValue } from "../api/admin";

const missing = Symbol("missing");

function valueKind(value: AuditValue | typeof missing): string {
  if (value === missing) return "Missing";
  if (value === null) return "Null";
  if (value === "") return "Blank";
  if (typeof value === "object" && !Array.isArray(value) && value && value._audit_value === "REDACTED") return "Redacted";
  return "Value";
}

function compactValue(value: AuditValue | typeof missing): string {
  if (value === missing) return "Not recorded";
  if (value === null) return "Null";
  if (value === "") return "Blank";
  if (typeof value === "object" && !Array.isArray(value) && value && value._audit_value === "REDACTED") return "Redacted";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function AuditValueCell({ value }: { value: AuditValue | typeof missing }) {
  const [expanded, setExpanded] = useState(false);
  const serialized = compactValue(value);
  const canExpand = serialized.length > 180 || typeof value === "object";
  return (
    <div className="audit-value">
      <span className={`audit-value-kind audit-value-kind-${valueKind(value).toLowerCase()}`}>{valueKind(value)}</span>
      <code className={expanded ? "expanded" : ""}>{expanded ? serialized : serialized.slice(0, 180)}</code>
      {!expanded && serialized.length > 180 ? <span aria-hidden="true">…</span> : null}
      {canExpand ? (
        <button className="link-button" type="button" onClick={() => setExpanded((current) => !current)}>
          {expanded ? "Show less" : "Show full value"}
        </button>
      ) : null}
    </div>
  );
}

export function AuditDiff({
  changedFields,
  before,
  after,
}: {
  changedFields: string[];
  before?: Record<string, AuditValue> | null;
  after?: Record<string, AuditValue> | null;
}) {
  const fields = changedFields.length > 0 ? changedFields : [...new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])].sort();
  if (!fields.length) return <p className="state-note">This event did not record a field-level change.</p>;
  return (
    <div className="diff-table-wrap">
      <table className="diff-table">
        <thead>
          <tr><th scope="col">Field</th><th scope="col">Previous</th><th scope="col">Resulting</th></tr>
        </thead>
        <tbody>
          {fields.map((field) => (
            <tr key={field}>
              <th scope="row"><code>{field}</code></th>
              <td><AuditValueCell value={before && Object.hasOwn(before, field) ? before[field] : missing} /></td>
              <td><AuditValueCell value={after && Object.hasOwn(after, field) ? after[field] : missing} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
