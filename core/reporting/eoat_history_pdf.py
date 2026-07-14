from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from core.atlas_record_details import RecordDetailData
from core.eoat_history import EOATHistoryEvent, EOATHistoryExportModel
from core.reporting.pdf_footer import draw_standard_pdf_footer

LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - dependency availability is environment-specific
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Image,
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
except Exception as exc:  # pragma: no cover
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


NO_HISTORY_MESSAGE = "No documented lifecycle history is currently available for this EOAT."


def eoat_history_filename(eoat_id: str, *, generated_at: datetime | None = None) -> str:
    stamp = (generated_at or datetime.now()).strftime("%Y%m%d_%H%M")
    safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", str(eoat_id or "EOAT").strip()).strip("_") or "EOAT"
    return f"EOAT_History__{safe_id}__{stamp}.pdf"


def export_eoat_history_pdf(
    detail_data: RecordDetailData,
    history: EOATHistoryExportModel,
    output_path: str | Path,
    *,
    generated_at: datetime | None = None,
    scope_label: str = "Complete documented history",
) -> Path:
    if _IMPORT_ERROR is not None:
        raise RuntimeError("EOAT history PDF export requires reportlab.") from _IMPORT_ERROR
    generated = generated_at or datetime.now()
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = _styles()
    story: list = []

    story.append(Paragraph("EOAT Atlas", styles["eyebrow"]))
    story.append(Paragraph("EOAT Lifecycle History", styles["title"]))
    story.append(Paragraph(_xml(detail_data.record_id), styles["record_id"]))
    story.append(Spacer(1, 0.12 * inch))
    cover_fields = [
        ("Exported", generated.strftime("%b %d, %Y %I:%M %p")),
        ("Export scope", scope_label),
        ("EOAT type", detail_data.subtitle),
        ("Condition / location", detail_data.condition),
        ("Plant / area", detail_data.plant_area),
        ("Photo count", str(detail_data.photo_count)),
    ]
    cover_fields.extend((field.label, _value(field.value)) for field in detail_data.hero_fields)
    story.append(_key_value_table(_dedupe_fields(cover_fields), styles))
    _profile_photo(story, detail_data, styles)

    story.append(Paragraph("EOAT Overview", styles["section"]))
    overview = [(field.label, _value(field.value)) for field in detail_data.hero_fields]
    if overview:
        story.append(_key_value_table(_dedupe_fields(overview), styles))
    else:
        story.append(Paragraph("No additional EOAT overview fields are documented.", styles["muted"]))

    story.append(Paragraph("Lifecycle History Summary", styles["section"]))
    summary = [
        ("Total documented events", str(history.total_events)),
        ("Covered date range", _date_range(history)),
        ("Event types", ", ".join(f"{kind}: {count}" for kind, count in history.event_type_counts) or "Cannot be calculated from available data"),
        ("Machines represented", ", ".join(history.machines) or "Cannot be calculated from available data"),
    ]
    story.append(_key_value_table(summary, styles))

    if not history.events:
        story.append(Paragraph("Complete Documented History", styles["section"]))
        story.append(Paragraph(NO_HISTORY_MESSAGE, styles["empty"]))
    else:
        story.append(PageBreak())
        story.append(Paragraph("Complete Documented History", styles["section"]))
        story.append(_history_table(history.events, styles))

    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        topMargin=0.62 * inch,
        bottomMargin=0.62 * inch,
        title=f"EOAT History - {detail_data.record_id}",
        author="EOAT Atlas",
    )

    def footer(canvas, document) -> None:
        draw_standard_pdf_footer(
            canvas,
            document,
            left_text=f"EOAT Atlas - {detail_data.record_id} - Exported {generated.strftime('%Y-%m-%d %H:%M')}",
            right_text=f"Page {document.page}",
        )

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    LOGGER.info("Generated EOAT lifecycle history PDF: %s", path)
    return path


def _history_table(events: tuple[EOATHistoryEvent, ...], styles: dict[str, ParagraphStyle]):
    rows = [[Paragraph("Date / Type", styles["table_header"]), Paragraph("Documented event", styles["table_header"])]]
    for event in events:
        stamp = _format_datetime(event.effective_timestamp)
        if event.is_approximate_date and stamp != "Not documented":
            stamp = f"Approx. {stamp}"
        left = Paragraph(f"<b>{_xml(event.event_type)}</b><br/>{_xml(stamp)}", styles["small"])
        lines = [f"<b>{_xml(event.title)}</b>"]
        for label, value in _event_fields(event):
            lines.append(f"<font color='#52677D'><b>{_xml(label)}:</b></font> {_xml(value)}")
        right = Paragraph("<br/>".join(lines), styles["event"])
        rows.append([left, right])
    table = Table(rows, colWidths=(1.25 * inch, 5.55 * inch), repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0A3158")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#B8CBE0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D7E1EC")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), (colors.white, colors.HexColor("#F6F9FC"))),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _event_fields(event: EOATHistoryEvent) -> list[tuple[str, str]]:
    fields = [
        ("Machine", event.machine_label),
        ("Previous machine", event.previous_machine_label),
        ("Tool #", event.tool_number),
        ("Previous tool #", event.previous_tool_number),
        ("From", event.previous_status),
        ("To", event.new_status),
        ("Reason", event.reason),
        ("Notes", event.notes),
        ("Audit ID", event.audit_id),
        ("Maintenance ID", event.maintenance_id),
        ("Recorded by", event.recorded_by),
        ("Source", event.source_type),
        ("Verification", "Verified" if event.is_verified is True else "Unverified" if event.is_verified is False else ""),
    ]
    return [(label, str(value).strip()) for label, value in fields if str(value or "").strip()]


def _key_value_table(fields: list[tuple[str, str]], styles: dict[str, ParagraphStyle]):
    rows = [[Paragraph(_xml(label), styles["key"]), Paragraph(_xml(value), styles["value"])] for label, value in fields]
    table = Table(rows, colWidths=(1.75 * inch, 5.05 * inch), hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAFC")),
                ("BOX", (0, 0), (-1, -1), 0.45, colors.HexColor("#D7E1EC")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDE6F0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _profile_photo(story: list, detail_data: RecordDetailData, styles: dict[str, ParagraphStyle]) -> None:
    for group in detail_data.photo_groups:
        for photo in group.photos:
            try:
                path = Path(photo.path)
                if path.exists() and path.is_file():
                    story.append(Spacer(1, 0.12 * inch))
                    story.append(KeepTogether([Image(str(path), width=1.45 * inch, height=1.2 * inch, kind="proportional"), Paragraph("Current indexed EOAT image", styles["muted"])]))
                    return
            except (OSError, ValueError):
                continue


def _dedupe_fields(fields: list[tuple[str, str]]) -> list[tuple[str, str]]:
    output = []
    seen = set()
    for label, value in fields:
        key = label.casefold()
        if key in seen or not str(value or "").strip():
            continue
        seen.add(key)
        output.append((label, str(value)))
    return output


def _date_range(history: EOATHistoryExportModel) -> str:
    if history.first_event_at is None or history.last_event_at is None:
        return "Cannot be calculated from available data"
    return f"{_format_datetime(history.first_event_at)} through {_format_datetime(history.last_event_at)}"


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "Not documented"
    return value.astimezone().strftime("%b %d, %Y %I:%M %p")


def _value(value: str | tuple[str, ...]) -> str:
    if isinstance(value, tuple):
        return ", ".join(str(item) for item in value if str(item).strip()) or "Not documented"
    return str(value or "Not documented")


def _xml(value: object) -> str:
    return escape(str(value or ""))


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "eyebrow": ParagraphStyle("history_eyebrow", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=9, textColor=colors.HexColor("#0073CE"), spaceAfter=3),
        "title": ParagraphStyle("history_title", parent=base["Title"], fontName="Helvetica-Bold", fontSize=24, leading=28, textColor=colors.HexColor("#111827"), spaceAfter=2),
        "record_id": ParagraphStyle("history_record", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=13, textColor=colors.HexColor("#334155")),
        "section": ParagraphStyle("history_section", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=colors.HexColor("#111827"), spaceBefore=12, spaceAfter=6),
        "key": ParagraphStyle("history_key", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=colors.HexColor("#52677D")),
        "value": ParagraphStyle("history_value", parent=base["Normal"], fontName="Helvetica", fontSize=8.5, leading=10.5, textColor=colors.HexColor("#1F2937")),
        "small": ParagraphStyle("history_small", parent=base["Normal"], fontName="Helvetica", fontSize=7.5, leading=10, textColor=colors.HexColor("#334155")),
        "event": ParagraphStyle("history_event", parent=base["Normal"], fontName="Helvetica", fontSize=8, leading=10.5, textColor=colors.HexColor("#1F2937")),
        "table_header": ParagraphStyle("history_table_header", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.white, alignment=TA_LEFT),
        "muted": ParagraphStyle("history_muted", parent=base["Normal"], fontName="Helvetica", fontSize=8, leading=10, textColor=colors.HexColor("#718096")),
        "empty": ParagraphStyle("history_empty", parent=base["Normal"], fontName="Helvetica", fontSize=10, leading=14, textColor=colors.HexColor("#334155"), borderColor=colors.HexColor("#B8CBE0"), borderWidth=0.5, borderPadding=12, backColor=colors.HexColor("#F7FAFC")),
    }


__all__ = ["NO_HISTORY_MESSAGE", "eoat_history_filename", "export_eoat_history_pdf"]
