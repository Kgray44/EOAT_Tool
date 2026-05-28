# EOAT Command Center Manual Smoke-Test Checklist

Date: 2026-05-27

Phase: 0 - Current-State Audit and Safety Baseline

Use this checklist before and after major phase work. Prefer the synthetic demo project unless explicitly validating a private local project. Do not capture screenshots, logs, paths, or reports containing private operational data in repository files.

## Preparation

- [ ] Confirm no real company data is staged in Git.
- [ ] Confirm local config remains ignored.
- [ ] Start from a clean app process.
- [ ] Prefer the default synthetic demo project for baseline smoke tests.
- [ ] Keep any generated reports/logs/cache files in ignored project output folders.

## App Launch And Shell

- [ ] Run `python run_dashboard.py`.
- [ ] App launches without traceback.
- [ ] Single-instance guard prevents a second active window.
- [ ] Window title shows EOAT Command Center.
- [ ] Sidebar navigation appears.
- [ ] Home page loads first.
- [ ] Status bar is visible and reports Ready or current task state.
- [ ] Theme loads from config.

## Home Page

- [ ] Home page shows active project root status.
- [ ] Demo mode warning appears when using the synthetic demo project.
- [ ] Master workbook path/status is shown.
- [ ] Quick status cards populate.
- [ ] Recent activity area does not crash if activity log is missing.
- [ ] Refresh performs a lightweight refresh.
- [ ] Deep Refresh starts a background task and does not freeze the shell.
- [ ] Navigation shortcuts/buttons open the expected pages.

## Project Root And Settings

- [ ] Settings page opens.
- [ ] Current project root displays.
- [ ] Demo/real project status is understandable.
- [ ] Theme selector changes the app theme.
- [ ] Git executable test works or reports a clear warning.
- [ ] Saving settings writes only ignored local config.
- [ ] Returning Home reflects saved settings.

## EOAT Audit Page

- [ ] EOAT Audit page opens.
- [ ] Audit Entry tab appears.
- [ ] Interview Notes tab appears.
- [ ] Compatibility Entry tab appears.
- [ ] Audit ID selector populates from demo workbook.
- [ ] Generate New Audit ID fills a new ID without saving immediately.
- [ ] Machine lookup accepts a demo machine number and populates available lookup fields.
- [ ] EOAT Type changes update visible/hidden fields.
- [ ] Hidden-field note is visible and understandable.
- [ ] Empty Only / Full Audit view switch works.
- [ ] Load Existing Audit ID loads a demo audit.
- [ ] Loaded audit refreshes annotation indicators.
- [ ] Duplicate current audit creates a new unsaved Audit ID.
- [ ] Save Audit Entry succeeds on a disposable demo copy or test project only.
- [ ] Save creates workbook backup before write.
- [ ] Non-applicable hidden fields save as `N/A`.
- [ ] Follow-up action item option works when selected.

## Compatibility Workflow

- [ ] Compatibility Entry tab lists audited source records.
- [ ] Selecting a source and refreshing compatible machines shows candidates or a clear no-candidates message.
- [ ] Select All only selects create-compatible candidates.
- [ ] Clear Selection clears selected candidates.
- [ ] Creating selected compatible entries works on disposable demo/test data only.
- [ ] Compatibility result reports created, skipped, or conflicts clearly.
- [ ] Source audit save syncs linked compatible rows where applicable.

## Robot_Info.xlsx Small Circuit Workflow

- [ ] Loading an audit with matching robot circuit data pulls circuit counts into the audit form when available.
- [ ] Saving an audit updates only robot-side pneumatic circuit counts and basic tracking fields in `Robot_Info.xlsx`.
- [ ] Invalid robot circuit values show a clear validation error.
- [ ] Robot Info workbook backup is created before write.
- [ ] No full robot database fields are added.

## Interview Notes

- [ ] Interview Notes tab loads.
- [ ] Required fields are visible.
- [ ] Save Interview creates a workbook row or clear validation error on disposable demo/test data.
- [ ] Optional follow-up action item can be created.

## Notes Page

- [ ] Notes page opens.
- [ ] Search/filter controls work.
- [ ] Selecting a note loads it into the editor.
- [ ] Creating a note works in demo/test data.
- [ ] Updating note status/importance works.
- [ ] Note target links display.
- [ ] Export Notes works and writes to ignored project output.

## Tags Page

- [ ] Tags page opens.
- [ ] Tag list populates.
- [ ] Tag assignment list populates.
- [ ] Creating/updating a tag works in demo/test data.
- [ ] Selecting an assignment shows target details.
- [ ] Open target navigates to the expected page when target data exists.
- [ ] Workbook color sync works on disposable demo/test data and reports warnings clearly if not possible.
- [ ] Export Tags works and writes to ignored project output.

## Photos Page

- [ ] Photos page opens.
- [ ] Incoming photo list populates from demo placeholders.
- [ ] Category selector works.
- [ ] Preview naming works.
- [ ] Copy/move actions are tested only on disposable demo/test data.
- [ ] Photo Index update succeeds or reports a clear validation error.

## Workbook Health

- [ ] Workbook Health page opens.
- [ ] Run Foundation Validation completes.
- [ ] Markdown validation report is created in ignored project output.
- [ ] Validation warnings/errors are readable.
- [ ] Repair Workbook Schema requires explicit user action.
- [ ] Refresh Audit by Press View creates backup before workbook write.

## Audit Progress

- [ ] Audit Progress page opens.
- [ ] Metrics load from workbook.
- [ ] Physical and compatible audit counts are distinguishable.
- [ ] Missing-data counts appear.
- [ ] Generate Progress Report writes a report to ignored project output.

## Schedule And Morning Plan

- [ ] Schedule page opens.
- [ ] Week selector populates where schedule files exist.
- [ ] Task table loads.
- [ ] Updating task status creates backup and writes safely.
- [ ] Morning plan generation works and writes to ignored project output.

## Reports Page

- [ ] Reports page opens.
- [ ] Report folders display.
- [ ] Recent report list displays.
- [ ] Markdown/text/JSON/CSV previews work.
- [ ] Weekly summary dialog opens and can generate a demo/test report.
- [ ] Mentor brief dialog opens and can generate a demo/test report.
- [ ] Daily summary command guidance is visible.

## Scheduled Reports Page

- [ ] Scheduled Reports page opens.
- [ ] Daily and weekly status sections display.
- [ ] Last report paths/status display when available.
- [ ] Missed summary dates display when available.
- [ ] Manual Daily Now works on disposable demo/test output.
- [ ] Manual Weekly Now works on disposable demo/test output.
- [ ] Dry-run Daily works without overwriting real reports.
- [ ] Dry-run Weekly works without overwriting real reports.
- [ ] Install/Repair Tasks reports success or clear platform/permission warnings.
- [ ] Uninstall Tasks requires explicit action and reports status.
- [ ] Open Logs and Open Reports Folder actions do not crash.

## Analysis Pages

- [ ] Issues page opens and refreshes.
- [ ] FMEA-Lite page opens and refreshes.
- [ ] Pilot Candidates page opens and refreshes.
- [ ] KPI Dashboard page opens and refreshes.
- [ ] Standards Docs page opens and refreshes.
- [ ] PM Checklists page opens.
- [ ] BOM / Spare Parts page opens and refreshes.
- [ ] Each report-generation action writes only ignored project output.

## Final Handoff

- [ ] Final Handoff page opens.
- [ ] Final deliverable check runs.
- [ ] Presentation asset export writes a timestamped ignored output.
- [ ] Final summary generation works.
- [ ] Handoff package dry-run works.
- [ ] Handoff package build copies files only and does not move originals.
- [ ] Existing packages are not overwritten.

## System Tools

- [ ] Tool Registry page opens and lists tools.
- [ ] Settings System Audit runs and reports import/file/tool status.
- [ ] Project backup actions create ignored backups only.
- [ ] Repo safety audit can be run from terminal before commit.

## Closeout

- [ ] Generated demo/test reports, logs, caches, and backups remain ignored.
- [ ] No real project artifacts are staged.
- [ ] `git status --short --ignored` is reviewed before any commit.
- [ ] `python scripts/repo_safety_audit.py` is run and findings are documented.
- [ ] Any failed smoke checks are recorded before the next phase begins.
