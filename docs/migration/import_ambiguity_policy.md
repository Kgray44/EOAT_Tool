# Import Ambiguity Policy

Review records use stable UUIDs and the statuses `UNRESOLVED`, `DEFERRED`, `RESOLVED`, `NOT_APPLICABLE`, and `REJECTED_WITH_REASON`. Administrator evidence must include a value, reason, identity, and timestamp before a deferred value becomes authoritative.

- Tool Number is never treated as Part Number. The 67 distinct candidates remain deferred.
- Audit dates are not treated as installation/removal dates. All 57 EOAT installation histories remain deferred.
- Multiple audited machines do not establish current location. Current location is returned as Unknown / Not Verified.
- Missing/ambiguous machines and tools omit only the unsafe relationship; the traceable EOAT/audit is retained.
- `26 - Xqual in 25` is preserved verbatim and does not create a machine.
- The two conflicting `CL-EOAT-0052` cleanroom rows remain review items and the normalized field remains null.
- The placeholder Photo Index row is retained as a deferred import row without document/photo creation.
- Unknown does not mean incompatible; absent compatibility evidence remains Unknown.

The authoritative review artifacts are `reports/mysql_import/import_review_items.json`, `.csv`, and `import_review_summary.md`.

