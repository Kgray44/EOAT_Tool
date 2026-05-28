from __future__ import annotations

import json

from core.annotations.service import AnnotationService
from core.paths import resolve_project_paths
from core.search import SearchFilters, search_project, sqlite_fts_status


def test_search_returns_audits_machines_reports_and_photos(usability_fake_project):
    results = search_project(usability_fake_project, "Press 101")
    result_types = {result.result_type for result in results}

    assert "audit" in result_types
    assert "machine" in result_types
    assert "photo" in result_types
    assert any(result.audit_id == "AUD-20260518-001" for result in results)


def test_search_includes_cup_count_tooling_value(usability_fake_project):
    results = search_project(usability_fake_project, "# of Cups: 8")

    assert any(result.result_type == "audit" and result.audit_id == "AUD-20260518-001" for result in results)


def test_search_returns_notes_and_tags(usability_fake_project):
    service = AnnotationService(usability_fake_project)
    tag = service.create_tag("Needs Review", "yellow", description="Synthetic tag for search")
    target = service.create_or_get_target("audit", audit_id="AUD-20260518-001", machine_id="101", target_label="Audit search target")
    note = service.create_note("Searchable follow-up", "Review this synthetic audit note.", target_ids=[target.id])
    service.assign_tag_to_target(tag.id, target.id, comment="Synthetic searchable tag assignment")
    service.link_note_to_tag(note.id, tag.id)

    results = search_project(usability_fake_project, "Searchable")
    result_types = {result.result_type for result in results}

    assert "note" in result_types
    assert "tag" in result_types
    assert any(result.audit_id == "AUD-20260518-001" for result in results)


def test_search_tolerates_missing_optional_sources(minimal_fake_project):
    results = search_project(minimal_fake_project, "anything")

    assert results == []
    assert sqlite_fts_status(minimal_fake_project)["mode"] == "like_fallback"


def test_search_filters_by_type_machine_status_and_validation(usability_fake_project):
    paths = resolve_project_paths(usability_fake_project)
    payload = {
        "findings": [
            {
                "finding_id": "vf_demo",
                "severity": "WARNING",
                "category": "demo",
                "sheet_name": "EOAT Inventory",
                "audit_id": "AUD-20260518-001",
                "machine_number": "101",
                "column_name": "Status",
                "message": "Synthetic validation warning for search.",
                "recommended_action": "Review synthetic warning.",
            }
        ]
    }
    (paths.validation_reports / "Foundation_Validation_2026-05-18_0800.json").write_text(json.dumps(payload), encoding="utf-8")

    results = search_project(
        usability_fake_project,
        "validation warning",
        SearchFilters(result_types=("validation",), machine="101", severity="WARNING"),
    )

    assert len(results) == 1
    assert results[0].result_type == "validation"
    assert results[0].audit_id == "AUD-20260518-001"
