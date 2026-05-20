# Morning Plan Usability Polish Report

## Summary

This polish pass improves the Morning Plan from a correct schedule report into a more practical daily briefing. The generator still preserves the project-calendar date resolver, Week/Day title, safe file creation, CLI behavior, and Plan Sources section, but the plan now gives clearer decision support for what to do first, what to do if blocked, and what counts as done by the end of the day.

## Files Changed

- `core/morning_planner.py`
- `tests/test_morning_planner.py`
- `tests/ui/test_home_morning_plan.py`
- `docs/Morning_Plan_Usability_Polish_Report.md`

## Output Improvements

Primary Focus:

- Replaced the robotic `making visible progress on:` phrasing with a mission-style sentence.
- Uses real scheduled/carryover tasks as inputs, then turns them into action wording.
- Keeps the focus concise and phase-aware.

Recommended Next Actions:

- Expands from a thin one-item fallback into 3-5 practical actions when schedule/project state supports it.
- Prioritizes today's scheduled tasks, then blockers/carryover, then project state and phase-aware fallbacks.
- Avoids repeating the Scheduled Tasks section verbatim.

If Blocked:

- Added `## If Blocked`.
- Provides 3-5 conditional fallback actions.
- Uses real blocked tasks first when present.
- Adds Discovery/Analysis/Implementation/Wrap-up fallback guidance without inventing approval or access status.

Definition of Done:

- Added `## Definition of Done for Today`.
- Converts scheduled tasks into measurable finish lines.
- Always includes updating task statuses before the daily end summary.

Questions:

- Keeps phase-aware questions, but now prioritizes questions related to today's task text and blockers.
- Limits to useful, deduplicated questions.

Optional Stretch:

- Uses future unfinished tasks in schedule order.
- Uses `Optional:` wording.
- Suppresses stretch work when carryover/blockers are present.
- Falls back truthfully to `No stretch tasks suggested yet.`

Recent Context and Plan Sources:

- Latest tool run now includes status and timestamp when activity-log metadata exists.
- Falls back truthfully when status or timestamp is unavailable.
- Plan Sources remains compact and now includes manual override status.

## Tests

Commands run:

```powershell
python -m pytest tests/test_morning_planner.py -q
python -m pytest tests/test_morning_planner.py tests/ui/test_home_morning_plan.py -q
python -m pytest -q
```

Results:

```text
13 passed in 18.39s
15 passed in 32.26s
125 passed in 227.07s (0:03:47)
```

Coverage added/updated:

- Primary Focus quality.
- Recommended Next Actions count and usefulness.
- `If Blocked` section content.
- `Definition of Done for Today` section content.
- No blank bullets.
- Optional Stretch future-task and empty-state behavior.
- Latest tool-run metadata formatting.
- Existing Week 1 Day 2 date/filename/Plan Sources/CLI regressions.

## Before/After Example

Before:

```markdown
## Primary Focus
Continue Week 1 Day 2 discovery work by making visible progress on: Begin target cell list, Start first walkthrough/audit if approved, Decide photo naming system.

## Recommended Next Actions
- Run workbook validation after data entry or template changes.
```

After:

```markdown
## Primary Focus
Today's goal is to turn setup into real discovery progress: start the target-cell list and flag the cells that need mentor or supervisor confirmation, confirm the first safe walkthrough or audit target, then start the audit entry if access is approved, and decide the photo naming format before more evidence gets collected.

## Recommended Next Actions
- Start the target-cell list and flag the cells that need mentor or supervisor confirmation.
- Confirm the first safe walkthrough or audit target, then start the audit entry if access is approved.
- Decide the photo naming format before more evidence gets collected.
- Run workbook validation after any audit or template changes.
- Confirm the first 2-4 target cells with mentor or supervisor if priorities are still unclear.
```

## Known Limitations

- The plan still relies on available schedule/task text, workbook state, and activity-log metadata. If those are sparse, the generator uses phase-aware fallbacks.
- It does not infer real floor access, approval status, or mentor availability.
- It does not add new workbook fields or change workbook schema.
- Questions are heuristic and task-aware, not generated from a separate knowledge base.
