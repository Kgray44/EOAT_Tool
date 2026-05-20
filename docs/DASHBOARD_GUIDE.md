# Dashboard Guide

## Home

Shows the selected project root, root validity, workbook presence, Git status, workbook health, tool registry count, current schedule summary, and recent activity log entries. Quick actions open project/report folders, run setup safely, and validate the foundation.

## Settings

Stores project root, debug mode, theme, and optional Git executable path. It can test the configured Git executable and reload settings from disk.

## Tool Registry

Shows all planned tools and their implementation status, dashboard page, CLI module, safety flags, workbook requirement, and Git requirement.

## Workbook Health

Runs foundation validation, writes a Markdown report, logs the run, opens validation reports, and opens the master workbook.

## Reports

Shows report folders, recent report files, previews Markdown/text/JSON/CSV, opens folders, integrates the existing daily status summary script, and generates weekly summaries and mentor briefs. Interactive daily summary mode is shown as a command for terminal use.

## Schedule

Reads schedule and task progress JSON files, displays planned tasks and task statuses, can safely update task status with timestamped backups, and generates morning plans from schedule carryover, blockers, and open actions.

## Audit

The Audit page has two tabs:

- `Audit Entry`: add or update EOAT Inventory records
- `Interview Notes`: add operator/technician interview notes

Both tabs can optionally create follow-up action items.

## Photos

The Photos page lists supported incoming image files, previews the target naming convention, copies or moves photos to the correct category folder, and writes Photo Index rows.

## Audit Progress

The Audit Progress page reads the workbook, displays key metrics, shows missing-data counts, and generates Markdown progress reports.

## Issue Analysis

Runs Issue Log analysis, shows issue categories, top problem cells, missing risk ranking fields, and suggested FMEA candidates.

## Standards & Documentation

Runs the documentation gap scanner, shows critical/important gaps, top EOATs by gap count, and writes Markdown plus CSV outputs.

## FMEA-Lite

Calculates RPN from existing FMEA rows, ranks risks, and suggests FMEA entries from recurring Issue Log categories. Applying suggestions is planned and disabled in Phase 3.

## Pilot Candidates

Ranks pilot candidates from the Pilot Candidates sheet or EOAT Inventory pilot flags, with score breakdown and confidence.

## KPI Dashboard

Summarizes KPI Baseline downtime, drops, mis-picks, scrap, maintenance events, and missing KPI fields.

## PM Checklists

Generates generic or EOAT-specific PM checklist drafts from EOAT type, audit fields, known issues, and PM template data. Markdown always works; DOCX can also be created when requested.

## BOM & Spare Parts

Analyzes common cups, sensors, quick disconnects, grippers, vacuum generators, and missing BOM/spare documentation fields. Writes Markdown and CSV outputs.

## Final Handoff

The Final Handoff page has four sections:

- Final Deliverable Status: runs the final deliverable checker and shows found/missing/partial items.
- Presentation Assets: exports a timestamped slide-outline and asset package.
- Final Summary: generates a Markdown and optional DOCX final summary draft.
- Handoff Package: dry-runs or builds a timestamped copied handoff package with `HANDOFF_INDEX.md`.

The handoff package copies files only. It does not move originals or modify the workbook.

## Settings Release Tools

Settings includes release-hardening actions:

- Run Full System Audit
- Backup Workbook
- Create Light Project Backup
- Open Backups Folder

Home includes workflow buttons for daily start, daily end, weekly review, and final review.
