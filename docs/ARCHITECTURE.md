# Architecture

EOAT Command Center is organized as a local-first desktop app with separable tools.

```text
Standalone tools
    -> shared core data layer
    -> PySide6 dashboard
    -> reports, workbooks, charts, and final handoff
```

## Layers

`core/` contains reusable business logic: config, paths, safe file handling, validation, Git helpers, schema loading, report writing, logging, and registry metadata.

`app/` contains PySide6 UI code only. Button handlers call `core/` functions instead of embedding project logic in the UI.

`tools/` is reserved for importable wrappers around standalone command-line tools.

`data_templates/` stores JSON templates and seed metadata used by core modules.

Existing scripts remain independently runnable.

## Phase 4 Pattern

The Phase 4 standardization/reporting tools follow the same three-entry architecture:

- CLI wrappers in `tools/`
- importable functions in `core/`
- dashboard actions/pages in `app/pages/`

They are read-only for the master workbook by default. Their normal side effects are timestamped reports/checklists under the project folders and JSONL activity log entries under `00_Project_Admin/Activity_Logs`.

## Phase 5 Pattern

The final presentation and handoff tools collect evidence from existing project outputs. They create timestamped packages under `06_Final_Handoff`, copy files instead of moving them, and report missing data directly instead of fabricating final outcomes.
