# Audit Workflow Safety

Date: 2026-05-27

Phase: 2 - Audit Workflow Stabilization

## Dirty Form Protection

The Audit page tracks a baseline snapshot of audit form values after:

- New form reset.
- Existing audit load.
- Duplicate audit creation.
- Successful save, through the post-save reset.

If the current form differs from the baseline, the page treats it as dirty. Loading another audit, clearing the form, or navigating away through the page lifecycle prompts the user to save a local draft, discard changes, or cancel.

## Local Draft Recovery

Audit drafts are project-local output files, not repo files.

Storage:

`00_Project_Admin/cache/audit_drafts/latest_audit_draft.json`

Draft payload:

- `version`
- `saved_at`
- `project_root`
- `audit_id`
- `mode`
- `form_values`
- `baseline_values`

The project `cache` folder is ignored by Git and the repo safety rules. Drafts can be saved manually from the Audit page or from the unsaved-changes warning. The Audit page checks for a draft on page open and offers restore, discard, or later.

## Compatibility Impact Preview

When an existing physical source audit is edited and linked compatible rows point to it, the Audit page previews the impact before saving.

The preview includes:

- Source audit ID.
- Number of linked compatible rows.
- Fields likely to propagate.
- Whether compatibility auto-run will execute.
- Whether press views may refresh.

The current save architecture updates source audit data and linked compatible rows together, so the preview offers save-and-update or cancel.

## Audit History

Audit save history is written as project-local JSONL:

`00_Project_Admin/history/audit_history.jsonl`

Each record includes:

- Timestamp.
- Audit ID.
- Event type.
- Changed fields.
- Old values.
- New values.
- Source.
- Files modified when available.

This file is local project output and should not be committed.

## Robot Info Boundary

Phase 2 preserves the existing `Robot_Info.xlsx` behavior. It remains a small side workbook for robot-side circuit counts and basic tracking fields only. The app does not add full robot reference/entity behavior.
