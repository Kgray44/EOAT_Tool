from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.atlas_record_details import RecordDetailData, RecordField
from core.audit.history import append_audit_history
from core.eoat_history import (
    EOATHistoryService,
    EOATHistorySourceRecord,
    LegacyAuditHistoryRepository,
    normalize_event_type,
)
from core.reporting.eoat_history_pdf import NO_HISTORY_MESSAGE, eoat_history_filename, export_eoat_history_pdf
from tests.fixtures.eoat_history import edge_case_history, history_event, mixed_history


class MemoryHistoryRepository:
    def __init__(self, records):
        self.records = tuple(records)

    def get_history(self, eoat_id: str):
        return tuple(record for record in self.records if str(record.payload.get("eoat_id", eoat_id)) == eoat_id)


def _detail(eoat_id: str = "TEST-EOAT-0001") -> RecordDetailData:
    return RecordDetailData(
        record_type="eoat",
        record_id=eoat_id,
        title=eoat_id,
        subtitle="Hybrid",
        condition="Off-Machine",
        plant_area="Plant 4",
        hero_fields=(RecordField("Current Machine", "Not Indexed"), RecordField("Tool #", "TEST-TOOL-01")),
        detail_sections=(),
        documentation_fields=(RecordField("Documentation Score", "77%"),),
        photo_groups=(),
        history_fields=(),
        summary_fields=(),
        report_sections=(),
    )


def test_legacy_repository_filters_by_eoat_and_handles_empty_and_partial_rows(tmp_path: Path) -> None:
    append_audit_history(
        tmp_path,
        "AUD-ONE",
        "created",
        {},
        {"EOAT Assembly ID": "EOAT-ONE", "Audit Date": "2026-07-01", "Auditor": "KG"},
    )
    append_audit_history(
        tmp_path,
        "AUD-TWO",
        "created",
        {},
        {"EOAT Assembly ID": "EOAT-TWO", "Audit Date": "invalid"},
    )
    repository = LegacyAuditHistoryRepository(tmp_path)
    assert [row.source_record_id for row in repository.get_history("EOAT-ONE")] == ["AUD-ONE"]
    assert repository.get_history("EOAT-MISSING") == ()


def test_service_normalizes_sorts_deduplicates_filters_and_does_not_invent_values() -> None:
    records = [
        EOATHistorySourceRecord("mysql_api", "duplicate", {"eoat_id": "E1", "event_type": "machine_install", "occurred_at": "2026-01-01T10:00:00Z", "summary": "Installed", "machine": "M2"}),
        EOATHistorySourceRecord("mysql_api", "duplicate", {"eoat_id": "E1", "event_type": "machine_install", "occurred_at": "2026-01-01T10:00:00Z", "summary": "Installed", "machine": "M2"}),
        EOATHistorySourceRecord("mysql_api", "audit-1", {"eoat_id": "E1", "event_type": "audit", "occurred_at": "2026-06-01T10:00:00Z", "summary": "Audit completed", "details": {"audit_id": "AUD-1", "recorded_by": "KG"}}),
        EOATHistorySourceRecord("mysql_api", "partial", {"eoat_id": "E1", "event_type": "unexpected"}),
        EOATHistorySourceRecord("mysql_api", "other-eoat", {"eoat_id": "E2", "event_type": "audit"}),
    ]
    service = EOATHistoryService(MemoryHistoryRepository(records))
    view = service.history_for("E1")
    assert len(view.events) == 3
    assert [event.event_type for event in view.events] == ["AUDIT", "LOCATION", "OTHER"]
    assert view.events[-1].machine_label == ""
    assert service.filter_events(view.events, search="AUD-1")[0].title == "Audit completed"
    assert len(service.filter_events(view.events, event_type="LOCATION", machine="M2")) == 1
    assert normalize_event_type("corrective maintenance") == "MAINTENANCE"
    export = service.export_model("E1", view.events)
    assert export.total_events == 3
    assert export.event_type_counts == (("AUDIT", 1), ("LOCATION", 1), ("OTHER", 1))


def test_deterministic_order_for_identical_and_invalid_timestamps() -> None:
    shared = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [history_event(1, effective_from=shared, event_timestamp=shared), history_event(2, effective_from=shared, event_timestamp=shared), history_event(3, effective_from=None, event_timestamp=None)]
    records = [
        EOATHistorySourceRecord("mysql_api", event.event_id, {"eoat_id": event.eoat_id, "event_type": event.event_type, "occurred_at": event.effective_from.isoformat() if event.effective_from else "bad", "summary": event.title})
        for event in reversed(events)
    ]
    first = EOATHistoryService(MemoryHistoryRepository(records)).history_for("TEST-EOAT-0001").events
    second = EOATHistoryService(MemoryHistoryRepository(list(reversed(records)))).history_for("TEST-EOAT-0001").events
    assert [event.event_id for event in first] == [event.event_id for event in second]


def test_history_pdf_complete_and_no_history(tmp_path: Path) -> None:
    pypdf = pytest.importorskip("pypdf")
    detail = _detail()
    service = EOATHistoryService(MemoryHistoryRepository(()))
    view = mixed_history(30)
    model = service.export_model(detail.record_id, view.events)
    output = tmp_path / eoat_history_filename(detail.record_id, generated_at=datetime(2026, 7, 13, 14, 30))
    result = export_eoat_history_pdf(detail, model, output, generated_at=datetime(2026, 7, 13, 14, 30))
    text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(str(result)).pages)
    assert result.name == "EOAT_History__TEST-EOAT-0001__20260713_1430.pdf"
    assert "EOAT Lifecycle History" in text
    assert "Physical Audit Completed" in text
    assert len(pypdf.PdfReader(str(result)).pages) > 1

    empty = tmp_path / "empty.pdf"
    export_eoat_history_pdf(detail, service.export_model(detail.record_id, ()), empty)
    empty_text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(str(empty)).pages)
    assert NO_HISTORY_MESSAGE in empty_text


def test_history_ui_empty_selection_filters_read_only_and_large_model(qapp, tmp_path: Path) -> None:
    from app.atlas.minimalist.library import RecordHistoryTab

    empty = RecordHistoryTab(_detail(), project_root=str(tmp_path), initial_view_model=mixed_history(0))
    empty.resize(1300, 650)
    empty.show()
    qapp.processEvents()
    assert empty.empty_title.text() == "No documented history"
    assert empty.export_button.isEnabled()

    view = edge_case_history()
    widget = RecordHistoryTab(_detail(), project_root=str(tmp_path), initial_view_model=view)
    widget.resize(1300, 650)
    widget.show()
    qapp.processEvents()
    assert widget.model.rowCount() == len(view.events)
    assert widget.selected_event_id
    assert widget.details_panel.findChildren(type(widget.empty_title))
    widget.search_edit.setText("Imported Legacy")
    widget._search_timer.stop()
    widget.apply_filters()
    qapp.processEvents()
    assert widget.model.rowCount() == 1
    widget.search_edit.clear()
    widget.apply_filters()
    assert widget.model.rowCount() == len(view.events)
    all_text = " ".join(button.text() for button in widget.findChildren(type(widget.export_button)))
    assert "Add Activity" not in all_text
    assert "Timeline" not in all_text
    assert "Table" not in all_text

    many = tuple(history_event(index, event_type=("AUDIT", "LOCATION", "MAINTENANCE", "STATUS")[index % 4]) for index in range(500))
    started = time.perf_counter()
    widget.view_model = replace(view, events=many, event_types=("AUDIT", "LOCATION", "MAINTENANCE", "STATUS"))
    widget.apply_filters()
    qapp.processEvents()
    elapsed = time.perf_counter() - started
    assert widget.model.rowCount() == 500
    assert elapsed < 3.0

