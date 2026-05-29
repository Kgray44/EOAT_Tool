from __future__ import annotations

import json

from core.paths import resolve_project_paths
from core.project_data_service import ProjectDataService, build_machine_360_context


def test_project_data_service_lists_and_gets_audits(usability_fake_project):
    service = ProjectDataService(usability_fake_project)

    audits = service.list_audits()
    audit = service.get_audit("AUD-20260518-001")
    machines = service.list_machines()

    assert len(audits) >= 3
    assert audit is not None
    assert audit["Tool #"] == "TOOL-A"
    assert machines[:3] == ["101", "102", "103"]


def test_project_data_service_machine_context_uses_relationships(usability_fake_project):
    service = ProjectDataService(usability_fake_project)

    context = service.get_machine_context("Press 101")

    assert context["machine_number"] == "101"
    assert context["metrics"]["physical_audit_count"] == 1
    assert context["metrics"]["compatibility_entry_count"] == 0
    assert context["metrics"]["physical_verification_excludes_compatibility"] is True
    assert context["metrics"]["open_item_count"] >= 1
    assert context["metrics"]["photo_count"] == 1


def test_project_data_service_machine_360_compatibility_wrapper(usability_fake_project):
    service = ProjectDataService(usability_fake_project)

    direct = build_machine_360_context(usability_fake_project, "101")
    via_service = service.get_machine_360("101")

    assert via_service.machine_number == direct.machine_number
    assert via_service.metrics["physical_audit_count"] == direct.metrics["physical_audit_count"]


def test_project_data_service_photos_and_validation_findings(usability_fake_project):
    paths = resolve_project_paths(usability_fake_project)
    report = paths.validation_reports / "Foundation_Validation_2099-01-01_0000.json"
    report.write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "severity": "WARNING",
                        "category": "compatibility",
                        "audit_id": "AUD-20260518-001",
                        "machine_number": "Press 101",
                        "column_name": "Source Audit ID",
                        "message": "Synthetic service test finding.",
                    },
                    {
                        "severity": "INFO",
                        "category": "other",
                        "audit_id": "AUD-OTHER",
                        "machine_number": "Press 999",
                        "column_name": "Status",
                        "message": "Other machine.",
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    service = ProjectDataService(usability_fake_project)

    photos = service.get_photos_for_audit("AUD-20260518-001")
    machine_findings = service.get_validation_findings("machine", "101")
    audit_findings = service.get_validation_findings("audit", "AUD-20260518-001")

    assert len(photos) == 1
    assert photos[0]["Photo ID"] == "PHO-20260518-001"
    assert [finding["message"] for finding in machine_findings] == ["Synthetic service test finding."]
    assert [finding["message"] for finding in audit_findings] == ["Synthetic service test finding."]


def test_machine_360_context_aggregates_fake_project(usability_fake_project):
    context = build_machine_360_context(usability_fake_project, "101")

    assert context.machine_number == "101"
    assert context.metrics["physical_audit_count"] >= 1
    assert context.physical_audits
    assert context.metrics["open_item_count"] >= 0
    assert context.recommended_actions
    assert context.guided_plans


def test_machine_360_context_handles_missing_machine(usability_fake_project):
    context = build_machine_360_context(usability_fake_project, "")

    assert context.warnings
    assert context.metrics["physical_audit_count"] == 0
    assert "Create or load" in " ".join(context.recommended_actions)
