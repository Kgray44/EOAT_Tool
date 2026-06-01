# Audit Coach and Guided Completion

Phase 3 adds an Audit Coach panel to the Audit Entry workflow. The coach is a local-first helper for finishing an audit without changing the underlying audit save/load behavior.

## Source of Truth

The coach uses the shared audit applicability rules in `core.audit_field_rules`:

- `field_applies(entry, field_name)`
- `non_applicable_reason(entry, field_name)`
- `entry_type_requirements(entry)`
- `hybrid_completeness_warnings(entry)`
- `semantic_consistency_warnings(entry)`

Do not add separate UI-only applicability rules. If field visibility or completion truth changes, update the shared rule module first and let the coach consume that behavior.

## Core Model

The completion model lives in `core.audit.coach`.

Primary dataclasses:

- `AuditCoachSectionStatus`
- `AuditCoachFinding`
- `AuditCoachSummary`
- `AuditCoachFieldStatus`

Field states:

- `verified_complete`: applicable field has a verified value.
- `missing`: applicable field is blank or marked `N/A`.
- `unknown_not_checked`: applicable field is explicitly `Unknown / Not Checked`; this is not verified complete.
- `not_applicable`: field is non-applicable under shared rules; valid `N/A` does not count as missing.
- `follow_up_needed`: field value explicitly requests follow-up or review.
- `stale_conflict`: field is hidden/non-applicable but still has a meaningful value, or cross-field checks report a conflict.

## Guided Workflow

The Audit Coach panel appears on the right side of the Audit Entry tab. It shows:

- Overall verified completion.
- Section-by-section counts.
- Next best field.
- Findings such as stale hidden values, hybrid warnings, semantic conflicts, and photo evidence gaps.
- Hidden field reasons from `non_applicable_reason`.

`Finish This Audit` walks through actionable fields in this order:

1. Required identity fields.
2. EOAT/tooling fields.
3. Visibility controller fields.
4. Major engineering fields.
5. Sensor, pneumatic, and electrical details.
6. Documentation/photo evidence.
7. Notes/optional fields.

The workflow actions are:

- `Open Field`: switches to the correct section and highlights the field.
- `Mark Unknown / Not Checked`: records the explicit unknown state when the field schema can safely accept it.
- `Create Follow-Up`: creates a local Action Items row and marks `Follow-Up Needed` as `Yes`.
- `Tag Needs Review`: assigns the existing annotation tag to the audit field.
- `Skip` and `Next`: move through the guided list without changing data.

Restricted numeric-count fields are not overwritten with `Unknown / Not Checked`, because current workbook validation and the small `Robot_Info.xlsx` circuit-count workbook require numeric counts.

## Uninstalled EOAT Audits

The audit form infers uninstalled EOAT audit mode when `Tool #` is filled and `Press/Machine #` is blank. In that mode, the shared completion and validation rules ignore `Plant/Area`, `Press/Machine #`, `Robot Type`, and `Robot Model/Controller` so a bench audit is not penalized for missing machine context.

Entering `Tool #` without a machine number looks up the tool in the EOAT Inventory workbook and fills safe tool-owned fields such as `Part Family`, `Part Name/Description`, `EOAT Type`, tooling details, sensor details, and documentation fields when those values are available. Machine, robot, current assignment, status, priority, photo, and compatibility metadata fields are not copied by the tool lookup.

Uninstalled audit saves append `EOAT Not Installed.` to `Notes` once and skip linked machine compatibility creation or propagation by default.

## Safety Notes

- The coach does not implement the full Robot Info entity system.
- `Robot_Info.xlsx` remains limited to robot-side pneumatic circuit counts.
- Hidden non-applicable fields continue to save as `N/A` through the existing audit save workflow.
- No real company data, internal paths, customer names, part numbers, mold numbers, capacity data, downtime data, scrap data, logs, photos, reports, or local configs belong in tests or docs.
