# Import Ambiguity Policy

Review records use stable UUIDs and the statuses `UNRESOLVED`, `DEFERRED`, `RESOLVED`, `NOT_APPLICABLE`, and `REJECTED_WITH_REASON`. Administrator evidence must include a value, reason, identity, and timestamp before a deferred value becomes authoritative.

- Tool Number is never treated as Part Number. The 67 distinct candidates remain deferred.
- Audit dates are not treated as installation/removal dates. All 57 EOAT installation histories remain deferred.
- Multiple audited machines do not establish a lifecycle history. The owner-approved location policy records either proven separate physical units or a cabinet-unspecified `STORED` observed state.
- Missing/ambiguous machines and tools omit only the unsafe relationship; the traceable EOAT/audit is retained.
- `26 - Xqual in 25` is preserved verbatim in raw evidence and normalizes to Machine 26.
- Proven same-day Cleanroom physical duplicates are split into separately identified EOAT masters using the deterministic mapping in `config/eoat_location_normalization.json`.
- `N/A` in the audited machine field means cabinet-unspecified `STORED`; it never creates a cabinet identifier.
- The placeholder Photo Index row is retained as a deferred import row without document/photo creation.
- Unknown does not mean incompatible; absent compatibility evidence remains Unknown.

The authoritative review artifacts are `reports/mysql_import/import_review_items.json`, `.csv`, and `import_review_summary.md`.

