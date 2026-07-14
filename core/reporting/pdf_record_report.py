from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from core.atlas_record_details import RecordDetailData, RecordField, RecordPhoto, RecordSection
from core.performance import perf_timer
from core.reporting.pdf_footer import draw_standard_pdf_footer
from core.reporting.pdf_image_utils import PdfImageResult, prepare_image_for_pdf
from core.reporting.record_report_options import ReportOptions

LOGGER = logging.getLogger(__name__)
_LAST_EXPORT_IMAGE_WARNINGS: dict[str, tuple[PdfImageResult, ...]] = {}

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
    options: ReportOptions | None = None,
) -> Path:
    """Export a clean record report PDF and return the generated path."""
    if _IMPORT_ERROR is not None:
        raise RuntimeError("Record PDF export requires reportlab.") from _IMPORT_ERROR

    options = options or ReportOptions()
    root = Path(project_root) if project_root else Path.cwd()
    requested_output = output_path if output_path is not None else options.output_path
    path = Path(requested_output) if requested_output is not None else _default_output_path(root, detail_data)
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
        if options.include_summary:
            _section(story, styles, "Summary", detail_data.hero_fields)
        for section in detail_data.report_sections:
            if _include_report_section(section, options):
                _section(story, styles, section.title, section.fields)
        if options.include_documentation:
            _section(story, styles, "Documentation", detail_data.documentation_fields)
        skipped_photo_results: list[PdfImageResult] = []
        if options.include_photos or options.include_photo_thumbnails or options.include_photo_appendix or options.include_missing_photo_status:
            skipped_photo_results = _photos(story, styles, detail_data, root, options)
        if options.include_history:
            _section(story, styles, "History", detail_data.history_fields)
        if options.include_workbook_appendix:
            _workbook_appendix(story, styles, detail_data)
        if options.include_notes and detail_data.warnings:
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
        "pdf.report_build",
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
    _LAST_EXPORT_IMAGE_WARNINGS[str(path)] = tuple(skipped_photo_results)
    LOGGER.info("Generated EOAT Atlas record PDF: %s", path)
    return path


def pdf_image_warnings_for(pdf_path: str | Path) -> tuple[PdfImageResult, ...]:
    return _LAST_EXPORT_IMAGE_WARNINGS.get(str(Path(pdf_path)), ())


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
    if not fields:
        return
    story.append(KeepTogether([Paragraph(_xml(title), styles["section"]), _kv_table(fields, styles), Spacer(1, 0.14 * inch)]))


def _include_report_section(section: RecordSection, options: ReportOptions) -> bool:
    relationship = _section_is_relationship(section.title)
    if relationship:
        return options.include_relationships
    return options.include_details


def _section_is_relationship(title: str) -> bool:
    lowered = str(title or "").casefold()
    return any(token in lowered for token in ("compatibility", "relationship", "current setup"))


def _photos(story: list, styles: dict[str, ParagraphStyle], detail_data: RecordDetailData, project_root: Path, options: ReportOptions) -> list[PdfImageResult]:
    story.append(Paragraph("Photos", styles["section"]))
    all_photos = [photo for group in detail_data.photo_groups for photo in group.photos]
    resolved: list[tuple[RecordPhoto, Path]] = []
    missing: list[RecordPhoto] = []
    for photo in all_photos:
        resolved_path = _resolve_existing_photo_path(photo)
        if resolved_path is None:
            missing.append(photo)
        else:
            resolved.append((photo, resolved_path))
    if not resolved:
        message = "Photo references are indexed for this record, but the source files could not be loaded." if all_photos else "No photos indexed for this record."
        story.append(Paragraph(message, styles["body"]))
        if options.include_missing_photo_status and missing:
            _missing_photos(story, styles, missing)
        story.append(Spacer(1, 0.14 * inch))
        return []
    max_size = (1800, 1350) if options.include_photo_appendix else (1200, 900)
    prepared: list[tuple[RecordPhoto, PdfImageResult]] = []
    skipped: list[tuple[RecordPhoto, PdfImageResult]] = []
    for photo, path in resolved:
        result = prepare_image_for_pdf(path, project_root, max_size=max_size)
        prepared.append((photo, result))
        if not result.ok:
            skipped.append((photo, result))

    show_contact_sheet = options.include_photos and options.include_photo_thumbnails
    photo_limit = len(prepared) if options.include_photo_appendix else (9 if options.detailed else 6)
    visible = prepared[:photo_limit] if (show_contact_sheet or options.include_photo_appendix) else []
    usable_count = sum(1 for _photo, result in prepared if result.ok)
    skipped_count = len(skipped)
    intro = f"{len(resolved)} linked photo(s); {usable_count} prepared for this report."
    if skipped_count:
        intro += f" {skipped_count} photo(s) skipped or shown as unavailable."
    if not visible:
        intro += " Photo thumbnails are not included."
    elif len(visible) < len(prepared):
        intro += f" First {len(visible)} are shown below."
    elif options.include_photo_appendix:
        intro += " Full photo appendix is included below."
    story.append(Paragraph(intro, styles["body"]))
    if visible:
        rows = []
        row = []
        for photo, result in visible:
            row.append(_photo_cell(photo, result, styles, project_root))
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
    if skipped:
        _skipped_photos(story, styles, skipped)
    if options.include_missing_photo_status and missing:
        _missing_photos(story, styles, missing)
    story.append(Spacer(1, 0.14 * inch))
    return [result for _photo, result in skipped]


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


def _photo_cell(photo: RecordPhoto, result: PdfImageResult, styles: dict[str, ParagraphStyle], project_root: Path):
    elements = []
    with perf_timer(
        project_root,
        "pdf.generation.image_embed",
        details={
            "ui_sensitive": "pdf_export_photo",
            "path": str(result.original_path or ""),
            "safe_path": str(result.pdf_safe_path or ""),
            "photo_id": photo.photo_id or photo.filename,
            "skipped": result.skipped,
        },
        source="pdf_record_report",
        page_tool="library_record",
    ):
        if result.ok and result.pdf_safe_path:
            try:
                elements.append(Image(str(result.pdf_safe_path), width=1.8 * inch, height=1.15 * inch, kind="proportional"))
            except Exception as exc:
                LOGGER.warning("Could not embed prepared PDF photo %s: %s", result.pdf_safe_path, exc)
                elements.append(_photo_unavailable_box(styles, f"Prepared image could not be embedded: {exc}"))
        else:
            elements.append(_photo_unavailable_box(styles, result.reason or "Unsupported image format or decode failed"))
    caption = photo.category or photo.filename
    meta = photo.date_taken or photo.association or photo.filename
    elements.append(Paragraph(_xml(caption), styles["caption"]))
    elements.append(Paragraph(_xml(meta), styles["muted"]))
    return elements


def _photo_unavailable_box(styles: dict[str, ParagraphStyle], reason: str):
    reason_text = str(reason or "Image unavailable")
    if len(reason_text) > 96:
        reason_text = f"{reason_text[:93].rstrip()}..."
    table = Table(
        [
            [Paragraph("Image unavailable", styles["caption"])],
            [Paragraph(_xml(reason_text), styles["muted"])],
        ],
        colWidths=(1.8 * inch,),
        rowHeights=(0.44 * inch, 0.66 * inch),
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#C9D7E8")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _skipped_photos(story: list, styles: dict[str, ParagraphStyle], skipped: list[tuple[RecordPhoto, PdfImageResult]]) -> None:
    if not skipped:
        return
    story.append(Spacer(1, 0.08 * inch))
    story.append(Paragraph("Photos skipped or unavailable", styles["appendix_heading"]))
    for photo, result in skipped[:12]:
        label = photo.filename or photo.category or photo.photo_id or "Indexed photo"
        reason = result.reason or "Unsupported image format or decode failed"
        story.append(Paragraph(_xml(f"{label}: {reason}"), styles["muted"]))
    if len(skipped) > 12:
        story.append(Paragraph(_xml(f"+{len(skipped) - 12} more skipped photo reference(s)."), styles["muted"]))


def _missing_photos(story: list, styles: dict[str, ParagraphStyle], photos: list[RecordPhoto]) -> None:
    if not photos:
        return
    story.append(Spacer(1, 0.08 * inch))
    story.append(Paragraph("Missing photo status", styles["appendix_heading"]))
    for photo in photos[:12]:
        label = photo.category or photo.filename or photo.photo_id or "Indexed photo"
        candidate = next((path for path in (*photo.path_candidates, photo.path) if str(path or "").strip()), "")
        suffix = f" - {candidate}" if candidate else ""
        story.append(Paragraph(_xml(f"{label}: source file unavailable{suffix}"), styles["muted"]))
    if len(photos) > 12:
        story.append(Paragraph(_xml(f"+{len(photos) - 12} more missing photo reference(s)."), styles["muted"]))


def _resolve_existing_photo_path(photo: RecordPhoto) -> Path | None:
    candidates = [*photo.path_candidates, photo.path]
    seen: set[str] = set()
    for raw in candidates:
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        path = Path(text)
        try:
            if path.exists() and path.is_file():
                return path
        except OSError:
            LOGGER.debug("Photo path could not be checked during PDF export: %s", path)
    return None


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
        draw_standard_pdf_footer(
            canvas,
            doc,
            left_text=f"EOAT Atlas - {detail_data.record_id}",
            right_text=f"Page {doc.page}",
        )

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


__all__ = ["ReportOptions", "export_record_pdf", "pdf_image_warnings_for", "record_report_filename"]
