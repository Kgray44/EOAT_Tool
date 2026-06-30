# EOAT Atlas Information Library

The EOAT Atlas Information Library is a structured knowledge base, not a page-help text dump. Entries live in `core/atlas_information_library.py` and are loaded into the Atlas UI from the local `AtlasDataBundle`.

## Entry Types

Use the narrowest entry type that matches the reference:

- `app_help`: Atlas page guidance, workflow mistakes, data dependencies, and troubleshooting.
- `eoat_standard`: Engineering standards for EOAT design, documentation, inspection, and failure modes.
- `compatibility_rule`: Inputs, decision logic, confidence rules, warnings, examples, and repair actions.
- `data_dictionary`: Field definitions, source of truth, allowed values, validation, and repair action.
- `troubleshooting`: Symptom, likely causes, checks, fixes, manual workaround, and diagnostics.
- `report_guide`: Report purpose, inputs, key columns, interpretation, warning meanings, and actions.
- `pm_inspection`: Inspection frequency, checklist items, pass/fail criteria, findings, and corrective actions.
- `source_document`: Source document purpose, how Atlas uses it, when to open it, and repair boundary.

## Adding Or Editing Entries

1. Edit `core/atlas_information_library.py`.
2. Add entries through the helper for the correct type, such as `_compatibility_entries()` or `_data_dictionary_entries()`.
3. Keep content concise and technical. Prefer short bullet-style facts over long paragraphs.
4. Add useful `tags`, `related_fields`, `related_pages`, and `related_references`; do not point entries back to themselves.
5. Set source metadata with `_source(...)`. Use one of the recognized source names when possible:
   - `Atlas generated help`
   - `EOAT Standard Design Guidelines`
   - `EOAT Preventive Maintenance Checklist`
   - `Robot EOAT Intern Project Charter`
   - `Press Capacity Workbook`
   - `EOAT Master Tracker`
   - `Photo Folder Index`
   - `Generated Report`
6. If no real file applies, use `Atlas internal reference`. Atlas will show `File: Not applicable` and `Last modified: Not applicable`.
7. For source-backed entries, keep the source section specific enough that a user knows where to look.

## Quality Rules

`validate_information_library()` enforces the main content rules:

- No more than 20% duplicated body text across entries.
- Every non-app-help entry needs at least three meaningful sections.
- Compatibility rules must include `Inputs Used` and `Decision Logic`.
- Troubleshooting entries must include `Symptom`, `Likely Causes`, `Checks To Run`, and `Fix Steps`.
- Data dictionary entries must include `Definition`, `Source Of Truth`, `Used By`, and `Repair Action`.
- Source metadata must not contain raw `-` placeholder values.
- Banned generic page-help phrases must not appear in generated entry bodies.

Run the focused tests after editing:

```powershell
python -m pytest tests/test_atlas_information_library.py tests/test_atlas_ui_features.py::test_information_library_tree_represents_all_filtered_entries
```

## Search Behavior

Search indexes title, summary, body sections, tags, source document names, source paths, related fields, related pages, related references, warnings, and example values. If an entry includes important example data, put the exact values in `LibraryExample` so search can find them.
