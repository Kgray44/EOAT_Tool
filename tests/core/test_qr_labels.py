from __future__ import annotations

from pathlib import Path

from core.final_handoff import collect_handoff_sources
from core.qr_labels import audit_qr_value, build_qr_labels, export_qr_label_sheet, machine_qr_value, validate_qr_value


def test_qr_values_are_minimal_routes_only():
    assert machine_qr_value("Press 123") == "eoat://machine/123"
    assert audit_qr_value("EOAT-2026-0001") == "eoat://audit/EOAT-2026-0001"
    assert validate_qr_value("eoat://machine/123")
    assert validate_qr_value("eoat://audit/EOAT-2026-0001")
    assert not validate_qr_value("eoat://machine/123?plant=VT&tool=SECRET")
    assert not validate_qr_value("https://example.com/eoat/123")


def test_build_qr_labels_from_fake_project_excludes_operational_details(usability_fake_project):
    labels = build_qr_labels(usability_fake_project)

    assert labels
    assert any(label.qr_value.startswith("eoat://machine/") for label in labels)
    assert any(label.qr_value.startswith("eoat://audit/") for label in labels)
    combined_values = "\n".join(label.qr_value for label in labels).casefold()
    assert "plant" not in combined_values
    assert "tool" not in combined_values
    assert "part" not in combined_values
    assert "gwplastics" not in combined_values


def test_export_qr_label_sheet_writes_printable_outputs_and_handoff_source(fake_project):
    result = export_qr_label_sheet(fake_project, machines=["Press 44"], audit_ids=["EOAT-2026-0001"], log_activity=False)

    assert result.success is True
    assert result.metrics["label_count"] == 2
    assert any(path.endswith(".svg") for path in result.output_reports)
    assert any(path.endswith(".md") for path in result.output_reports)
    assert all(Path(path).is_relative_to(fake_project) for path in result.output_reports)
    values_text = next(Path(path) for path in result.output_reports if path.endswith(".md")).read_text(encoding="utf-8")
    assert "eoat://machine/44" in values_text
    assert "eoat://audit/EOAT-2026-0001" in values_text

    sources = collect_handoff_sources(fake_project)
    assert any("QR_Labels" in str(path) for path in sources["qr_labels"])
