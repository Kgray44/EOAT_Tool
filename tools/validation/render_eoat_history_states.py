from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from app.atlas.minimalist.library import RecordHistoryTab
from app.atlas.minimalist.theme import set_active_minimalist_theme
from core.atlas_record_details import RecordDetailData, RecordField
from core.eoat_history import EOATHistoryEvent, EOATHistoryViewModel


def detail() -> RecordDetailData:
    return RecordDetailData(
        record_type="eoat",
        record_id="HISTORY-VALIDATION-EOAT",
        title="HISTORY-VALIDATION-EOAT",
        subtitle="Hybrid EOAT",
        condition="Active / verified",
        plant_area="Development validation",
        hero_fields=(RecordField("Revision", "C"), RecordField("Connection Type", "Pneumatic")),
        detail_sections=(),
        documentation_fields=(),
        photo_groups=(),
        history_fields=(),
        summary_fields=(),
        report_sections=(),
    )


def events() -> tuple[EOATHistoryEvent, ...]:
    now = datetime(2026, 7, 14, 12, tzinfo=timezone.utc)
    definitions = (
        ("EOAT_RESTORED", "ARCHIVE_ACTIVITY", "EOAT restored", {}),
        ("DOCUMENT_ADDED", "DOCUMENTS_AND_PHOTOS", "Setup drawing added", {"document_reference": "DOC-EOAT-1042"}),
        ("MAINTENANCE_COMPLETED", "MAINTENANCE", "Preventive maintenance completed", {"maintenance_id": "PM-2048", "notes": "Vacuum cups inspected and replaced."}),
        ("AUDIT_COMPLETED", "AUDITS", "Physical audit completed", {"audit_id": "AUD-2026-0714", "is_verified": True}),
        ("EOAT_MOVED_TO_STORAGE", "INSTALLATIONS", "EOAT moved to storage", {"storage_location": "CRIB-A-12", "reason": "Production run completed"}),
        ("EOAT_REMOVED_FROM_MACHINE", "INSTALLATIONS", "EOAT removed from Machine 40", {"machine_id": "Machine 40"}),
        ("EOAT_INSTALLED_ON_MACHINE", "INSTALLATIONS", "EOAT installed on Machine 40", {"machine_id": "Machine 40", "tool_number": "TOOL-881", "robot_number": "R-40"}),
        ("COMPATIBILITY_VERIFIED", "ENGINEERING_CHANGES", "Compatibility verified", {"machine_id": "Machine 40", "recorded_by": "Development Engineer"}),
        ("TAG_ASSIGNED", "TAGS_AND_ANNOTATIONS", "Engineering review tag assigned", {}),
        ("ANNOTATION_ADDED", "TAGS_AND_ANNOTATIONS", "Engineering note added", {"description": "Clearance checked against the current robot dress pack."}),
        ("EOAT_UPDATED", "ENGINEERING_CHANGES", "Connection type corrected", {"previous_values": {"connection_type": "Electric"}, "new_values": {"connection_type": "Pneumatic"}}),
        ("EOAT_CREATED", "ENGINEERING_CHANGES", "EOAT record created", {}),
    )
    return tuple(
        EOATHistoryEvent(
            event_id=f"visual-{index:02d}",
            eoat_id="HISTORY-VALIDATION-EOAT",
            event_type=event_type,
            event_category=category,
            title=title,
            event_timestamp=now - timedelta(days=index * 12),
            effective_from=now - timedelta(days=index * 12),
            source_type="validation_fixture",
            source_record_id=f"VIS-{index:04d}",
            **values,
        )
        for index, (event_type, category, title, values) in enumerate(definitions)
    )


def view(items: tuple[EOATHistoryEvent, ...]) -> EOATHistoryViewModel:
    return EOATHistoryViewModel(
        "HISTORY-VALIDATION-EOAT",
        items,
        tuple(sorted({item.event_type for item in items})),
        tuple(sorted({item.machine_label for item in items if item.machine_label})),
    )


def render(
    app: QApplication,
    output: Path,
    name: str,
    items: tuple[EOATHistoryEvent, ...],
    *,
    theme: str,
    width: int,
    height: int,
    selected_type: str | None = None,
) -> None:
    set_active_minimalist_theme(theme)
    widget = RecordHistoryTab(detail(), project_root=str(output), initial_view_model=view(items))
    widget.apply_theme_preference(theme)
    widget.resize(width, height)
    widget.show()
    for _ in range(4):
        app.processEvents()
    if selected_type:
        row = next(index for index, item in enumerate(items) if item.event_type == selected_type)
        widget.list_view.setCurrentIndex(widget.model.index(row, 0))
        app.processEvents()
    target = output / f"{name}.png"
    if not widget.grab().save(str(target), "PNG"):
        raise RuntimeError(f"Could not save {target}")
    widget.close()
    widget.deleteLater()
    app.processEvents()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=820)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    for font_name in ("segoeui.ttf", "segoeuib.ttf", "segoeuisb.ttf"):
        QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font_name))
    app.setFont(QFont("Segoe UI", 10))
    history = events()
    dimensions = {"width": args.width, "height": args.height}
    render(app, output, "no_history_dark", (), theme="dark", **dimensions)
    render(app, output, "single_event_dark", history[-1:], theme="dark", **dimensions)
    render(app, output, "many_events_dark", history, theme="dark", **dimensions)
    render(app, output, "selected_installation_dark", history, theme="dark", selected_type="EOAT_INSTALLED_ON_MACHINE", **dimensions)
    render(app, output, "selected_maintenance_dark", history, theme="dark", selected_type="MAINTENANCE_COMPLETED", **dimensions)
    render(app, output, "selected_document_dark", history, theme="dark", selected_type="DOCUMENT_ADDED", **dimensions)
    render(app, output, "many_events_light", history, theme="light", **dimensions)
    render(app, output, "selected_installation_light", history, theme="light", selected_type="EOAT_INSTALLED_ON_MACHINE", **dimensions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
