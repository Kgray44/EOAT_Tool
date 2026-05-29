# Feature Expansion Plan

This plan captures the current roadmap shape after the overnight expansion work. New features should continue to prioritize app stability, local-first operation, and safe handling of project files.

## Current Foundation

- Audit field registry and completion engine provide shared audit semantics.
- Guided audit, manual override, cylinder support, settings, default rules, and smart rules are layered on top of existing audit workflows.
- Machine 360, ProjectDataService, relationship services, Workbook Truth Engine, PM Due, photo evidence, standardization, compatibility matrix, risk, FMEA, pilot scoring, KPI truth labels, work instructions, change validation, import/QR, timeline, health, search, and performance diagnostics now have backend or UI coverage.
- Command palette, feature registry, dashboard routes, and event bus now have explicit safety and architecture checks.
- CI and release safety checks protect the repository from generated outputs and private operational files.

## Expansion Rules

1. Start with a core service and focused tests before adding UI.
2. Use the page registry, feature registry, command registry, and search route service for discoverability.
3. Mark file-writing commands with `writes_files=True` and require confirmation.
4. Add disabled reasons for commands that depend on selected audits, machines, reports, or folders.
5. Keep expensive scans behind explicit refresh or button actions.
6. Keep generated reports, logs, caches, backups, real workbooks, and photos outside Git.

## Near-Term Follow-Ups

- Add richer search-result routing for Machine 360 action payloads.
- Add event-bus diagnostics to the App Health page.
- Extend Performance Doctor thresholds from static heuristics to user-tunable settings.
- Add exportable Feature Registry and Command Palette diagnostics for release reviews.
- Add more granular CI jobs if the full test suite becomes too slow for one workflow.

## Definition Of Done

A feature is ready when:

- Existing workflows still open.
- Core behavior has tests.
- UI changes have smoke or workflow coverage where practical.
- Safety audit passes.
- Registry checks pass.
- File-writing behavior is explicit and documented.
