from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from core.atlas_record_details import RecordDetailData, RecordField, RecordPhoto, RecordSection
from core.performance import perf_timer

LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - availability is environment-specific
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
except Exception as exc:  # pragma: no cover
    colors = None
    getSampleStyleSheet = None
    Image = None
    KeepTogether = None
    Paragraph = None
    SimpleDocTemplate = None
    Spacer = None
    Table = None
    TableStyle = None
    inch = 72
    letter = (612, 792)
    TA_LEFT = 0
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def export_record_pdf(
    detail_data: RecordDetailData,
    output_path: str | Path | None = None,
    *,
    project_root: str | Path = "",
) -> Path:
    """Export a clean record report PDF and return the generated path."""
    if _IMPORT_ERROR is not None:
        raise RuntimeError("Record PDF export requires reportlab.") from _IMPORT_ERROR

    root = Path(project_root) if project_root else Path.cwd()
    path = Path(output_path) if output_path is not None else _default_output_path(root, detail_data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path = _unique_path(path)

    with perf_timer(
        root,
        "pdf.record_export.build_story",
        details={
            "ui_sensitive": "pdf_export",
            "record_type": detail_data.record_type,
            "record_id": detail_data.record_id,
            "photo_count": detail_data.photo_count,
        },
        source="pdf_record_report",
        page_tool="library_record",
    ):
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        styles = _styles()
        story: list = []
        _cover(story, styles, detail_data, generated_at, root)
        _section(story, styles, "Summary", detail_data.hero_fields)
        for section in detail_data.report_sections:
            _section(story, styles, section.title, section.fields)
        _section(story, styles, "Documentation", detail_data.documentation_fields)
        _photos(story, styles, detail_data, root)
        _section(story, styles, "History", detail_data.history_fields)
        _workbook_appendix(story, styles, detail_data)
        if detail_data.warnings:
            _section(
                story,
                styles,
                "Issues / Notes",
                tuple(RecordField(warning.title or warning.severity.title(), warning.message) for warning in detail_data.warnings[:10]),
            )

    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        rightMargin=0.62 * inch,
        leftMargin=0.62 * inch,
        topMargin=0.72 * inch,
        bottomMargin=0.62 * inch,
        title=f"EOAT Atlas {detail_data.record_type.title()} Report",
        author="EOAT Atlas",
    )
    with perf_timer(
        root,
        "pdf.record_export.doc_build",
        details={
            "ui_sensitive": "pdf_export",
            "record_type": detail_data.record_type,
            "record_id": detail_data.record_id,
            "output_path": str(path),
        },
        source="pdf_record_report",
        page_tool="library_record",
    ):
        doc.build(story, onFirstPage=_page_decorator(detail_data), onLaterPages=_page_decorator(detail_data))
    LOGGER.info("Generated EOAT Atlas record PDF: %s", path)
    return path


def record_report_filename(detail_data: RecordDetailData, *, date_stamp: str | None = None) -> str:
    stamp = date_stamp or datetime.now().strftime("%Y-%m-%d")
    type_label = {"eoat": "EOAT", "tool": "Tool", "machine": "Machine"}.get(detail_data.record_type, "Record")
    return f"{type_label}_Report_{_safe_component(detail_data.record_id)}_{stamp}.pdf"


def _cover(story: list, styles: dict[str, ParagraphStyle], detail_data: RecordDetailData, generated_at: str, project_root: Path) -> None:
    logo = _logo_path(project_root)
    if logo is not None:
        story.append(Image(str(logo), width=1.25 * inch, height=0.56 * inch, kind="proportional"))
        story.append(Spacer(1, 0.12 * inch))
    else:
        LOGGER.warning("Nolato logo asset not found.")
        story.append(Paragraph("Nolato Vermont", styles["brand"]))
    title = f"{detail_data.record_type.upper()} Report"
    story.append(Paragraph("EOAT Atlas", styles["eyebrow"]))
    story.append(Paragraph(title, styles["title"]))
    story.append(Paragraph(_xml(detail_data.record_id), styles["record_id"]))
    story.append(Spacer(1, 0.12 * inch))
    rows = (
        RecordField("Generated", generated_at),
        RecordField("Record", detail_data.title),
        RecordField("Description", detail_data.subtitle),
        RecordField("Condition / Location", detail_data.condition),
        RecordField("Plant / Area", detail_data.plant_area),
        RecordField("Photo Count", str(detail_data.photo_count)),
    )
    story.append(_kv_table(rows, styles))
    story.append(Spacer(1, 0.22 * inch))


def _section(story: list, styles: dict[str, ParagraphStyle], title: str, fields: tuple[RecordField, ...]) -> None:
    story.append(KeepTogether([Paragraph(_xml(title), styles["section"]), _kv_table(fields, styles), Spacer(1, 0.14 * inch)]))


def _photos(story: list, styles: dict[str, ParagraphStyle], detail_data: RecordDetailData, project_root: Path) -> None:
    story.append(Paragraph("Photos", styles["section"]))
    existing = [photo for group in detail_data.photo_groups for photo in group.photos if photo.exists]
    if not existing:
        story.append(Paragraph("No photos indexed for this record.", styles["body"]))
        story.append(Spacer(1, 0.14 * inch))
        return
    story.append(Paragraph(f"{len(existing)} linked photo(s). First images are shown below.", styles["body"]))
    rows = []
    row = []
    for photo in existing[:6]:
        row.append(_photo_cell(photo, styles, project_root))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        while len(row) < 3:
            row.append("")
        rows.append(row)
    table = Table(rows, colWidths=(2.05 * inch, 2.05 * inch, 2.05 * inch))
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.14 * inch))


def _workbook_appendix(story: list, styles: dict[str, ParagraphStyle], detail_data: RecordDetailData) -> None:
    if not detail_data.workbook_sections:
        return
    story.append(Paragraph("Workbook Data Appendix", styles["section"]))
    story.append(
        Paragraph(
            "Matched source rows from the Master Tracker workbook and Press Capacity reference are included below.",
            styles["body"],
        )
    )
    story.append(Spacer(1, 0.08 * inch))
    for section in detail_data.workbook_sections:
        if not section.rows:
            continue
        story.append(Paragraph(_xml(section.title), styles["appendix_heading"]))
        story.append(Paragraph(f"{len(section.rows)} matched row(s).", styles["muted"]))
        for row in section.rows:
            story.append(Paragraph(_xml(row.label), styles["caption"]))
            story.append(_kv_table(row.fields, styles))
            story.append(Spacer(1, 0.08 * inch))


def _photo_cell(photo: RecordPhoto, styles: dict[str, ParagraphStyle], project_root: Path):
    elements = []
    with perf_timer(
        project_root,
        "pdf.record_export.photo_embed",
        details={"ui_sensitive": "pdf_export_photo", "path": photo.path, "photo_id": photo.photo_id or photo.filename},
        source="pdf_record_report",
        page_tool="library_record",
    ):
        try:
            elements.append(Image(photo.path, width=1.8 * inch, height=1.15 * inch, kind="proportional"))
        except Exception:
            elements.append(Paragraph("Thumbnail unavailable", styles["muted"]))
    caption = photo.category or photo.filename
    meta = photo.date_taken or photo.association or photo.filename
    elements.append(Paragraph(_xml(caption), styles["caption"]))
    elements.append(Paragraph(_xml(meta), styles["muted"]))
    return elements


def _kv_table(fields: tuple[RecordField, ...], styles: dict[str, ParagraphStyle]):
    rows = []
    for field in fields:
        rows.append(
            [
                Paragraph(_xml(field.label), styles["key"]),
                Paragraph(_xml(_value_text(field.value)), styles["value" if field.tone != "muted" else "muted"]),
            ]
        )
    table = Table(rows, colWidths=(1.75 * inch, 4.55 * inch), hAlign="LEFT")
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


def _page_decorator(detail_data: RecordDetailData):
    def decorate(canvas, doc) -> None:
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#C8D6E5"))
        canvas.setLineWidth(0.5)
        canvas.line(doc.leftMargin, 0.48 * inch, letter[0] - doc.rightMargin, 0.48 * inch)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#5C6E82"))
        canvas.drawString(doc.leftMargin, 0.30 * inch, f"EOAT Atlas - {detail_data.record_id}")
        canvas.drawRightString(letter[0] - doc.rightMargin, 0.30 * inch, f"Page {doc.page}")
        canvas.restoreState()

    return decorate


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "brand": ParagraphStyle("brand", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=colors.HexColor("#1E2A36")),
        "eyebrow": ParagraphStyle("eyebrow", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=9, leading=11, textColor=colors.HexColor("#0073CE"), spaceAfter=3),
        "title": ParagraphStyle("title", parent=base["Title"], fontName="Helvetica-Bold", fontSize=24, leading=28, textColor=colors.HexColor("#111827"), spaceAfter=2),
        "record_id": ParagraphStyle("record_id", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=colors.HexColor("#334155")),
        "section": ParagraphStyle("section", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=colors.HexColor("#111827"), spaceBefore=8, spaceAfter=6),
        "appendix_heading": ParagraphStyle("appendix_heading", parent=base["Heading3"], fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=colors.HexColor("#0073CE"), spaceBefore=8, spaceAfter=3),
        "key": ParagraphStyle("key", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=colors.HexColor("#52677D"), alignment=TA_LEFT),
        "value": ParagraphStyle("value", parent=base["Normal"], fontName="Helvetica", fontSize=8.5, leading=10.5, textColor=colors.HexColor("#1F2937")),
        "body": ParagraphStyle("body", parent=base["Normal"], fontName="Helvetica", fontSize=9, leading=12, textColor=colors.HexColor("#334155")),
        "caption": ParagraphStyle("caption", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=7.6, leading=9, textColor=colors.HexColor("#1F2937"), spaceBefore=3),
        "muted": ParagraphStyle("muted", parent=base["Normal"], fontName="Helvetica", fontSize=7.6, leading=9, textColor=colors.HexColor("#718096")),
    }


def _default_output_path(project_root: Path, detail_data: RecordDetailData) -> Path:
    output_dir = project_root / "output" / "pdf"
    return output_dir / record_report_filename(detail_data)


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}_{datetime.now().strftime('%H%M%S')}{suffix}")


def _logo_path(project_root: Path) -> Path | None:
    candidates = [
        project_root / "docs" / "nolato_logo.png",
        Path(__file__).resolve().parents[2] / "docs" / "nolato_logo.png",
    ]
    return next((path for path in candidates if path.exists()), None)


def _safe_component(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "record").strip())
    return text.strip("_") or "record"


def _value_text(value: str | tuple[str, ...]) -> str:
    if isinstance(value, tuple):
        items = [str(item) for item in value if str(item or "").strip()]
        if len(items) > 12:
            return ", ".join(items[:12]) + f", +{len(items) - 12} more"
        return ", ".join(items) or "Not Indexed"
    return str(value or "Not Indexed")


def _xml(value: str) -> str:
    return escape(str(value or ""))


__all__ = ["export_record_pdf", "record_report_filename"]
