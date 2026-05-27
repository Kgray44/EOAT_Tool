# Codex Implementation Prompt: EOAT Notes + Tags Annotation System

## Context

This app is a local-first Python desktop tool for an EOAT Standardization / Audit project. It already has an EOAT Audit form, master tracker workbook integration, compatibility entry tooling, summary panels, left-side navigation tabs/tools, and other project management/reporting tools.

The next implementation must add a robust, elegant, and highly usable annotation system made of two new user-facing tools:

1. **Notes**
2. **Tags**

These should feel like natural extensions of the EOAT Audit workflow, not bolted-on afterthoughts.

The goal is to let the user capture project knowledge, questions, decisions, follow-ups, warnings, visual flags, field-level concerns, audit-level observations, documentation gaps, pilot-candidate evidence, and other contextual information without cluttering the EOAT Audit form or corrupting the master tracker workbook.

The implementation must be careful, modular, testable, and local-first.

---

# Primary Goal

Build a shared **Annotation System** with two clean UI surfaces:

```text
Notes = long-form project knowledge, observations, questions, decisions, follow-ups, and evidence
Tags  = lightweight visual flags/colors attached to audit fields, notes, machines, workbook warnings, photos, pilot candidates, etc.
```

The two tools should be separate pages/tabs in the app:

```text
Notes
Tags
```

They should share a backend database and be able to connect to each other, but they should not be mashed into one cluttered page.

---

# High-Level Architecture Requirement

Implement this as a shared local annotation subsystem:

```text
core/
  annotations/
    database.py
    models.py
    service.py
    migrations.py
    exports.py
    suggestions.py
    tag_colors.py
    targets.py

app/
  pages/
    notes.py
    tags.py
  widgets/
    field_tag_button.py
    note_editor.py
    tag_picker.py
    annotation_target_picker.py
    open_items_panel.py
```

Adapt exact paths to the existing project structure. Do not duplicate business logic directly inside UI widgets.

The UI should call a service layer. The service layer should handle all database access, validation, target linking, exports, and workbook color synchronization.

---

# Storage Requirement

Use a separate SQLite database for Notes and Tags.

Do **not** store notes and tags directly in the EOAT master workbook as the source of truth.

Recommended database location:

```text
<ProjectRoot>/project_data/annotations.sqlite
```

If the project already has a config/path resolver, use it. If not, add a safe path helper that creates the folder if missing.

The workbook may receive visual cell colors based on tags, but the SQLite database is the authoritative source.

---

# Must Not Break Existing Behavior

Do not regress existing EOAT Audit behavior.

Existing behavior that must remain intact:

- Saving an audit still writes the audit data to the master tracker workbook.
- Existing audit loading still works.
- Existing compatibility entry workflow still works.
- Existing summary panel still works.
- Existing defaults and field visibility behavior should remain intact unless explicitly changed below.
- Existing workbook health / progress tools should continue to run.
- Existing file paths and project root settings must not be broken.

This change should be additive and carefully integrated.

---

# Required EOAT Audit Form Workflow Changes

## 1. Clear Form Confirmation Popup

When the user presses **Clear Form**, show a confirmation dialog.

Dialog behavior:

- Explain that it clears only the current on-screen form entries and summary panel.
- Explain that it does not delete saved audit data from the workbook.
- Include a checkbox:

```text
Do not ask again this session
```

Required buttons:

```text
Cancel
Clear Form
```

Suggested message text:

```text
Clear this form?

This will erase the current on-screen entries and clear the summary panel.
It will not delete any audit entries already saved to the workbook.
```

If the user checks “Do not ask again this session,” suppress this confirmation only until the app restarts. Do not persist this preference permanently unless the existing app already has a safe session-preferences system.

## 2. Save Audit Entry Auto-Clears Form

After the user presses **Save Audit Entry** and the save succeeds:

1. Validate the audit form.
2. Save the audit entry to the master tracker workbook.
3. Automatically run the Compatibility Entry tool for the saved/edited audit.
4. Clear the form fields automatically so the user can start the next audit.
5. Do **not** clear the bottom EOAT Audit summary/output panel.
6. Combine the EOAT Audit save summary and Compatibility Entry summary into the same bottom summary/output panel.
7. Keep the combined summary visible after the form clears.

The user should not need to manually press Clear Form after saving.

## 3. Clear Form Still Clears Summary Panel

The **Clear Form** button should continue to clear the bottom summary/output panel.

Difference:

```text
Save Audit Entry:
  Clears form fields only after successful save.
  Preserves and updates summary panel.

Clear Form:
  Requires confirmation unless suppressed for session.
  Clears form fields.
  Clears summary/output panel.
```

## 4. Compatibility Auto-Run Summary

The summary panel after Save Audit Entry should be formatted cleanly, for example:

```text
Audit Save Summary
------------------
Saved audit AUD-00042 for Machine 12.
Updated workbook row 42.
Blank unanswered fields were written as N/A.

Compatibility Entry Summary
---------------------------
Compatibility entries were updated for AUD-00042.
Machine/tool relationship refreshed successfully.
```

If compatibility auto-run fails, do not hide the audit save success. Show both clearly:

```text
Audit Save Summary
------------------
Saved audit AUD-00042 for Machine 12.

Compatibility Entry Summary
---------------------------
Compatibility update failed: <friendly error message>
The saved audit entry was not rolled back.
```

Do not expose raw tracebacks in the normal summary panel. Put raw errors in debug logs if the app has logging.

---

# Required Default Field Changes

Apply these default values in the EOAT Audit form:

```text
ATI Changeover Difficulty default = Low
Dovetail Changeover Difficulty default = Medium
Vacuum Type default = Venturi
Quick Disconnects Present default = Yes
Vacuum Confirmation Present default = Yes
Part-Present Detection Present default = No
Documentation / Photos fields default = No
```

Also preserve these existing workflow rules if they already exist:

```text
Blank unanswered fields saved to workbook should become N/A.
When loading an existing audit, workbook N/A values should appear as blank in the app UI.
Fields that do not apply to the EOAT type should save as N/A.
```

---

# Notes Tool Requirements

## Purpose

The Notes tool is a project knowledge system.

It should let the user capture:

- Questions
- Facts
- Issues
- Decisions
- Follow-ups
- Ideas
- Risks
- Observations
- Standardization opportunities
- Documentation gaps
- Pilot candidate evidence
- Maintenance concerns
- Compatibility concerns
- General project knowledge

This should be much more than a plain text box.

## Notes Page Name

The left navigation tab/page should be named:

```text
Notes
```

## Basic Default Note Fields

The default visible note fields should stay clean and minimal.

Default fields:

```text
Subject
Body
Importance
```

Optional but acceptable if visually clean:

```text
Status
Collection
Note Type
```

Do not overload the default form with every possible metadata field. The user explicitly wants only a few basics visible by default.

## Optional “+” Add Field Button

Add a **+ button** in the Notes editor.

When clicked, it should open a dropdown/popup/panel with:

- Search box
- List of optional fields that can be added to the note
- Clear labels and descriptions

Optional fields should include:

```text
Status
Collection / Folder
Note Type
Follow-Up Date
Linked Audit ID
Linked Machine
Linked EOAT / Tool
Linked Audit Field
Linked Compatibility Entry
Linked Photo / Attachment
Linked Workbook Health Warning
Linked Pilot Candidate
Related Tags
Created By
```

The user should be able to add optional fields only when needed.

Do not show all optional fields by default.

## Importance Options

Use exactly these importance values:

```text
Low
Neutral
Important
Critical
```

Default:

```text
Neutral
```

## Optional Status

Notes should support optional status.

Recommended status values:

```text
Open
Resolved
Archived
```

The status field should be optional and addable from the + button.

If shown by default, it should not clutter the page.

## Follow-Up Date

Notes should support an optional follow-up date.

This should be addable from the + button.

The app does not need a full notification scheduler yet unless one already exists. For now, follow-up date should support filtering and sorting.

## Body Format

The note body should support simple rich text / Markdown.

Minimum acceptable support:

- Multi-line body
- Bullet lists
- Numbered lists
- Basic Markdown rendering or preview if reasonable
- Plain-text safe storage

Preferred:

- Edit mode
- Preview mode
- Markdown saved as text in SQLite

Do not require an internet connection or external cloud service.

## Attachments / Photo Links

Notes should support attachments or photo/document links eventually.

For this implementation:

- Add attachment/photo link support as an optional field from the + button.
- Allow linking to local file paths or project-relative paths.
- Do not embed binary files into SQLite unless the existing architecture already supports safe binary storage.
- Prefer storing file path references.

## Notes List / Browser

The Notes page should include a clean browser/list area.

Each note card/row should show:

```text
Subject
Importance
Optional Status
Optional Collection
Optional Note Type
Created/Updated date
Small indicator if linked to an audit/machine/field/tag
```

The full body should be shown in a selected-note detail panel or editor, not crammed into every row.

## Notes Search

Add search for:

- Subject
- Body
- Collection
- Note Type
- Audit ID
- Machine
- Tags

Search should be fast and local.

SQLite FTS is optional, but a basic indexed search is acceptable.

## Notes Filtering

Support filtering by:

```text
Importance
Status
Collection
Note Type
Linked Audit
Linked Machine
Tag
Follow-Up Date
Open items only
```

## Notes Sorting

Support sorting by:

```text
Updated date
Created date
Subject alphabetical
Importance
Status
Collection
Note Type
Follow-Up Date
```

## Notes Export

Add optional export to:

```text
Markdown
Excel
```

Export requirements:

- Allow exporting all notes.
- Allow exporting filtered notes.
- Markdown export should produce readable project documentation.
- Excel export should include note metadata columns.
- Exports should be saved to a predictable reports/exports folder.
- Never overwrite an existing export without either timestamping or asking confirmation.

Suggested export paths:

```text
<ProjectRoot>/reports/exports/notes_export_YYYYMMDD_HHMMSS.md
<ProjectRoot>/reports/exports/notes_export_YYYYMMDD_HHMMSS.xlsx
```

---

# Tags Tool Requirements

## Purpose

The Tags tool is a visual annotation and organization system.

It should let users flag things with:

- One or more tag names
- One or more colors
- Optional notes/comments
- Optional link to a Note

Tags should apply to many types of targets, including EOAT Audit fields and broader project objects.

## Tags Page Name

The left navigation tab/page should be named:

```text
Tags
```

## Tags Are Not Just Colors

A tag should have a meaning, not only a color.

For example:

```text
Needs Review
Critical Issue
Verified
Question
Missing Evidence
Data Conflict
Follow Up
Pilot Candidate Evidence
Maintenance Concern
Compatibility Concern
Documentation Gap
Safety Concern
```

Colors should visually reinforce the tag, but the tag name/meaning is the actual data.

## Custom Tag Names

Users must be able to create custom tag names.

The UI should also provide a default dropdown/list of suggested standard tags.

Suggested default tags:

```text
Needs Review
Question
Verified
Missing Evidence
Data Conflict
Follow Up
Pilot Candidate Evidence
Maintenance Concern
Compatibility Concern
Documentation Gap
Safety Concern
```

Custom tags should be stored in SQLite.

## Fixed Color Palette

For now, tag colors should use a fixed palette.

Users should not be able to enter arbitrary hex colors in this phase.

Recommended palette labels:

```text
Yellow
Red
Green
Blue
Purple
Orange
Gray
Teal
Pink
```

Store a stable internal color key, not only display text.

Example:

```text
yellow
red
green
blue
purple
orange
gray
teal
pink
```

Map these keys to UI colors and Excel fill colors in one central place.

## Multiple Tags / Colors Per Target

A field or object can have multiple tags/colors at the same time.

Example:

```text
Machine 12 / Sensor Type:
- Needs Review / Yellow
- Missing Evidence / Orange
```

The UI should show all tags.

## Highest-Priority Color Wins for Workbook Cell Fill

Excel cells can only show one main background fill cleanly.

When multiple tags/colors are applied to the same audit field, the master workbook cell background should use the highest-priority tag color.

Recommended priority order:

```text
Critical / Red
Safety Concern / Red
Data Conflict / Orange
Missing Evidence / Orange
Needs Review / Yellow
Question / Purple
Compatibility Concern / Blue
Maintenance Concern / Teal
Pilot Candidate Evidence / Blue
Follow Up / Yellow
Verified / Green
Neutral / Gray
```

Implement this centrally so it can be changed later.

The app should still show all tags even if Excel only displays the highest-priority color.

## Subtle UI Indication

Tagged fields or objects should show a subtle visual indication.

For EOAT Audit fields:

- Subtle colored border and/or background tint
- Tiny flag icon state change
- Tooltip listing tag names

Do not make the form visually chaotic.

The field should remain readable.

## Tiny Field-Level Tag Button

On the EOAT Audit form, add a tiny non-invasive flag button/icon next to every field where tagging makes sense.

Requirements:

- No text label on the button.
- Use a flag icon or similarly tiny icon.
- Must not disrupt form layout.
- Must not make the audit form harder to scan.
- Must be keyboard/mouse accessible if reasonable.
- Tooltip should explain purpose, for example:

```text
Tag this field
```

Suggested field layout:

```text
Vacuum Type        [ Venturi ▼ ]   ⚑
Sensor Type        [           ]   ⚑
Quick Disconnect   [ PTC      ]   ⚑
```

## Field Tag Popup

Clicking a field’s tag button should open a compact popup/dialog.

The popup should show:

```text
Field label
Audit ID if available
Machine if available
Current value
Existing tags
Add/remove tags
Color selection from fixed palette
Optional short comment
Create/link note action
```

Required actions:

```text
Add Tag
Remove Tag
Create Note About This Field
Link Existing Note
Save
Cancel
```

If the audit has not been saved yet and has no Audit ID, the tag should either:

1. Attach to a temporary draft form ID and resolve after save, or
2. Warn the user that field-level tags will be attached after the audit is saved.

Preferred behavior:

- Support draft tags during an unsaved audit.
- When Save Audit Entry succeeds and Audit ID is known, convert draft tags to the saved Audit ID target.

If implementing draft tags is too invasive, use a clean message and require saving first for persistent field tags.

## Tag Targets

Tags should be able to apply to the following target types:

```text
Audit
Audit Field
Machine
Note
Compatibility Entry
Photo / Documentation Item
Workbook Health Warning
Pilot Candidate
General Project Item
```

Important nuance:

- Compatibility entries should be supported as a possible target type in the database/model.
- However, when Save Audit Entry auto-runs Compatibility Entry, the summary result does not need special tag/note linking in this phase.

## Tags Page Features

The Tags page should allow the user to:

- View all tags.
- View all tagged targets.
- Search tags.
- Filter by tag name.
- Filter by color.
- Filter by target type.
- Filter by audit ID.
- Filter by machine.
- Filter by linked note.
- Sort by tag name.
- Sort by color.
- Sort by target type.
- Sort by updated date.
- Sort by importance/priority if available.
- Open/view the connected audit/note/field where possible.
- Edit tag name.
- Change tag color.
- Archive/delete unused tags if safe.
- Reorganize tags.

## Bulk Edit Tags

Add bulk edit functionality.

Examples:

```text
Select all tags matching “Needs Review” on Machine 1.
Change them to “Resolved” or remove them.
Change all selected tag colors.
Archive selected tag assignments.
Move selected tagged items to another tag.
```

Bulk actions should require confirmation.

Bulk edit should never silently destroy data.

Recommended bulk actions:

```text
Add tag to selected targets
Remove tag from selected targets
Change tag color
Replace tag name
Archive selected tag assignments
Link selected tags to note
Export selected tags
```

## Tags Export

Add optional export to:

```text
Markdown
Excel
```

Export should support:

- All tags
- Filtered tags
- Selected tags

Suggested export paths:

```text
<ProjectRoot>/reports/exports/tags_export_YYYYMMDD_HHMMSS.md
<ProjectRoot>/reports/exports/tags_export_YYYYMMDD_HHMMSS.xlsx
```

---

# Notes / Tags Connection Requirements

Notes and Tags should be connected.

A note can have many tags.
A tag can connect to many notes.
An audit field can have many tags.
An audit field can link to one or more notes.

The UI should allow:

```text
From a Note:
  Add related tags.
  View tagged targets connected to the note.

From a Tag:
  View related notes.
  Link selected tag assignments to an existing note.
  Create a new note from a tag/target.

From an Audit Field:
  Add/remove tags.
  Create note about this field.
  Link existing note.
```

---

# Open Items Dashboard Requirement

Add a clean, compact “Open Items” dashboard card/panel somewhere appropriate, likely on the Home page or Project Overview page.

It should not be messy or visually loud.

It should summarize:

```text
Open Critical Notes
Open Important Notes
Fields Needing Review
Data Conflicts
Missing Evidence Tags
Compatibility Concerns
Documentation Gaps
Follow-Ups Due Soon
```

Clicking an item/count should open the filtered Notes or Tags page.

Example:

```text
Open Items
----------
Critical Notes: 2
Important Notes: 5
Fields Needing Review: 8
Data Conflicts: 1
Follow-Ups Due This Week: 3
```

Keep it compact.

Do not add a messy new giant dashboard section.

---

# Suggestion Engine Requirement

Auto-generated warnings should only suggest notes/tags, not automatically create them.

Examples of future suggestions:

```text
EOAT Type = Gripper but Cup Type/Material is filled.
Sensors Present = No but Sensor Type is filled.
Sensors Present = No but Cable Management Condition is required.
Quick Disconnects Present = No but QD Type is filled.
Vacuum Type filled but EOAT Type has no vacuum system.
Documentation Photos = No on a high-priority audit.
```

The app should present suggestions like:

```text
Suggested Tag: Data Conflict
Target: AUD-00042 / Cup Type/Material
Reason: EOAT Type is Gripper, but cup material is populated.
[Apply] [Ignore]
```

For this phase, add the service/model foundations and at least a simple UI location for suggested annotations if feasible.

Do not make automatic changes without user confirmation.

---

# Workbook Cell Coloring Requirement

When a tag/color is applied to an EOAT Audit field that maps to a cell in the master tracker workbook:

1. Store the tag assignment in SQLite.
2. Resolve the field target to the correct workbook row/column using Audit ID and field key.
3. Apply the highest-priority tag color as the cell background fill.
4. Save the workbook safely.
5. If the tag is removed or priority changes, update the cell fill accordingly.
6. If no color tags remain, restore default/no fill if safe.

Do not rely only on row number because rows may be sorted or inserted.

Use stable identifiers:

```text
Audit ID
Field key
Sheet name
Header name
```

Store optional cached cell reference for convenience only, not as the source of truth.

---

# Suggested SQLite Schema

Adapt to the existing code style, but use this concept.

## notes

```sql
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    body_markdown TEXT NOT NULL DEFAULT '',
    importance TEXT NOT NULL DEFAULT 'Neutral',
    status TEXT,
    collection TEXT,
    note_type TEXT,
    follow_up_date TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT
);
```

## tags

```sql
CREATE TABLE IF NOT EXISTS tags (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    color_key TEXT NOT NULL,
    description TEXT,
    is_default INTEGER NOT NULL DEFAULT 0,
    is_archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

## annotation_targets

This table stores target objects that notes/tags can link to.

```sql
CREATE TABLE IF NOT EXISTS annotation_targets (
    id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_label TEXT,
    audit_id TEXT,
    machine_id TEXT,
    field_key TEXT,
    field_label TEXT,
    sheet_name TEXT,
    header_name TEXT,
    workbook_path TEXT,
    cached_cell_ref TEXT,
    object_ref TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

Target type examples:

```text
audit
audit_field
machine
note
compatibility_entry
photo
workbook_warning
pilot_candidate
project_item
```

## tag_assignments

```sql
CREATE TABLE IF NOT EXISTS tag_assignments (
    id TEXT PRIMARY KEY,
    tag_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    comment TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT,
    FOREIGN KEY(tag_id) REFERENCES tags(id),
    FOREIGN KEY(target_id) REFERENCES annotation_targets(id)
);
```

## note_targets

```sql
CREATE TABLE IF NOT EXISTS note_targets (
    id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(note_id) REFERENCES notes(id),
    FOREIGN KEY(target_id) REFERENCES annotation_targets(id)
);
```

## note_tags

```sql
CREATE TABLE IF NOT EXISTS note_tags (
    id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL,
    tag_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(note_id) REFERENCES notes(id),
    FOREIGN KEY(tag_id) REFERENCES tags(id)
);
```

## attachments

```sql
CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    note_id TEXT,
    target_id TEXT,
    file_path TEXT NOT NULL,
    display_name TEXT,
    description TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(note_id) REFERENCES notes(id),
    FOREIGN KEY(target_id) REFERENCES annotation_targets(id)
);
```

## indexes

Add useful indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_notes_importance ON notes(importance);
CREATE INDEX IF NOT EXISTS idx_notes_status ON notes(status);
CREATE INDEX IF NOT EXISTS idx_notes_collection ON notes(collection);
CREATE INDEX IF NOT EXISTS idx_notes_type ON notes(note_type);
CREATE INDEX IF NOT EXISTS idx_targets_type ON annotation_targets(target_type);
CREATE INDEX IF NOT EXISTS idx_targets_audit ON annotation_targets(audit_id);
CREATE INDEX IF NOT EXISTS idx_targets_machine ON annotation_targets(machine_id);
CREATE INDEX IF NOT EXISTS idx_targets_field ON annotation_targets(field_key);
CREATE INDEX IF NOT EXISTS idx_tag_assignments_tag ON tag_assignments(tag_id);
CREATE INDEX IF NOT EXISTS idx_tag_assignments_target ON tag_assignments(target_id);
```

---

# Service Layer Requirements

Create a clean API/service layer for annotations.

Example methods:

```python
create_note(...)
update_note(...)
delete_or_archive_note(...)
search_notes(...)
export_notes_markdown(...)
export_notes_excel(...)

create_tag(...)
update_tag(...)
archive_tag(...)
list_tags(...)
search_tags(...)

create_or_get_target(...)
assign_tag_to_target(...)
remove_tag_from_target(...)
get_tags_for_target(...)
get_targets_for_tag(...)

link_note_to_target(...)
unlink_note_from_target(...)
link_note_to_tag(...)

get_open_items_summary(...)
get_suggested_annotations(...)
apply_suggested_annotation(...)

sync_target_colors_to_workbook(...)
sync_all_tag_colors_to_workbook(...)
```

Do not make UI code write SQL directly.

---

# Migration / Initialization Requirements

On app startup or when opening a project root:

1. Ensure annotations.sqlite exists.
2. Run migrations safely.
3. Seed default tags if they do not exist.
4. Never duplicate default tags on every startup.
5. Preserve user-created custom tags.
6. Preserve archived tags.

Use a schema version table:

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
```

---

# UI / UX Requirements

## General

The Notes and Tags tools should feel polished and smooth.

Do not create a half-finished utility page with a few raw tables and call it done.

Prioritize:

- Clean spacing
- Search-first interaction
- Good empty states
- Clear buttons
- Subtle colors
- No visual clutter
- Fast filtering/sorting
- Safe confirmations for destructive actions

## Notes Page Layout Suggestion

Recommended layout:

```text
Notes
--------------------------------------------------
[Search notes...] [Importance ▼] [Status ▼] [Collection ▼] [Sort ▼] [+ New Note]

Left/main list:
  Note cards or table rows

Right/detail editor:
  Subject
  Body markdown editor
  Importance
  + Add Field
  Linked targets
  Related tags
  Save / Archive / Export
```

If the app uses stacked pages instead of split panes, adapt to existing style.

## Tags Page Layout Suggestion

Recommended layout:

```text
Tags
--------------------------------------------------
[Search tags/targets...] [Color ▼] [Target Type ▼] [Machine ▼] [Sort ▼] [+ New Tag]

Tag list / tag manager
Tagged target table
Detail panel:
  Selected tag
  Color
  Description
  Connected targets
  Connected notes
  Bulk actions
```

## Audit Form Tag Button

The flag button must be tiny and non-invasive.

Do not add huge labels or secondary rows under every input.

The EOAT Audit form is already dense; preserve scanability.

---

# Data Integrity Rules

## Stable Target Identity

For field-level tags, stable identity should be based on:

```text
Audit ID + field key
```

Not only:

```text
Excel row + Excel column
```

Workbook cell reference can be cached, but must not be the only source of truth.

## Safe Workbook Writes

When syncing tag colors to Excel:

- Use existing workbook I/O helper if available.
- Back up workbook if the existing app normally does so.
- Avoid wiping unrelated formatting.
- Only modify the intended cell fills.
- Handle missing workbook/sheet/header gracefully.
- Log warnings instead of crashing when a tag cannot be synced.

## Safe Deletes

Prefer archiving notes/tags/tag assignments over permanent deletion.

If permanent delete exists, require confirmation.

## No Silent Data Loss

Bulk edits and Clear Form must use confirmation.

---

# Testing Requirements

Add automated tests where reasonable.

## Unit Tests

Test:

- SQLite database initialization
- Migrations
- Default tag seeding does not duplicate tags
- Create/update/search notes
- Create/update/search tags
- Link note to target
- Assign multiple tags to one target
- Highest-priority color selection
- Export notes to Markdown
- Export notes to Excel
- Export tags to Markdown
- Export tags to Excel
- Open Items summary counts
- Suggested annotation generation

## Workbook Tests

Use a temporary workbook fixture.

Test:

- Tagging an audit field changes the correct cell fill.
- Multiple tags choose highest-priority fill.
- Removing highest-priority tag falls back to next highest priority.
- Removing all tags clears/restores the fill safely.
- Missing Audit ID/header/sheet produces friendly warning, not crash.

## UI Smoke Tests

If the project has UI testing/smoke tests, add:

- Notes page opens.
- Tags page opens.
- New Note button exists.
- New Tag button exists.
- EOAT Audit form still opens.
- Tag flag buttons appear on appropriate fields.
- Clear Form confirmation appears.
- Save Audit Entry still performs save workflow.

## Regression Tests

Specifically ensure:

- Save Audit Entry clears form after success.
- Save Audit Entry preserves combined summary panel.
- Clear Form clears summary panel.
- Clear Form confirmation can be suppressed for session.
- ATI Changeover Difficulty default is Low.
- Vacuum Type default is Venturi.

---

# Acceptance Criteria

This implementation is complete only when all of the following are true.

## EOAT Audit Workflow

- Clear Form shows confirmation.
- Confirmation includes “Do not ask again this session.”
- Clear Form clears the form and bottom summary panel.
- Save Audit Entry saves the audit.
- Save Audit Entry automatically runs Compatibility Entry afterward.
- Save Audit Entry clears form fields after successful save.
- Save Audit Entry does not clear the summary panel.
- Summary panel shows combined audit save summary and compatibility summary.
- Defaults are updated as specified.

## Notes

- Left-side Notes tab exists.
- Notes are stored in SQLite.
- User can create/edit/archive notes.
- Default note form is simple and not cluttered.
- + button allows optional fields to be added.
- Notes support Low/Neutral/Important/Critical importance.
- Notes support optional status.
- Notes support optional follow-up date.
- Notes support Markdown/simple rich text body.
- Notes can link to audits, machines, audit fields, photos/attachments, workbook warnings, pilot candidates, and tags.
- Notes can be searched, filtered, and sorted.
- Notes can export to Markdown and Excel.

## Tags

- Left-side Tags tab exists.
- Tags are stored in SQLite.
- User can create custom tag names.
- Default tag suggestions exist.
- Tag colors use a fixed palette.
- Targets can have multiple tags/colors.
- Highest-priority tag color controls Excel cell fill.
- All tags remain visible in app even if Excel shows only one fill color.
- Tags can apply to audits, audit fields, machines, notes, compatibility entries, photos/documentation items, workbook warnings, pilot candidates, and general project items.
- Tags page can view, search, filter, sort, reorganize, and bulk edit tags.
- Tags can export to Markdown and Excel.

## Audit Form Tag Integration

- Tiny flag buttons appear beside fields where tagging makes sense.
- Buttons are non-invasive and do not clutter the form.
- Tagged fields show subtle visual indication.
- Clicking a flag opens a field tag popup.
- Popup supports adding/removing tags, selecting fixed color, optional comment, creating a note, and linking an existing note.
- Field tags sync to workbook cell colors when possible.

## Open Items

- A clean Open Items dashboard card/panel exists.
- It summarizes critical/important open notes, fields needing review, data conflicts, missing evidence, compatibility concerns, documentation gaps, and follow-ups due soon.
- Counts link/filter into Notes or Tags where possible.

## Quality

- No raw tracebacks in normal UI.
- Friendly errors for missing workbook/database/path issues.
- Activity logging or debug logging records annotation operations where appropriate.
- Tests are added for core behavior.
- Existing app behavior is not regressed.

---

# Implementation Phasing Recommendation

Do not try to build every single UI feature first and then discover the backend is held together with emotional duct tape.

Implement in this order:

## Phase 1: Backend Foundation

- SQLite path resolver
- Database initialization
- Migrations
- Models/service layer
- Default tags
- Target model
- Basic note/tag CRUD
- Basic tests

## Phase 2: Notes Page

- Notes tab
- Notes list
- Note editor
- Search/filter/sort
- + optional field button
- Markdown body support
- Export to Markdown/Excel

## Phase 3: Tags Page

- Tags tab
- Tag manager
- Tagged target list
- Search/filter/sort
- Bulk edit foundation
- Export to Markdown/Excel

## Phase 4: EOAT Audit Integration

- Tiny flag buttons beside appropriate fields
- Field tag popup
- Target creation for audit fields
- Subtle field indication
- Workbook cell color sync

## Phase 5: Workflow Refinements

- Clear Form confirmation
- Save Audit Entry auto-clear
- Save Audit Entry auto-run Compatibility Entry
- Combined summary panel behavior
- Updated defaults

## Phase 6: Open Items + Suggestions

- Open Items dashboard panel
- Basic suggested annotations
- Apply/ignore suggestion actions
- Final tests and polish

If dependencies make this order awkward, backend foundation still comes first.

---

# Final Instruction to Codex

Make this feel like a polished internal engineering tool, not a toy demo.

The user is actively using the app during real EOAT audits. Prioritize stability, clarity, data safety, and clean workflow.

Do not clutter the EOAT Audit page.

Do not make Notes and Tags confusingly overlap in the UI.

Do not store annotation truth only in Excel formatting.

Do build a shared annotation system with SQLite as the source of truth, clean Notes and Tags pages, subtle audit-form tagging, safe workbook color sync, and exportable project knowledge.
