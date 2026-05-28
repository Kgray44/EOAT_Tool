from __future__ import annotations

from core.workbook_truth import (
    TRUTH_COMPATIBILITY_DERIVED,
    TRUTH_ESTIMATED,
    TRUTH_MEASURED,
    TRUTH_MISSING,
    TRUTH_NOT_APPLICABLE,
    TRUTH_SYSTEM,
    TRUTH_UNKNOWN,
    analyze_truth_from_rows,
    analyze_workbook_truth,
    classify_truth_cell,
)


def test_truth_cell_classification_distinguishes_states():
    row = {"Audit ID": "AUD-1", "Press/Machine #": "101", "Entry Type": "Audited"}

    assert classify_truth_cell(row, "Known Issues", "").truth_state == TRUTH_MISSING
    assert classify_truth_cell(row, "Known Issues", "Unknown / Not Checked").truth_state == TRUTH_UNKNOWN
    assert classify_truth_cell(row, "Cup Type/Material", "N/A").truth_state == TRUTH_NOT_APPLICABLE
    assert classify_truth_cell(row, "Entry Type", "Audited").truth_state == TRUTH_SYSTEM
    assert classify_truth_cell(row, "Estimated EOAT Weight", "12").truth_state == TRUTH_ESTIMATED
    assert classify_truth_cell(row, "Tubing Condition", "OK").truth_state == TRUTH_MEASURED


def test_truth_engine_treats_compatible_rows_as_derived():
    row = {"Audit ID": "AUD-C", "Press/Machine #": "102", "Entry Type": "Compatible", "Tubing Condition": "OK"}

    assert classify_truth_cell(row, "Tubing Condition", "OK").truth_state == TRUTH_COMPATIBILITY_DERIVED


def test_truth_summary_counts_rows_and_fields():
    summary = analyze_truth_from_rows(
        [
            {"Audit ID": "AUD-1", "Entry Type": "Audited", "Known Issues": ""},
            {"Audit ID": "AUD-2", "Entry Type": "Compatible", "Known Issues": "OK"},
        ],
        fields=["Audit ID", "Entry Type", "Known Issues"],
    )

    assert summary.metrics["rows_scanned"] == 2
    assert summary.state_counts[TRUTH_SYSTEM] == 2
    assert summary.state_counts[TRUTH_MISSING] == 1
    assert summary.state_counts[TRUTH_COMPATIBILITY_DERIVED] == 1


def test_truth_engine_reads_fake_workbook(usability_fake_project):
    summary = analyze_workbook_truth(usability_fake_project, fields=["Audit ID", "Entry Type", "Known Issues", "Estimated EOAT Weight"])

    assert summary.metrics["rows_scanned"] >= 1
    assert summary.state_counts
    assert not summary.warnings

