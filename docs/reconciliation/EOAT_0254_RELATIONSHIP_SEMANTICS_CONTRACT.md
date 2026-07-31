# EOAT Atlas 0.25.4 relationship semantics contract

## Browser display contract

Profile relationship cards use the shared `presentRelationship` mapping. The
primary label describes relationship meaning, while evidence is disclosed only
through the expandable **Evidence details** control.

| Source condition | Primary browser label | Meaning |
| --- | --- | --- |
| Current/assigned/installed | Current assignment | A present assignment is recorded. It is not a compatibility claim. |
| Compatible/verified | Verified compatibility | Compatibility is explicitly recorded. |
| Incompatible/not compatible | Incompatible | An explicit negative result never becomes verified compatibility. |
| Inferred | Inferred compatibility | It is a useful inference, not verification. |
| Observation/historical event | Historical observation | Historical evidence never becomes a current assignment. |
| Unverified/review required | Unverified assignment | A relationship exists but needs verification. |
| Missing or unrecognized value | Unknown relationship | No compatibility or incompatibility is inferred. |

Raw enums, legacy-source wording, migration reason strings, and provenance
codes are never primary labels. Unknown source data remains unknown; it does
not become an incompatibility. Evidence details intentionally state only what
the browser contract can prove and do not fabricate a source, date, confidence,
or record identifier.

## Coverage

`web/src/components/profile/ProfileBlocks.test.tsx` covers every semantic
state (including explicit incompatibility), an unknown legacy value,
raw-label suppression, and the expandable evidence control. The shared
component is used by EOAT, Machine, and Tool profiles.
