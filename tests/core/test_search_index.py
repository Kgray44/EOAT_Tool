from __future__ import annotations

from core.search_index import build_search_corpus_counts, search_index


def test_search_index_returns_explained_audit_field_and_machine_matches(usability_fake_project):
    results = search_index(usability_fake_project, "Vacuum")

    assert results
    assert all(result.matched_source for result in results)
    assert all(result.matched_field for result in results)
    assert all(result.snippet for result in results)
    assert all(result.rank_score > 0 for result in results)
    assert all(result.why_matched for result in results)
    assert any(result.result_type == "field" and result.matched_field == "EOAT Type" for result in results)
    assert any(
        result.result_type in {"machine", "press_group"} for result in search_index(usability_fake_project, "101")
    )


def test_search_index_indexes_reports_and_counts(usability_fake_project):
    report_dir = usability_fake_project / "00_Project_Admin" / "Validation_Reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = report_dir / "Foundation_Validation_Search_Test.md"
    report.write_text("# Validation\n\nSensor routing review.", encoding="utf-8")

    results = search_index(usability_fake_project, "Sensor routing")
    counts = build_search_corpus_counts(usability_fake_project)

    assert any(result.result_type == "report" or result.matched_source == "Reports" for result in results)
    assert counts["audits"] > 0
    assert counts["reports"] > 0
