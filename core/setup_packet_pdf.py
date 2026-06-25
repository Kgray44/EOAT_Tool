from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from .atlas_setup_packets import (
    COMPATIBILITY_MANUAL_OVERRIDE,
    COMPATIBILITY_NOT_CONFIRMED,
    PACKET_TYPE_DOCUMENTATION_REVIEW,
    PACKET_TYPE_MAINTENANCE_PM,
    PACKET_TYPE_SETUP_VERIFICATION,
    PHOTO_NONE,
    SetupPacketContext,
    SetupPacketExportResult,
    atlas_setup_packet_dir,
    build_documentation_checklist,
    build_pm_checklist,
    build_standard_changeover_checklist,
    build_verification_checklist,
    compatible_eoats_for_machine,
    compatible_eoats_for_tool,
    compatible_machines_for_eoat,
    compatible_machines_for_tool,
    compatible_tools_for_eoat,
    compatible_tools_for_machine,
    row_first,
)
from .atlas_utils import normalized_eoat_key, normalized_machine_key, normalized_tool_key

LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - import availability is environment-specific
    from PIL import Image as PILImage
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
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
except Exception as exc:  # pragma: no cover - exercised only if dependency missing
    PILImage = None
    Image = None
    PageBreak = None
    Paragraph = None
    SimpleDocTemplate = None
    Spacer = None
    Table = None
    TableStyle = None
    colors = None
    getSampleStyleSheet = None
    inch = 72
    letter = (612, 792)
    TA_CENTER = 1
    TA_LEFT = 0
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def export_setup_packet_pdf(
    context: SetupPacketContext,
    output_dir: str | Path | None = None,
) -> SetupPacketExportResult:
    if _IMPORT_ERROR is not None:
        raise RuntimeError("Setup Packet PDF export requires reportlab and Pillow.") from _IMPORT_ERROR
    target_dir = Path(output_dir) if output_dir is not None else atlas_setup_packet_dir(context.project_root)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = _unique_packet_path(target_dir, context)
    story = _build_story(context)
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        rightMargin=0.62 * inch,
        leftMargin=0.62 * inch,
        topMargin=0.88 * inch,
        bottomMargin=0.72 * inch,
        title="EOAT Atlas Setup Packet",
        author="EOAT Atlas",
    )
    doc.build(story, onFirstPage=_page_decorator(context), onLaterPages=_page_decorator(context))
    LOGGER.info("Generated EOAT Atlas setup packet PDF: %s", path)
    return SetupPacketExportResult(path=path, message=f"Generated setup packet: {path}")


def setup_packet_filename(context: SetupPacketContext, *, timestamp: str | None = None) -> str:
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    return (
        f"Setup_Packet_Machine_{_safe_component(context.machine_id)}"
        f"_Tool_{_safe_component(context.tool_id)}"
        f"_EOAT_{_safe_component(context.eoat_id)}_{stamp}.pdf"
    )


def _build_story(context: SetupPacketContext) -> list:
    styles = _styles()
    story: list = []
    _cover_page(story, styles, context)
    packet_type = context.options.packet_type
    if packet_type == PACKET_TYPE_SETUP_VERIFICATION:
        _compatibility_summary(story, styles, context)
        _ids_summary(story, styles, context)
        _robot_information(story, styles, context)
        _eoat_information(story, styles, context, key_only=True)
        _checklist_section(story, styles, "Setup Verification Checklist", build_verification_checklist())
        _warnings_section(story, styles, context)
        _source_summary(story, styles, context)
    elif packet_type == PACKET_TYPE_MAINTENANCE_PM:
        _eoat_information(story, styles, context)
        _machine_information(story, styles, context, compact=True)
        _robot_information(story, styles, context)
        story.append(PageBreak())
        _pneumatics_section(story, styles, context)
        _checklist_section(story, styles, "Maintenance / PM Checklist", build_pm_checklist())
        story.append(PageBreak())
        _photos_section(story, styles, context)
        _standards_section(story, styles, context)
        _warnings_section(story, styles, context)
        _source_summary(story, styles, context)
    elif packet_type == PACKET_TYPE_DOCUMENTATION_REVIEW:
        _ids_summary(story, styles, context)
        _documentation_review_section(story, styles, context)
        _photos_section(story, styles, context)
        _standards_section(story, styles, context)
        _checklist_section(story, styles, "Documentation Checklist", build_documentation_checklist())
        _warnings_section(story, styles, context)
        _source_summary(story, styles, context)
    else:
        _compatibility_summary(story, styles, context)
        _machine_information(story, styles, context)
        _robot_information(story, styles, context)
        story.append(PageBreak())
        _tool_information(story, styles, context)
        _eoat_information(story, styles, context)
        story.append(PageBreak())
        _pneumatics_section(story, styles, context)
        story.append(PageBreak())
        _checklist_section(story, styles, "Standard Changeover Checklist", build_standard_changeover_checklist())
        story.append(PageBreak())
        _checklist_section(story, styles, "Documentation Checklist", build_documentation_checklist())
        story.append(PageBreak())
        _photos_section(story, styles, context)
        _standards_section(story, styles, context)
        _warnings_section(story, styles, context)
        _source_summary(story, styles, context)
    return story


def _cover_page(story: list, styles: dict[str, ParagraphStyle], context: SetupPacketContext) -> None:
    story.append(Spacer(1, 0.24 * inch))
    logo_path = Path(context.project_root) / "docs" / "nolato_logo.png"
    repo_logo = Path(__file__).resolve().parents[1] / "docs" / "nolato_logo.png"
    if not logo_path.exists() and repo_logo.exists():
        logo_path = repo_logo
    if logo_path.exists():
        story.append(Image(str(logo_path), width=1.35 * inch, height=0.72 * inch, kind="proportional"))
        story.append(Spacer(1, 0.18 * inch))
    story.append(Paragraph("Setup Packet / Changeover Packet", styles["cover_title"]))
    story.append(Spacer(1, 0.08 * inch))
    story.append(Paragraph("Prepared by EOAT Atlas", styles["subtitle"]))
    story.append(Spacer(1, 0.32 * inch))
    rows = [
        ("Machine", context.machine_id),
        ("Tool / Mold / Part", context.tool_id),
        ("EOAT ID", context.eoat_id),
        ("Part name / description", _part_description(context)),
        ("Compatibility status", context.validation.status),
        ("Manual override", "Yes" if context.validation.manual_override_used else "No"),
        ("Generated", context.generated_at),
        ("Documentation score", f"{context.documentation_score}%"),
        ("Photo count", str(context.photo_count)),
        ("Warning count", str(context.warning_count)),
        ("Packet type", context.packet_type_label),
        ("Photo inclusion", context.photo_inclusion_label),
    ]
    story.append(_kv_table(rows, styles, col_widths=(2.05 * inch, 4.15 * inch)))
    if context.validation.status in {COMPATIBILITY_MANUAL_OVERRIDE, COMPATIBILITY_NOT_CONFIRMED}:
        story.append(Spacer(1, 0.22 * inch))
        story.append(_warning_box(_compatibility_warning_text(context), styles))
    story.append(PageBreak())


def _compatibility_summary(story: list, styles: dict[str, ParagraphStyle], context: SetupPacketContext) -> None:
    _section_title(story, styles, "Compatibility Summary")
    story.append(
        _kv_table(
            [
                ("Relationship", f"Machine {context.machine_id} -> Tool {context.tool_id} -> EOAT {context.eoat_id}"),
                ("Compatibility status", context.validation.status),
                ("Compatibility source", _join(context.validation.sources) or "Not confirmed by available indexes"),
                ("Manual override used", "Yes" if context.validation.manual_override_used else "No"),
            ],
            styles,
        )
    )
    check_rows = [(check.relationship, check.status, check.source or _join(check.notes) or "No source") for check in context.validation.checks]
    story.append(Spacer(1, 0.14 * inch))
    story.append(_plain_table(("Relationship", "Status", "Source / Note"), check_rows, styles, col_widths=(1.7 * inch, 1.45 * inch, 3.35 * inch)))
    if context.validation.status in {COMPATIBILITY_MANUAL_OVERRIDE, COMPATIBILITY_NOT_CONFIRMED}:
        story.append(Spacer(1, 0.12 * inch))
        story.append(_warning_box(_compatibility_warning_text(context), styles))
    story.append(Spacer(1, 0.12 * inch))
    story.append(
        _kv_table(
            [
                ("Compatible machines for selected tool", _join(compatible_machines_for_tool(_bundle_proxy(context), context.tool_id))),
                ("Compatible machines for selected EOAT", _join(compatible_machines_for_eoat(_bundle_proxy(context), context.eoat_id))),
                ("Compatible EOATs for selected machine", _join(compatible_eoats_for_machine(_bundle_proxy(context), context.machine_id))),
                ("Compatible EOATs for selected tool", _join(compatible_eoats_for_tool(_bundle_proxy(context), context.tool_id))),
                ("Compatible tools for selected machine", _join(compatible_tools_for_machine(_bundle_proxy(context), context.machine_id))),
                ("Compatible tools for selected EOAT", _join(compatible_tools_for_eoat(_bundle_proxy(context), context.eoat_id))),
                ("Missing / uncertain notes", _join(context.validation.missing_data) or "No missing compatibility notes found."),
            ],
            styles,
        )
    )
    story.append(PageBreak())


def _ids_summary(story: list, styles: dict[str, ParagraphStyle], context: SetupPacketContext) -> None:
    _section_title(story, styles, "Machine / Tool / EOAT Context")
    story.append(
        _kv_table(
            [
                ("Machine", context.machine_id),
                ("Tool / Mold / Part", context.tool_id),
                ("EOAT", context.eoat_id),
                ("Part description", _part_description(context)),
                ("Compatibility status", context.validation.status),
                ("Documentation score", f"{context.documentation_score}%"),
                ("Warnings", str(context.warning_count)),
            ],
            styles,
        )
    )
    story.append(Spacer(1, 0.16 * inch))


def _machine_information(story: list, styles: dict[str, ParagraphStyle], context: SetupPacketContext, *, compact: bool = False) -> None:
    _section_title(story, styles, "Machine Information")
    machine = context.machine
    rows = [
        ("Machine number", context.machine_id),
        ("Plant / area", row_first(machine, "Plant/Area") if machine else ""),
        ("Press / machine name", _machine_name(machine)),
        ("Compatible tools", _join(getattr(machine, "compatible_tools", ()))),
        ("Compatible EOATs", _join(getattr(machine, "compatible_eoats", ()))),
        ("Machine-specific notes / warnings", _warning_titles(getattr(machine, "warnings", ()))),
    ]
    if not compact:
        rows.insert(3, ("Documentation score", f"{machine.documentation_score}%" if machine else ""))
    story.append(_kv_table(rows, styles))
    story.append(Spacer(1, 0.18 * inch))


def _robot_information(story: list, styles: dict[str, ParagraphStyle], context: SetupPacketContext) -> None:
    _section_title(story, styles, "Robot Information")
    robot = context.robot_info
    rows = [
        ("Robot type", _first(robot.get("Robot Type"), getattr(context.machine, "robot_type", ""))),
        ("Robot model / controller", _first(robot.get("Robot Identifier"), robot.get("Robot Model/Controller"), getattr(context.machine, "robot_model", ""))),
        ("Controller", _first(robot.get("Controller Type"), getattr(context.machine, "controller", ""))),
        ("Robot-side vacuum circuits", robot.get("Robot Vacuum Circuits", "")),
        ("Robot-side pressure circuits", robot.get("Robot Pressure Circuits", "")),
        ("Robot-side interchangeable circuits", robot.get("Robot Interchangeable Circuits", "")),
        ("Quick disconnect / electrical info", _first(robot.get("Electrical Quick Disconnect Type"), robot.get("Notes", ""))),
        ("Robot notes / warnings", _first(robot.get("Robot Notes"), robot.get("Notes"), _robot_warning_text(context))),
    ]
    story.append(_kv_table(rows, styles))
    if not robot:
        story.append(Spacer(1, 0.1 * inch))
        story.append(_warning_box("Robot information is missing or incomplete for the selected machine.", styles))
    story.append(Spacer(1, 0.18 * inch))


def _tool_information(story: list, styles: dict[str, ParagraphStyle], context: SetupPacketContext) -> None:
    _section_title(story, styles, "Tool / Part Information")
    tool = context.tool
    rows = [
        ("Tool number", context.tool_id),
        ("Mold / part number", _join(getattr(tool, "molds", ())) or _join(getattr(tool, "parts", ()))),
        ("Part family", getattr(tool, "part_family", "")),
        ("Part name / description", _part_description(context)),
        ("Compatible machines", _join(getattr(tool, "compatible_machines", ()))),
        ("Compatible EOATs", _join(getattr(tool, "compatible_eoats", ()))),
        ("Tool source info", getattr(tool, "source", "")),
        ("Tool-specific warnings", _warning_titles(getattr(tool, "warnings", ()))),
    ]
    story.append(_kv_table(rows, styles))
    story.append(Spacer(1, 0.18 * inch))


def _eoat_information(
    story: list,
    styles: dict[str, ParagraphStyle],
    context: SetupPacketContext,
    *,
    key_only: bool = False,
) -> None:
    _section_title(story, styles, "EOAT Information")
    eoat = context.eoat
    rows = [
        ("EOAT Assembly ID", context.eoat_id),
        ("EOAT type", getattr(eoat, "eoat_type", "")),
        ("Status", getattr(eoat, "status", "")),
        ("Compatible tools", _join(getattr(eoat, "tools", ()))),
        ("Compatible machines", _join(getattr(eoat, "machines", ()))),
        ("Connection type", getattr(eoat, "connection_type", "")),
        ("Quick disconnect info", _quick_disconnect_text(eoat)),
        ("Mounting / changeover style", _first(row_first(eoat, "Changeover Difficulty"), row_first(eoat, "Mounting Hardware Condition")) if eoat else ""),
    ]
    if not key_only:
        rows.extend(
            [
                ("Known issues", getattr(eoat, "known_issues", "")),
                ("EOAT notes", getattr(eoat, "install_notes", "")),
                ("Documentation", f"{context.documentation_score}% - {getattr(getattr(eoat, 'documentation', None), 'status_label', '')}"),
            ]
        )
    story.append(_kv_table(rows, styles))
    story.append(Spacer(1, 0.18 * inch))


def _pneumatics_section(story: list, styles: dict[str, ParagraphStyle], context: SetupPacketContext) -> None:
    _section_title(story, styles, "Pneumatics / Vacuum / Gripper / Sensor Information")
    eoat = context.eoat
    robot = context.robot_info
    rows = [
        ("EOAT-side vacuum circuits", _first(row_first(eoat, "EOAT Vacuum Circuits"), getattr(eoat, "vacuum_info", ""))),
        ("EOAT-side pressure circuits", _first(row_first(eoat, "EOAT Pressure Circuits"), getattr(eoat, "pressure_info", ""))),
        ("EOAT-side interchangeable circuits", row_first(eoat, "EOAT Interchangeable Circuits")),
        ("Robot-side vacuum circuits", robot.get("Robot Vacuum Circuits", "")),
        ("Robot-side pressure circuits", robot.get("Robot Pressure Circuits", "")),
        ("Robot-side interchangeable circuits", robot.get("Robot Interchangeable Circuits", "")),
        ("Number of grippers", row_first(eoat, "# of Grippers")),
        ("Gripper type", row_first(eoat, "Gripper Type")),
        ("Gripper model", row_first(eoat, "Gripper Model")),
        ("Vacuum cup info", _vacuum_cup_text(eoat)),
        ("Part-present detection info", row_first(eoat, "Part-Present Detection Present?")),
        ("Sensor type", row_first(eoat, "Sensor Type")),
        ("Sensor brand / model", row_first(eoat, "Sensor Brand/Model")),
        ("Tubing / routing notes", getattr(eoat, "tubing_notes", "")),
    ]
    story.append(_kv_table(rows, styles))
    story.append(Spacer(1, 0.18 * inch))


def _documentation_review_section(story: list, styles: dict[str, ParagraphStyle], context: SetupPacketContext) -> None:
    _section_title(story, styles, "Documentation Score And Missing Fields")
    eoat = context.eoat
    doc = getattr(eoat, "documentation", None)
    rows = [
        ("Documentation score", f"{context.documentation_score}%"),
        ("Documentation status", getattr(doc, "status_label", "")),
        ("Present fields", _join(getattr(doc, "present_fields", ())[:18] if doc else ())),
        ("Missing fields", _join(getattr(doc, "missing_fields", ())[:24] if doc else ())),
        ("Critical missing fields", _join(getattr(doc, "critical_missing_fields", ()) if doc else ())),
        ("Missing photos", _join(getattr(getattr(eoat, "photos", None), "missing_categories", ()) if eoat else ())),
        ("Warnings", _warning_titles(context.warnings)),
    ]
    story.append(_kv_table(rows, styles))
    story.append(Spacer(1, 0.18 * inch))


def _checklist_section(story: list, styles: dict[str, ParagraphStyle], title: str, items: tuple[str, ...]) -> None:
    _section_title(story, styles, title)
    rows = [("[ ]", item) for item in items]
    story.append(_plain_table(("", "Action"), rows, styles, col_widths=(0.42 * inch, 5.92 * inch), header=False))
    story.append(Spacer(1, 0.18 * inch))


def _photos_section(story: list, styles: dict[str, ParagraphStyle], context: SetupPacketContext) -> None:
    _section_title(story, styles, "Photos / Visual References")
    if context.options.photo_inclusion == PHOTO_NONE:
        story.append(
            _kv_table(
                [
                    ("Photo inclusion", "No photos"),
                    ("Photo folder path", getattr(getattr(context.eoat, "photos", None), "folder_path", "")),
                    ("Photo count", str(context.photo_count)),
                    ("Missing categories", _join(getattr(getattr(context.eoat, "photos", None), "missing_categories", ()) if context.eoat else ())),
                    ("Note", "Photos are available in Atlas or the source folder when paths are present."),
                ],
                styles,
            )
        )
        story.append(PageBreak())
        return
    if not context.selected_photos:
        story.append(_warning_box("No photos are available for this setup context.", styles))
        story.append(PageBreak())
        return
    story.append(
        _kv_table(
            [
                ("Photo inclusion", context.photo_inclusion_label),
                ("Included photos", str(len(context.selected_photos))),
                ("Rule", "Each included photo is placed on its own page."),
            ],
            styles,
        )
    )
    story.append(PageBreak())
    for index, photo in enumerate(context.selected_photos, start=1):
        _photo_page(story, styles, context, photo, index)


def _photo_page(story: list, styles: dict[str, ParagraphStyle], context: SetupPacketContext, photo, index: int) -> None:
    title = f"Photo {index}: {photo.category or photo.filename or 'Visual reference'}"
    _section_title(story, styles, title)
    caption = _join([photo.filename, photo.category, photo.path])
    story.append(Paragraph(_escaped(caption), styles["caption"]))
    story.append(Spacer(1, 0.16 * inch))
    path = Path(photo.path)
    if not path.exists():
        story.append(
            _warning_box(
                f"Image could not be embedded because the file was not found. Path: {photo.path}",
                styles,
            )
        )
        story.append(PageBreak())
        return
    try:
        width, height = _image_size(path)
        max_width = 6.45 * inch
        max_height = 7.0 * inch
        scale = min(max_width / width, max_height / height)
        story.append(Image(str(path), width=width * scale, height=height * scale, kind="proportional", hAlign="CENTER"))
    except Exception as exc:
        story.append(
            _warning_box(
                f"Image could not be embedded but can be opened from the folder. Path: {photo.path}. Error: {exc}",
                styles,
            )
        )
    story.append(PageBreak())


def _standards_section(story: list, styles: dict[str, ParagraphStyle], context: SetupPacketContext) -> None:
    _section_title(story, styles, "Standards / PM References")
    rows = []
    for reference in context.standards[:18]:
        rows.append((reference.title or "Reference", reference.category or "Standard", reference.path or reference.snippet))
    if not rows:
        rows = [("Standards library", "Reference", "No specific standard references are linked for this setup.")]
    story.append(_plain_table(("Reference", "Category", "Path / Note"), rows, styles, col_widths=(2.05 * inch, 1.35 * inch, 3.05 * inch)))
    story.append(Spacer(1, 0.18 * inch))


def _warnings_section(story: list, styles: dict[str, ParagraphStyle], context: SetupPacketContext) -> None:
    _section_title(story, styles, "Warnings / Missing Information")
    if not context.warnings and not context.missing_key_data:
        story.append(_success_box("No warnings or missing key data are indexed for this packet.", styles))
        story.append(Spacer(1, 0.18 * inch))
        return
    for warning in context.warnings[:28]:
        rows = [
            ("What is missing / wrong", f"{warning.title}: {warning.message}"),
            ("Why it matters", warning.why_it_matters or "This can affect setup confidence, lookup quality, or documentation review."),
            ("Where to fix it", warning.suggested_fix or "Review Command Center/source workflow."),
            ("Source", warning.source),
        ]
        story.append(KeepTogether([_kv_table(rows, styles), Spacer(1, 0.1 * inch)]))
    if context.missing_key_data:
        story.append(Paragraph("Missing Key Data", styles["h3"]))
        story.append(_bullet_list(context.missing_key_data[:30], styles))
    story.append(Spacer(1, 0.18 * inch))


def _source_summary(story: list, styles: dict[str, ParagraphStyle], context: SetupPacketContext) -> None:
    _section_title(story, styles, "Notes / Source Summary")
    rows = [
        ("Generated by", "EOAT Atlas"),
        ("Generated timestamp", context.generated_at),
        ("Machine / Tool / EOAT", f"{context.machine_id} / {context.tool_id} / {context.eoat_id}"),
        ("Read-only note", "Atlas generated this export without modifying source workbooks or photo folders."),
        ("Export path", context.export_path or "Assigned at PDF export time."),
        ("Detail level", context.options.detail_level.title()),
    ]
    story.append(_kv_table(rows, styles))
    story.append(Spacer(1, 0.14 * inch))
    source_rows = context.source_files or (("Source files", "", "No source status rows available."),)
    story.append(_plain_table(("Source", "Path", "Status"), source_rows, styles, col_widths=(1.55 * inch, 3.85 * inch, 1.0 * inch)))


def _section_title(story: list, styles: dict[str, ParagraphStyle], title: str) -> None:
    story.append(Paragraph(_escaped(title), styles["h1"]))
    story.append(Spacer(1, 0.1 * inch))


def _kv_table(rows: list[tuple[str, object]], styles: dict[str, ParagraphStyle], col_widths=None):
    data = []
    for key, value in rows:
        text = str(value or "").strip() or "Not recorded"
        data.append([Paragraph(_escaped(str(key)), styles["key"]), Paragraph(_escaped(text), styles["body"])])
    table = Table(data, colWidths=col_widths or (1.95 * inch, 4.45 * inch), hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d7dee8")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3f8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _plain_table(headers, rows, styles: dict[str, ParagraphStyle], col_widths=None, *, header: bool = True):
    data = []
    if header:
        data.append([Paragraph(_escaped(str(value)), styles["table_header"]) for value in headers])
    for row in rows:
        data.append([Paragraph(_escaped(str(value or "")), styles["body"]) for value in row])
    table = Table(data, colWidths=col_widths, hAlign="LEFT", repeatRows=1 if header else 0)
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d7dee8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    if header:
        commands.extend(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#102033")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ]
        )
    table.setStyle(TableStyle(commands))
    return table


def _warning_box(text: str, styles: dict[str, ParagraphStyle]):
    table = Table([[Paragraph(_escaped(text), styles["warning"])]], colWidths=(6.45 * inch,))
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff4dd")),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#b76a00")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _success_box(text: str, styles: dict[str, ParagraphStyle]):
    table = Table([[Paragraph(_escaped(text), styles["body"])]], colWidths=(6.45 * inch,))
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#e6f6ef")),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#087f5b")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _bullet_list(items, styles: dict[str, ParagraphStyle]):
    return KeepTogether([Paragraph(f"- {_escaped(str(item))}", styles["body"]) for item in items if str(item).strip()])


def _page_decorator(context: SetupPacketContext):
    def _draw(canvas, doc):
        canvas.saveState()
        width, height = letter
        header = f"EOAT Atlas Setup Packet | Machine {context.machine_id} | Tool {context.tool_id} | EOAT {context.eoat_id}"
        footer = f"Generated {context.generated_at} | {context.validation.status} | Page {doc.page}"
        canvas.setStrokeColor(colors.HexColor("#d7dee8"))
        canvas.setFillColor(colors.HexColor("#102033"))
        canvas.setFont("Helvetica-Bold", 8.5)
        canvas.drawString(0.62 * inch, height - 0.45 * inch, header[:118])
        canvas.line(0.62 * inch, height - 0.55 * inch, width - 0.62 * inch, height - 0.55 * inch)
        canvas.setFillColor(colors.HexColor("#627d98"))
        canvas.setFont("Helvetica", 8)
        canvas.line(0.62 * inch, 0.48 * inch, width - 0.62 * inch, 0.48 * inch)
        canvas.drawString(0.62 * inch, 0.31 * inch, footer[:128])
        canvas.restoreState()

    return _draw


def _styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=sample["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=29,
            textColor=colors.HexColor("#102033"),
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#627d98"),
            alignment=TA_CENTER,
        ),
        "h1": ParagraphStyle(
            "SectionHeading",
            parent=sample["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=21,
            textColor=colors.HexColor("#102033"),
            spaceBefore=4,
            spaceAfter=6,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "SmallHeading",
            parent=sample["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#102033"),
            spaceBefore=8,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "PacketBody",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=9.8,
            leading=13.2,
            textColor=colors.HexColor("#172033"),
            alignment=TA_LEFT,
        ),
        "key": ParagraphStyle(
            "PacketKey",
            parent=sample["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9.2,
            leading=12.5,
            textColor=colors.HexColor("#243b53"),
        ),
        "table_header": ParagraphStyle(
            "PacketTableHeader",
            parent=sample["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8.8,
            leading=11.5,
            textColor=colors.white,
        ),
        "warning": ParagraphStyle(
            "PacketWarning",
            parent=sample["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13.5,
            textColor=colors.HexColor("#78350f"),
        ),
        "caption": ParagraphStyle(
            "PacketCaption",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=8.8,
            leading=11.5,
            textColor=colors.HexColor("#627d98"),
            alignment=TA_CENTER,
        ),
    }


def _unique_packet_path(output_dir: Path, context: SetupPacketContext) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / setup_packet_filename(context, timestamp=stamp)
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}_{index:03d}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not allocate a unique setup packet filename in {output_dir}")


def _safe_component(value: str) -> str:
    text = str(value or "Unselected").strip()
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in text)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "Unselected"


def _escaped(value: str) -> str:
    return escape(str(value or "").replace("\n", " "))


def _join(values) -> str:
    if isinstance(values, str):
        return values
    return ", ".join(str(value).strip() for value in values if str(value).strip())


def _first(*values) -> str:
    return next((str(value).strip() for value in values if str(value or "").strip()), "")


def _part_description(context: SetupPacketContext) -> str:
    return _first(
        getattr(context.tool, "part_description", ""),
        getattr(context.eoat, "part_description", ""),
        getattr(context.tool, "part_family", ""),
        getattr(context.eoat, "part_family", ""),
        _join(getattr(context.tool, "parts", ())),
        _join(getattr(context.eoat, "parts", ())),
    )


def _machine_name(machine) -> str:
    if machine is None:
        return ""
    return _first(machine.label, machine.robot_type, machine.robot_model)


def _warning_titles(warnings) -> str:
    return "; ".join(f"{warning.title}: {warning.message}" for warning in warnings) if warnings else ""


def _robot_warning_text(context: SetupPacketContext) -> str:
    warnings = getattr(context.machine, "warnings", ()) if context.machine else ()
    return _warning_titles(warnings)


def _quick_disconnect_text(eoat) -> str:
    if eoat is None:
        return ""
    return _first(
        row_first(eoat, "Pneumatic Quick Disconnect Type"),
        row_first(eoat, "Electrical Quick Disconnect Type"),
        eoat.connection_type,
    )


def _vacuum_cup_text(eoat) -> str:
    if eoat is None:
        return ""
    parts = [
        f"# of Cups: {row_first(eoat, '# of Cups')}" if row_first(eoat, "# of Cups") else "",
        f"Cup Type/Material: {row_first(eoat, 'Cup Type/Material')}" if row_first(eoat, "Cup Type/Material") else "",
        f"Cup Diameter/Size: {row_first(eoat, 'Cup Diameter/Size')}" if row_first(eoat, "Cup Diameter/Size") else "",
        f"Vacuum Generator Type: {row_first(eoat, 'Vacuum Generator Type')}" if row_first(eoat, "Vacuum Generator Type") else "",
    ]
    return "; ".join(part for part in parts if part)


def _compatibility_warning_text(context: SetupPacketContext) -> str:
    if context.validation.status == COMPATIBILITY_MANUAL_OVERRIDE:
        return (
            "Manual Override Used. This combination is not confirmed by Atlas compatibility data. Generate or use this "
            "packet only if the setup has been verified through another approved source."
        )
    return (
        "Compatibility Not Confirmed. Atlas does not find full compatibility for the selected Machine + Tool + EOAT "
        "combination in the loaded source data."
    )


def _image_size(path: Path) -> tuple[float, float]:
    if PILImage is None:
        raise RuntimeError("Pillow is required to read image dimensions.")
    with PILImage.open(path) as image:
        return float(image.width), float(image.height)


def _bundle_proxy(context: SetupPacketContext):
    class BundleProxy:
        project_root = context.project_root
        eoats = tuple([context.eoat] if context.eoat else [])
        machines = tuple([context.machine] if context.machine else [])
        tools = tuple([context.tool] if context.tool else [])

        class Indexes:
            eoat_by_id = {}
            eoats_by_tool = {}
            eoats_by_machine = {}
            machines_by_tool = {}
            machines_by_eoat = {}
            tools_by_machine = {}

        indexes = Indexes()

    proxy = BundleProxy()
    if context.eoat:
        proxy.indexes.eoat_by_id = {context.eoat_id.casefold(): context.eoat_id}
        proxy.indexes.eoats_by_tool = {normalized_tool_key(tool): (context.eoat_id,) for tool in context.eoat.tools}
        proxy.indexes.eoats_by_machine = {normalized_machine_key(machine): (context.eoat_id,) for machine in context.eoat.machines}
        proxy.indexes.machines_by_eoat = {normalized_eoat_key(context.eoat_id): context.eoat.machines}
    if context.tool:
        proxy.indexes.machines_by_tool = {normalized_tool_key(context.tool_id): context.tool.compatible_machines}
    if context.machine:
        proxy.indexes.tools_by_machine = {normalized_machine_key(context.machine_id): context.machine.compatible_tools}
    return proxy


__all__ = ["export_setup_packet_pdf", "setup_packet_filename"]
