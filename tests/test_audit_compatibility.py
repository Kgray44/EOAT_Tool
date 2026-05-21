from __future__ import annotations

from openpyxl import Workbook, load_workbook

from core.audit_compatibility import (
    build_compatibility_candidates,
    create_compatibility_entries,
    list_audit_options,
    list_audited_source_options,
    parse_machine_tokens,
    sync_compatible_rows_from_source,
)
from core.audit_constants import ENTRY_TYPE_COMPATIBLE, ENTRY_TYPE_FIELD, SOURCE_AUDIT_ID_FIELD
from core.audit_entries import save_audit_entry
from core.audit_progress import calculate_audit_progress
from core.paths import get_press_capacity_file, resolve_project_paths
from core.workbook_schema import get_expected_headers, get_expected_sheets


def _write_press_capacity(project_root, rows):
    path = get_press_capacity_file(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    ws = workbook.active
    ws.title = "Capacity"
    ws.append(["Machine No.", "NGW Part Number", "NGW Part Description"])
    for machine_cell, part_number, description in rows:
        ws.append([machine_cell, part_number, description])
    workbook.save(path)
    workbook.close()
    return path


def _save_audit(project_root, audit_id, machine, part_number, *, description="Part X", entry_type="Audited", source_id=""):
    entry = {
        "Audit ID": audit_id,
        "Audit Date": "2026-05-18",
        "Auditor": "KG",
        "Plant/Area": "Plant 4",
        "Press/Machine #": machine,
        "Tool #": part_number,
        "Part Name/Description": description,
        "Robot Type": "Wittmann R9",
        "EOAT Type": "Vacuum",
        "Status": "Audited",
        "Entry Type": entry_type,
        "Source Audit ID": source_id,
    }
    result = save_audit_entry(project_root, entry)
    assert result.success, result.errors
    return result


def _inventory_rows(project_root):
    workbook = load_workbook(resolve_project_paths(project_root).master_workbook, read_only=True)
    try:
        ws = workbook["EOAT Inventory"]
        headers = [cell.value for cell in ws[1]]
        return [{headers[index]: value for index, value in enumerate(row)} for row in ws.iter_rows(min_row=2, values_only=True) if any(value not in (None, "") for value in row)]
    finally:
        workbook.close()


def test_blank_or_missing_entry_type_counts_as_audited(fake_project):
    _write_press_capacity(fake_project, [("1", "PN-X", "Part X")])
    workbook_path = resolve_project_paths(fake_project).master_workbook
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_name in get_expected_sheets():
        ws = workbook.create_sheet(sheet_name)
        headers = [header for header in get_expected_headers(sheet_name) if header not in {"Entry Type", "Source Audit ID", "Compatibility Source"}]
        ws.append(headers)
    ws = workbook["EOAT Inventory"]
    headers = [cell.value for cell in ws[1]]
    row = [""] * len(headers)
    for field, value in {
        "Audit ID": "AUD-OLD-001",
        "Press/Machine #": "1",
        "Tool #": "PN-X",
        "Part Name/Description": "Part X",
        "EOAT Type": "Vacuum",
    }.items():
        row[headers.index(field)] = value
    ws.append(row)
    workbook.save(workbook_path)
    workbook.close()

    summary, error = calculate_audit_progress(fake_project)

    assert error is None
    assert summary.metrics["physically_audited_relationships"] == 1
    assert summary.entry_type_counts["Unknown treated as Audited"] == 1


def test_machine_cell_parsing_uses_exact_tokens():
    assert parse_machine_tokens("1, 2, 8, 9, 11") == ["1", "2", "8", "9", "11"]
    assert "1" in parse_machine_tokens("11, 1")
    assert parse_machine_tokens("11, 1").count("1") == 1


def test_audit_options_sort_by_machine_number_numerically(fake_project):
    for audit_id, machine in [
        ("AUD-SORT-010", "Press 10"),
        ("AUD-SORT-002", "Press 2"),
        ("AUD-SORT-WEIRD", "Bench A"),
        ("AUD-SORT-001", "Press 1"),
        ("AUD-SORT-026", "26, 70"),
    ]:
        _save_audit(fake_project, audit_id, machine, f"PN-{audit_id}", description=audit_id)
    workbook_path = resolve_project_paths(fake_project).master_workbook
    workbook = load_workbook(workbook_path)
    ws = workbook["EOAT Inventory"]
    headers = [cell.value for cell in ws[1]]
    row = [""] * len(headers)
    for field, value in {"Audit ID": "AUD-SORT-BLANK", "Tool #": "PN-BLANK", "Part Name/Description": "Blank machine", "Entry Type": "Audited"}.items():
        row[headers.index(field)] = value
    ws.append(row)
    workbook.save(workbook_path)
    workbook.close()

    options = list_audit_options(fake_project)
    sorted_ids = [option.audit_id for option in options]

    assert sorted_ids.index("AUD-SORT-001") < sorted_ids.index("AUD-SORT-002") < sorted_ids.index("AUD-SORT-010") < sorted_ids.index("AUD-SORT-026")
    assert sorted_ids.index("AUD-SORT-WEIRD") > sorted_ids.index("AUD-SORT-026")
    assert sorted_ids.index("AUD-SORT-BLANK") > sorted_ids.index("AUD-SORT-026")


def test_compatibility_source_options_sort_by_machine_number_numerically(fake_project):
    for audit_id, machine in [
        ("AUD-COMPAT-SORT-011", "Press 11"),
        ("AUD-COMPAT-SORT-003", "Press 3"),
        ("AUD-COMPAT-SORT-070", "Press 70"),
    ]:
        _save_audit(fake_project, audit_id, machine, f"PN-{audit_id}", description=audit_id)

    options = list_audited_source_options(fake_project)
    sorted_ids = [option.audit_id for option in options]

    assert sorted_ids.index("AUD-COMPAT-SORT-003") < sorted_ids.index("AUD-COMPAT-SORT-011") < sorted_ids.index("AUD-COMPAT-SORT-070")


def test_audited_source_creates_compatibility_opportunities(fake_project):
    _write_press_capacity(fake_project, [("1, 2, 8, 9, 11", "PN-X", "Part X")])
    _save_audit(fake_project, "AUD-SOURCE-001", "1", "PN-X")

    result = build_compatibility_candidates(fake_project, "AUD-SOURCE-001")
    actions = {candidate.machine_no: candidate.recommended_action for candidate in result.candidates}

    assert actions["1"] == "Already Audited"
    assert actions["2"] == "Create Compatible Entry"
    assert actions["11"] == "Create Compatible Entry"


def test_compatibility_entry_skips_audited_and_compatible_duplicates(fake_project):
    _write_press_capacity(fake_project, [("1, 2, 3", "PN-X", "Part X")])
    _save_audit(fake_project, "AUD-SOURCE-001", "1", "PN-X")

    first = create_compatibility_entries(fake_project, "AUD-SOURCE-001", ["1", "2"])
    assert first.success, first.errors
    assert first.metrics["created"] == 1
    assert first.metrics["skipped_already_audited"] == 1

    second = create_compatibility_entries(fake_project, "AUD-SOURCE-001", ["2"])
    assert second.success, second.errors
    assert second.metrics["created"] == 0
    assert second.metrics["skipped_already_compatible"] == 1

    workbook = load_workbook(resolve_project_paths(fake_project).master_workbook, read_only=True)
    ws = workbook["EOAT Inventory"]
    headers = [cell.value for cell in ws[1]]
    rows = [{headers[index]: value for index, value in enumerate(row)} for row in ws.iter_rows(min_row=2, values_only=True)]
    compatible_rows = [row for row in rows if row.get(ENTRY_TYPE_FIELD) == ENTRY_TYPE_COMPATIBLE]
    assert len(compatible_rows) == 1
    assert compatible_rows[0][SOURCE_AUDIT_ID_FIELD] == "AUD-SOURCE-001"
    workbook.close()


def test_progress_separates_covered_remaining_and_missing_reasons(fake_project):
    _write_press_capacity(fake_project, [("1, 2, 3", "PN-X", "Part X"), ("4", "PN-Y", "Part Y")])
    _save_audit(fake_project, "AUD-SOURCE-001", "1", "PN-X")
    assert create_compatibility_entries(fake_project, "AUD-SOURCE-001", ["2"]).success

    summary, error = calculate_audit_progress(fake_project)

    assert error is None
    assert summary.metrics["required_relationships"] == 4
    assert summary.metrics["physically_audited_relationships"] == 1
    assert summary.metrics["compatible_relationships"] == 1
    assert summary.metrics["total_covered_relationships"] == 2
    assert summary.metrics["remaining_relationships"] == 2
    missing_actions = {(row["Machine No."], row["NGW Part Number"]): row["Suggested Next Action"] for row in summary.missing_relationships}
    assert missing_actions[("3", "PN-X")] == "Use Compatibility Entry"
    assert missing_actions[("4", "PN-Y")] == "Needs Physical Audit"


def test_saving_audited_row_syncs_linked_compatible_rows_and_preserves_identity(fake_project):
    _write_press_capacity(fake_project, [("1, 2, 3", "PN-X", "Part X")])
    _save_audit(fake_project, "AUD-SOURCE-001", "1", "PN-X", description="Original part")
    create_result = create_compatibility_entries(fake_project, "AUD-SOURCE-001", ["2", "3"])
    assert create_result.success, create_result.errors

    before_rows = _inventory_rows(fake_project)
    compatible_before = [row for row in before_rows if row.get(ENTRY_TYPE_FIELD) == ENTRY_TYPE_COMPATIBLE]
    before_ids = {row["Press/Machine #"]: row["Audit ID"] for row in compatible_before}
    before_row_count = len(before_rows)

    update_result = save_audit_entry(
        fake_project,
        {
            "Audit ID": "AUD-SOURCE-001",
            "Audit Date": "2026-05-18",
            "Auditor": "KG",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "1",
            "Tool #": "PN-X",
            "Part Name/Description": "Updated part description",
            "Robot Type": "Wittmann R9",
            "EOAT Type": "Hybrid",
            "EOAT Moves": "Both",
            "Cup Type/Material": "Urethane",
            "Gripper Model": "Zimmer GPP",
            "Known Issues": "Updated source issue.",
            "Drop/Mis-Pick History": "Two recent drops",
            "Maintenance Frequency": "Monthly",
            "Estimated EOAT Weight": "12 lb",
            "Changeover Difficulty": "High",
            "Status": "Needs Follow-Up",
            "Priority": "High",
            "Pilot Candidate?": "Maybe",
            "Notes": "Updated shared note.",
            "Entry Type": "Audited",
        },
        allow_update=True,
    )

    assert update_result.success, update_result.errors
    assert update_result.metrics["compatibility_rows_synced"] == 2
    assert "Updated 2 linked compatibility" in update_result.summary
    after_rows = _inventory_rows(fake_project)
    assert len(after_rows) == before_row_count
    compatible_after = [row for row in after_rows if row.get(ENTRY_TYPE_FIELD) == ENTRY_TYPE_COMPATIBLE]
    assert len(compatible_after) == 2
    for row in compatible_after:
        assert row["Audit ID"] == before_ids[row["Press/Machine #"]]
        assert row["Press/Machine #"] in {"2", "3"}
        assert row[ENTRY_TYPE_FIELD] == ENTRY_TYPE_COMPATIBLE
        assert row[SOURCE_AUDIT_ID_FIELD] == "AUD-SOURCE-001"
        assert row["Part Name/Description"] == "Updated part description"
        assert row["EOAT Type"] == "Hybrid"
        assert row["EOAT Moves"] == "Both"
        assert row["Cup Type/Material"] == "Urethane"
        assert row["Known Issues"] == "Updated source issue."
        assert row["Drop/Mis-Pick History"] == "Two recent drops"
        assert row["Maintenance Frequency"] == "Monthly"
        assert row["Estimated EOAT Weight"] == "12 lb"
        assert row["Changeover Difficulty"] == "High"
        assert row["Status"] == "Needs Follow-Up"
        assert row["Priority"] == "High"
        assert row["Pilot Candidate?"] == "Maybe"
        assert row["Notes"] == "Updated shared note."


def test_saving_audited_row_with_no_linked_compatibility_reports_zero(fake_project):
    _save_audit(fake_project, "AUD-NO-LINKS-001", "1", "PN-X")

    result = save_audit_entry(
        fake_project,
        {
            "Audit ID": "AUD-NO-LINKS-001",
            "Audit Date": "2026-05-18",
            "Auditor": "KG",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "1",
            "Tool #": "PN-X",
            "Robot Type": "Wittmann R9",
            "EOAT Type": "Vacuum",
            "Known Issues": "No linked rows.",
            "Status": "Audited",
            "Entry Type": "Audited",
        },
        allow_update=True,
    )

    assert result.success, result.errors
    assert result.metrics["compatibility_rows_synced"] == 0
    assert "No linked compatibility entries found" in result.summary


def test_saving_compatible_row_does_not_recursively_sync_linked_rows(fake_project):
    _write_press_capacity(fake_project, [("1, 2, 3", "PN-X", "Part X")])
    _save_audit(fake_project, "AUD-SOURCE-001", "1", "PN-X")
    assert create_compatibility_entries(fake_project, "AUD-SOURCE-001", ["2", "3"]).success
    rows = _inventory_rows(fake_project)
    compatible_two = next(row for row in rows if row.get(ENTRY_TYPE_FIELD) == ENTRY_TYPE_COMPATIBLE and row["Press/Machine #"] == "2")
    compatible_three_before = next(row for row in rows if row.get(ENTRY_TYPE_FIELD) == ENTRY_TYPE_COMPATIBLE and row["Press/Machine #"] == "3")

    result = save_audit_entry(
        fake_project,
        {
            **compatible_two,
            "Audit Date": "2026-05-18",
            "Auditor": "KG",
            "Known Issues": "Manual compatibility note only.",
            "Entry Type": ENTRY_TYPE_COMPATIBLE,
        },
        allow_update=True,
    )

    assert result.success, result.errors
    assert result.metrics["compatibility_rows_synced"] == 0
    after_rows = _inventory_rows(fake_project)
    compatible_three_after = next(row for row in after_rows if row["Audit ID"] == compatible_three_before["Audit ID"])
    assert compatible_three_after["Known Issues"] == compatible_three_before["Known Issues"]


def test_sync_does_not_overwrite_different_source_compatible_rows(fake_project):
    _write_press_capacity(fake_project, [("1, 2", "PN-X", "Part X")])
    _save_audit(fake_project, "AUD-SOURCE-001", "1", "PN-X")
    _save_audit(fake_project, "AUD-SOURCE-OTHER", "4", "PN-X")
    _save_audit(fake_project, "AUD-COMP-DIFFERENT", "2", "PN-X", description="Different source child", entry_type=ENTRY_TYPE_COMPATIBLE, source_id="AUD-SOURCE-OTHER")

    result = save_audit_entry(
        fake_project,
        {
            "Audit ID": "AUD-SOURCE-001",
            "Audit Date": "2026-05-18",
            "Auditor": "KG",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "1",
            "Tool #": "PN-X",
            "Part Name/Description": "Should not touch different source",
            "Robot Type": "Wittmann R9",
            "EOAT Type": "Hybrid",
            "Known Issues": "Source changed.",
            "Status": "Audited",
            "Entry Type": "Audited",
        },
        allow_update=True,
    )

    assert result.success, result.errors
    assert result.metrics["compatibility_rows_synced"] == 0
    different_source = next(row for row in _inventory_rows(fake_project) if row["Audit ID"] == "AUD-COMP-DIFFERENT")
    assert different_source[SOURCE_AUDIT_ID_FIELD] == "AUD-SOURCE-OTHER"
    assert different_source["Part Name/Description"] == "Different source child"
    assert different_source["EOAT Type"] == "Vacuum"


def test_compatibility_candidates_distinguish_linked_and_different_sources(fake_project):
    _write_press_capacity(fake_project, [("1, 2, 3", "PN-X", "Part X")])
    _save_audit(fake_project, "AUD-SOURCE-001", "1", "PN-X")
    _save_audit(fake_project, "AUD-SOURCE-OTHER", "4", "PN-X")
    assert create_compatibility_entries(fake_project, "AUD-SOURCE-001", ["2"]).success
    _save_audit(fake_project, "AUD-COMP-DIFFERENT", "3", "PN-X", entry_type=ENTRY_TYPE_COMPATIBLE, source_id="AUD-SOURCE-OTHER")

    result = build_compatibility_candidates(fake_project, "AUD-SOURCE-001")
    actions = {candidate.machine_no: candidate.recommended_action for candidate in result.candidates}

    assert actions["2"] == "Already Compatible - Linked to this source"
    assert actions["3"] == "Already Compatible - Different Source / Review Needed"


def test_sync_preserves_progress_counts_and_workbook_structure(fake_project):
    _write_press_capacity(fake_project, [("1, 2", "PN-X", "Part X")])
    _save_audit(fake_project, "AUD-SOURCE-001", "1", "PN-X")
    assert create_compatibility_entries(fake_project, "AUD-SOURCE-001", ["2"]).success
    workbook_path = resolve_project_paths(fake_project).master_workbook
    workbook = load_workbook(workbook_path)
    ws = workbook["EOAT Inventory"]
    sheet_names_before = workbook.sheetnames[:]
    headers_before = [cell.value for cell in ws[1]]
    row_count_before = ws.max_row
    style_before = ws.cell(row=3, column=headers_before.index("Known Issues") + 1).style_id
    workbook.close()

    sync_result = sync_compatible_rows_from_source(workbook_path, "AUD-SOURCE-001")
    assert sync_result.updated_count == 1

    summary, error = calculate_audit_progress(fake_project)
    assert error is None
    assert summary.metrics["physically_audited_relationships"] == 1
    assert summary.metrics["compatible_relationships"] == 1
    assert summary.metrics["physical_audit_rows"] == 1
    assert summary.metrics["compatibility_rows"] == 1

    workbook = load_workbook(workbook_path)
    try:
        ws = workbook["EOAT Inventory"]
        assert workbook.sheetnames == sheet_names_before
        assert [cell.value for cell in ws[1]] == headers_before
        assert ws.max_row == row_count_before
        assert ws.cell(row=3, column=headers_before.index("Known Issues") + 1).style_id == style_before
    finally:
        workbook.close()
