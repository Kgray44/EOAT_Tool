from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from .atlas_models import AtlasDataBundle, EOATRecord
from .atlas_setup_packets import find_eoat, find_machine, find_tool, row_first
from .atlas_utils import display_value
from .fit_check_service import FitCheckRequest, FitCheckResult
from .paths import resolve_project_paths
from .reporting.pdf_footer import draw_standard_pdf_footer, pdf_page_size
from .resources import writable_config_path
from .safe_files import ensure_directory

try:  # pragma: no cover - dependency availability is environment-specific
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
except Exception as exc:  # pragma: no cover
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


PACKET_TYPE_SETUP = "setup"
PACKET_TYPE_CHANGEOVER = "changeover"
RECENT_PACKET_LIMIT = 8


@dataclass(frozen=True)
class PacketSetup:
    tool_id: str = ""
    machine_id: str = ""
    eoat_id: str = ""

    def normalized(self) -> PacketSetup:
        return PacketSetup(
            tool_id=str(self.tool_id or "").strip(),
            machine_id=str(self.machine_id or "").strip(),
            eoat_id=str(self.eoat_id or "").strip(),
        )

    def complete(self) -> bool:
        value = self.normalized()
        return bool(value.tool_id and value.machine_id and value.eoat_id)

    def to_fit_request(self) -> FitCheckRequest:
        value = self.normalized()
        return FitCheckRequest(
            tool_id=value.tool_id,
            machine_id=value.machine_id,
            eoat_id=value.eoat_id,
            eoat_mode="manual" if value.eoat_id else "auto",
        )

    def summary(self) -> str:
        value = self.normalized()
        parts = [part for part in (value.tool_id, f"Machine {value.machine_id}" if value.machine_id else "", value.eoat_id) if part]
        return " - ".join(parts) or "Incomplete setup"


@dataclass(frozen=True)
class RecentPacket:
    packet_id: str
    packet_type: str
    status: str
    created_at: str
    updated_at: str
    setup: PacketSetup = field(default_factory=PacketSetup)
    from_setup: PacketSetup = field(default_factory=PacketSetup)
    to_setup: PacketSetup = field(default_factory=PacketSetup)
    pdf_path: str = ""

    def title(self) -> str:
        return "Changeover Packet" if self.packet_type == PACKET_TYPE_CHANGEOVER else "Setup Packet"

    def summary(self) -> str:
        if self.packet_type == PACKET_TYPE_CHANGEOVER:
            return f"{self.from_setup.summary()} -> {self.to_setup.summary()}"
        return self.setup.summary()

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "packet_type": self.packet_type,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "setup": asdict(self.setup.normalized()),
            "from_setup": asdict(self.from_setup.normalized()),
            "to_setup": asdict(self.to_setup.normalized()),
            "pdf_path": self.pdf_path,
        }


def recent_packets_path() -> Path:
    return writable_config_path("eoat_atlas_recent_packets.json")


def load_recent_packets(*, limit: int = RECENT_PACKET_LIMIT) -> list[RecentPacket]:
    try:
        raw = json.loads(recent_packets_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get("items", raw) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    packets = [_packet_from_dict(item) for item in items if isinstance(item, dict)]
    packets = [packet for packet in packets if packet is not None]
    packets.sort(key=lambda packet: packet.updated_at or packet.created_at, reverse=True)
    return packets[:limit]


def save_recent_packets(packets: list[RecentPacket], *, limit: int = RECENT_PACKET_LIMIT) -> None:
    path = recent_packets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    deduped: list[RecentPacket] = []
    seen: set[str] = set()
    for packet in packets:
        key = packet.packet_id or _packet_signature(packet)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(packet)
        if len(deduped) >= limit:
            break
    path.write_text(json.dumps({"items": [packet.to_dict() for packet in deduped]}, indent=2), encoding="utf-8")


def upsert_recent_packet(packet: RecentPacket, *, limit: int = RECENT_PACKET_LIMIT) -> list[RecentPacket]:
    existing = [item for item in load_recent_packets(limit=limit) if item.packet_id != packet.packet_id]
    packets = [packet, *existing]
    save_recent_packets(packets, limit=limit)
    return packets[:limit]


def packet_output_dir(project_root: str | Path) -> Path:
    return ensure_directory(resolve_project_paths(project_root).final_handoff / "Atlas_Exports" / "Packets")


def setup_packet_filename(setup: PacketSetup, *, timestamp: str | None = None) -> str:
    setup = setup.normalized()
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M")
    return _clean_filename(
        f"EOAT_Setup_Packet__Tool_{setup.tool_id or 'Unknown'}"
        f"__Machine_{setup.machine_id or 'Unknown'}"
        f"__EOAT_{setup.eoat_id or 'Unknown'}__{stamp}.pdf"
    )


def changeover_packet_filename(from_setup: PacketSetup, to_setup: PacketSetup, *, timestamp: str | None = None) -> str:
    from_setup = from_setup.normalized()
    to_setup = to_setup.normalized()
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M")
    return _clean_filename(
        "EOAT_Changeover_Packet"
        f"__From_{from_setup.tool_id or 'Unknown'}_{from_setup.machine_id or 'Unknown'}_{from_setup.eoat_id or 'Unknown'}"
        f"__To_{to_setup.tool_id or 'Unknown'}_{to_setup.machine_id or 'Unknown'}_{to_setup.eoat_id or 'Unknown'}__{stamp}.pdf"
    )


def setup_checklist() -> tuple[str, ...]:
    return (
        "Confirm EOAT ID matches packet",
        "Confirm tool/mold number",
        "Confirm machine number",
        "Inspect vacuum cups/grippers for wear or damage",
        "Inspect pneumatic tubing",
        "Verify sensor operation",
        "Inspect mounting hardware",
        "Verify EOAT alignment",
        "Check quick disconnect fittings",
        "Verify cable management condition",
        "Dry-cycle robot before production",
        "Confirm first-shot/first-part handling",
    )


def changeover_checklist() -> tuple[tuple[str, tuple[str, ...]], ...]:
    return (
        (
            "Before Changeover",
            (
                "Confirm current setup matches FROM section",
                "Confirm next setup matches TO section",
                "Confirm new EOAT is available",
                "Confirm new tool/mold is available",
                "Review warnings and requirement changes",
                "Verify required fittings/cables/air lines are available",
            ),
        ),
        (
            "Remove Old Setup",
            (
                "Stop machine safely",
                "Confirm robot is in safe position",
                "Disconnect air/vacuum as required",
                "Disconnect sensors/electrical as required",
                "Remove current EOAT if changing",
                "Inspect removed EOAT for damage",
                "Store removed EOAT in correct location",
            ),
        ),
        (
            "Install New Setup",
            (
                "Install new tool/mold as required",
                "Install required EOAT",
                "Confirm EOAT ID",
                "Connect quick disconnects/fittings",
                "Connect sensor/electrical cables",
                "Verify tubing is not pinched or strained",
                "Verify mounting hardware",
                "Verify EOAT alignment",
            ),
        ),
        (
            "Verify Before Production",
            (
                "Verify sensor operation",
                "Verify vacuum/pressure behavior",
                "Dry-cycle robot",
                "Confirm pick location",
                "Confirm release location",
                "Confirm first-shot handling",
                "Confirm no unexpected interference",
            ),
        ),
        (
            "Final Signoff",
            (
                "First good parts confirmed",
                "Any issues documented",
                "Setup/changeover packet saved or printed if needed",
            ),
        ),
    )


def is_valid_fit_result(result: FitCheckResult | None) -> bool:
    return result is not None and result.status in {"compatible", "warning"}


def build_change_summary(
    bundle: AtlasDataBundle | None,
    from_setup: PacketSetup,
    to_setup: PacketSetup,
    *,
    from_result: FitCheckResult | None = None,
    to_result: FitCheckResult | None = None,
) -> tuple[str, ...]:
    from_setup = from_setup.normalized()
    to_setup = to_setup.normalized()
    if not (from_setup.complete() and to_setup.complete()):
        return ("Complete both setups to compare requirements.",)
    changes: list[str] = []
    _append_change(changes, "Machine", from_setup.machine_id, to_setup.machine_id, same_text="No machine change")
    _append_change(changes, "Tool", from_setup.tool_id, to_setup.tool_id, same_text="No tool change")
    _append_change(changes, "EOAT", from_setup.eoat_id, to_setup.eoat_id, same_text="No EOAT change")

    from_eoat = find_eoat(bundle, from_setup.eoat_id) if bundle is not None and from_setup.eoat_id else None
    to_eoat = find_eoat(bundle, to_setup.eoat_id) if bundle is not None and to_setup.eoat_id else None
    for label, left, right in _eoat_change_fields(from_eoat, to_eoat):
        if _normalized_text(left) != _normalized_text(right):
            changes.append(f"{label}: {_field_or_unknown(left)} -> {_field_or_unknown(right)}")

    for label, result in (("FROM", from_result), ("TO", to_result)):
        if result is None:
            continue
        warning_text = "; ".join(f"{warning.title}: {warning.message}" for warning in result.warnings[:2])
        if warning_text:
            changes.append(f"{label} warnings: {warning_text}")

    meaningful = [line for line in changes if not line.endswith("No machine change") and not line.endswith("No tool change") and not line.endswith("No EOAT change")]
    return tuple(changes if meaningful else ("No major setup requirement changes detected.",))


def export_changeover_packet_pdf(
    bundle: AtlasDataBundle,
    from_setup: PacketSetup,
    to_setup: PacketSetup,
    *,
    from_result: FitCheckResult | None = None,
    to_result: FitCheckResult | None = None,
    output_dir: str | Path | None = None,
) -> Path:
    if _IMPORT_ERROR is not None:
        raise RuntimeError("Changeover Packet PDF export requires reportlab.") from _IMPORT_ERROR
    from_setup = from_setup.normalized()
    to_setup = to_setup.normalized()
    target_dir = Path(output_dir) if output_dir is not None else packet_output_dir(bundle.project_root)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = _unique_path(target_dir / changeover_packet_filename(from_setup, to_setup))
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    story = _changeover_story(bundle, from_setup, to_setup, from_result, to_result, generated_at)
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        rightMargin=0.62 * inch,
        leftMargin=0.62 * inch,
        topMargin=0.88 * inch,
        bottomMargin=0.72 * inch,
        title="EOAT Atlas Changeover Packet",
        author="EOAT Atlas",
    )
    doc.build(story, onFirstPage=_changeover_page_decorator(from_setup, to_setup, generated_at), onLaterPages=_changeover_page_decorator(from_setup, to_setup, generated_at))
    return path


def make_recent_packet(
    *,
    packet_type: str,
    status: str,
    setup: PacketSetup | None = None,
    from_setup: PacketSetup | None = None,
    to_setup: PacketSetup | None = None,
    pdf_path: str = "",
    existing_id: str = "",
) -> RecentPacket:
    now = datetime.now().isoformat(timespec="seconds")
    packet = RecentPacket(
        packet_id=existing_id,
        packet_type=packet_type,
        status=status,
        created_at=now,
        updated_at=now,
        setup=(setup or PacketSetup()).normalized(),
        from_setup=(from_setup or PacketSetup()).normalized(),
        to_setup=(to_setup or PacketSetup()).normalized(),
        pdf_path=str(pdf_path or ""),
    )
    packet_id = existing_id or _packet_signature(packet)
    return RecentPacket(
        packet_id=packet_id,
        packet_type=packet.packet_type,
        status=packet.status,
        created_at=packet.created_at,
        updated_at=packet.updated_at,
        setup=packet.setup,
        from_setup=packet.from_setup,
        to_setup=packet.to_setup,
        pdf_path=packet.pdf_path,
    )


def _packet_from_dict(raw: dict[str, Any]) -> RecentPacket | None:
    packet_type = str(raw.get("packet_type") or raw.get("packetType") or "").strip()
    if packet_type not in {PACKET_TYPE_SETUP, PACKET_TYPE_CHANGEOVER}:
        return None
    setup = _setup_from_dict(raw.get("setup"))
    from_setup = _setup_from_dict(raw.get("from_setup") or raw.get("fromSetup"))
    to_setup = _setup_from_dict(raw.get("to_setup") or raw.get("toSetup"))
    created_at = str(raw.get("created_at") or raw.get("createdAt") or raw.get("updated_at") or datetime.now().isoformat(timespec="seconds"))
    updated_at = str(raw.get("updated_at") or raw.get("updatedAt") or created_at)
    packet = RecentPacket(
        packet_id=str(raw.get("packet_id") or raw.get("id") or "").strip(),
        packet_type=packet_type,
        status=str(raw.get("status") or "Draft").strip() or "Draft",
        created_at=created_at,
        updated_at=updated_at,
        setup=setup,
        from_setup=from_setup,
        to_setup=to_setup,
        pdf_path=str(raw.get("pdf_path") or raw.get("pdfPath") or "").strip(),
    )
    return RecentPacket(
        packet_id=packet.packet_id or _packet_signature(packet),
        packet_type=packet.packet_type,
        status=packet.status,
        created_at=packet.created_at,
        updated_at=packet.updated_at,
        setup=packet.setup,
        from_setup=packet.from_setup,
        to_setup=packet.to_setup,
        pdf_path=packet.pdf_path,
    )


def _setup_from_dict(raw: Any) -> PacketSetup:
    raw = raw if isinstance(raw, dict) else {}
    return PacketSetup(
        tool_id=str(raw.get("tool_id") or raw.get("toolId") or "").strip(),
        machine_id=str(raw.get("machine_id") or raw.get("machineId") or "").strip(),
        eoat_id=str(raw.get("eoat_id") or raw.get("eoatId") or "").strip(),
    ).normalized()


def _packet_signature(packet: RecentPacket) -> str:
    if packet.packet_type == PACKET_TYPE_CHANGEOVER:
        return "|".join(
            (
                PACKET_TYPE_CHANGEOVER,
                packet.from_setup.tool_id,
                packet.from_setup.machine_id,
                packet.from_setup.eoat_id,
                packet.to_setup.tool_id,
                packet.to_setup.machine_id,
                packet.to_setup.eoat_id,
                packet.status,
            )
        )
    return "|".join((PACKET_TYPE_SETUP, packet.setup.tool_id, packet.setup.machine_id, packet.setup.eoat_id, packet.status))


def _changeover_story(
    bundle: AtlasDataBundle,
    from_setup: PacketSetup,
    to_setup: PacketSetup,
    from_result: FitCheckResult | None,
    to_result: FitCheckResult | None,
    generated_at: str,
) -> list:
    styles = _styles()
    story: list = []
    story.append(Paragraph("EOAT Atlas", styles["brand"]))
    story.append(Paragraph("Changeover Packet", styles["title"]))
    story.append(Paragraph(f"Generated {escape(generated_at)}", styles["subtitle"]))
    story.append(Spacer(1, 0.18 * inch))
    story.append(_kv_table("FROM / Current Setup", _setup_rows(bundle, from_setup, from_result), styles))
    story.append(Spacer(1, 0.12 * inch))
    story.append(_kv_table("TO / New Setup", _setup_rows(bundle, to_setup, to_result), styles))
    story.append(Spacer(1, 0.18 * inch))
    _section(story, styles, "What Changes")
    story.append(_bullet_table(build_change_summary(bundle, from_setup, to_setup, from_result=from_result, to_result=to_result), styles))
    story.append(Spacer(1, 0.18 * inch))
    _section(story, styles, "Air / Vacuum / Pressure / IO Changes")
    story.append(_kv_table("Requirements", _eoat_requirement_rows(find_eoat(bundle, from_setup.eoat_id), find_eoat(bundle, to_setup.eoat_id)), styles))
    story.append(Spacer(1, 0.18 * inch))
    _section(story, styles, "Changeover Checklist")
    for phase, items in changeover_checklist():
        story.append(Paragraph(escape(phase), styles["phase"]))
        story.append(_checklist_table(items, styles))
        story.append(Spacer(1, 0.08 * inch))
    story.append(Spacer(1, 0.1 * inch))
    _section(story, styles, "Warnings / Notes")
    warnings = []
    for label, result in (("FROM", from_result), ("TO", to_result)):
        warnings.extend(f"{label}: {warning.title} - {warning.message}" for warning in getattr(result, "warnings", ())[:6])
    story.append(_bullet_table(tuple(warnings) or ("No warnings are indexed for these validated setups.",), styles))
    return story


def _setup_rows(bundle: AtlasDataBundle, setup: PacketSetup, result: FitCheckResult | None) -> list[tuple[str, str]]:
    tool = find_tool(bundle, setup.tool_id)
    machine = find_machine(bundle, setup.machine_id)
    eoat = find_eoat(bundle, setup.eoat_id)
    return [
        ("Tool number", setup.tool_id or "Not listed"),
        ("Tool description", _first(getattr(tool, "part_description", ""), getattr(tool, "part_family", ""))),
        ("Machine number", setup.machine_id or "Not listed"),
        ("Robot / location", _first(getattr(machine, "robot_type", ""), getattr(machine, "robot_model", ""), row_first(machine, "Plant/Area"))),
        ("EOAT ID", setup.eoat_id or "Not listed"),
        ("EOAT type", _first(getattr(eoat, "eoat_type", ""), getattr(eoat, "status", ""))),
        ("Compatibility", _fit_status_text(result)),
    ]


def _eoat_requirement_rows(from_eoat: EOATRecord | None, to_eoat: EOATRecord | None) -> list[tuple[str, str]]:
    rows = []
    for label, left, right in _eoat_change_fields(from_eoat, to_eoat):
        rows.append((label, f"{_field_or_unknown(left)} -> {_field_or_unknown(right)}"))
    return rows or [("Requirements", "Verify manually")]


def _eoat_change_fields(from_eoat: EOATRecord | None, to_eoat: EOATRecord | None) -> tuple[tuple[str, str, str], ...]:
    return (
        ("EOAT type", getattr(from_eoat, "eoat_type", ""), getattr(to_eoat, "eoat_type", "")),
        ("Connection type", getattr(from_eoat, "connection_type", ""), getattr(to_eoat, "connection_type", "")),
        ("Vacuum", _first(getattr(from_eoat, "vacuum_info", ""), row_first(from_eoat, "EOAT Vacuum Circuits")), _first(getattr(to_eoat, "vacuum_info", ""), row_first(to_eoat, "EOAT Vacuum Circuits"))),
        ("Pressure", _first(getattr(from_eoat, "pressure_info", ""), row_first(from_eoat, "EOAT Pressure Circuits")), _first(getattr(to_eoat, "pressure_info", ""), row_first(to_eoat, "EOAT Pressure Circuits"))),
        ("Sensor notes", getattr(from_eoat, "sensor_info", ""), getattr(to_eoat, "sensor_info", "")),
        ("Quick disconnect", _first(row_first(from_eoat, "Pneumatic Quick Disconnect Type"), row_first(from_eoat, "Electrical Quick Disconnect Type")), _first(row_first(to_eoat, "Pneumatic Quick Disconnect Type"), row_first(to_eoat, "Electrical Quick Disconnect Type"))),
        ("Parts picked", _first(row_first(from_eoat, "Number of Parts Picked"), row_first(from_eoat, "# Parts Picked")), _first(row_first(to_eoat, "Number of Parts Picked"), row_first(to_eoat, "# Parts Picked"))),
    )


def _append_change(changes: list[str], label: str, left: str, right: str, *, same_text: str) -> None:
    left_text = _field_or_unknown(left)
    right_text = _field_or_unknown(right)
    if _normalized_text(left_text) == _normalized_text(right_text):
        changes.append(f"{label}: {left_text} -> {right_text}. {same_text}")
    else:
        changes.append(f"{label}: {left_text} -> {right_text}. {label} change required")


def _section(story: list, styles: dict[str, ParagraphStyle], title: str) -> None:
    story.append(Paragraph(escape(title), styles["h1"]))
    story.append(Spacer(1, 0.08 * inch))


def _kv_table(title: str, rows: list[tuple[str, str]], styles: dict[str, ParagraphStyle]):
    data = [[Paragraph(escape(title), styles["table_header"]), ""]]
    data.extend([Paragraph(escape(label), styles["key"]), Paragraph(escape(_field_or_unknown(value)), styles["body"])] for label, value in rows)
    table = Table(data, colWidths=(1.75 * inch, 4.75 * inch), hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("SPAN", (0, 0), (-1, 0)),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#102033")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d7dee8")),
                ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#eef3f8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _bullet_table(items: tuple[str, ...], styles: dict[str, ParagraphStyle]):
    data = [[Paragraph("[ ]" if not item.startswith("No major") and not item.startswith("No warnings") else "-", styles["key"]), Paragraph(escape(item), styles["body"])] for item in items]
    table = Table(data, colWidths=(0.42 * inch, 6.02 * inch), hAlign="LEFT")
    table.setStyle(_plain_table_style())
    return table


def _checklist_table(items: tuple[str, ...], styles: dict[str, ParagraphStyle]):
    data = [[Paragraph("[ ]", styles["key"]), Paragraph(escape(item), styles["body"])] for item in items]
    table = Table(data, colWidths=(0.42 * inch, 6.02 * inch), hAlign="LEFT")
    table.setStyle(_plain_table_style())
    return table


def _plain_table_style():
    return TableStyle(
        [
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d7dee8")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
    )


def _changeover_page_decorator(from_setup: PacketSetup, to_setup: PacketSetup, generated_at: str):
    def _draw(canvas, doc):
        canvas.saveState()
        width, height = pdf_page_size(canvas, doc)
        header = f"EOAT Atlas Changeover Packet | FROM {from_setup.summary()} | TO {to_setup.summary()}"
        canvas.setStrokeColor(colors.HexColor("#d7dee8"))
        canvas.setFillColor(colors.HexColor("#102033"))
        canvas.setFont("Helvetica-Bold", 8.5)
        canvas.drawString(0.62 * inch, height - 0.45 * inch, header[:118])
        canvas.line(0.62 * inch, height - 0.55 * inch, width - 0.62 * inch, height - 0.55 * inch)
        canvas.restoreState()
        draw_standard_pdf_footer(canvas, doc, left_text=f"Generated {generated_at}", right_text=f"Page {doc.page}")

    return _draw


def _styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    return {
        "brand": ParagraphStyle("PacketBrand", parent=sample["BodyText"], fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=colors.HexColor("#1177cc"), alignment=TA_CENTER),
        "title": ParagraphStyle("PacketTitle", parent=sample["Title"], fontName="Helvetica-Bold", fontSize=23, leading=29, textColor=colors.HexColor("#102033"), alignment=TA_CENTER, spaceAfter=5),
        "subtitle": ParagraphStyle("PacketSubtitle", parent=sample["BodyText"], fontName="Helvetica", fontSize=10, leading=13, textColor=colors.HexColor("#627d98"), alignment=TA_CENTER),
        "h1": ParagraphStyle("PacketHeading", parent=sample["Heading1"], fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=colors.HexColor("#102033"), keepWithNext=True),
        "phase": ParagraphStyle("PacketPhase", parent=sample["Heading3"], fontName="Helvetica-Bold", fontSize=11.2, leading=14, textColor=colors.HexColor("#243b53"), spaceBefore=4, spaceAfter=3),
        "body": ParagraphStyle("PacketBody", parent=sample["BodyText"], fontName="Helvetica", fontSize=9.4, leading=12.8, textColor=colors.HexColor("#172033"), alignment=TA_LEFT),
        "key": ParagraphStyle("PacketKey", parent=sample["BodyText"], fontName="Helvetica-Bold", fontSize=9.0, leading=12.2, textColor=colors.HexColor("#243b53")),
        "table_header": ParagraphStyle("PacketHeader", parent=sample["BodyText"], fontName="Helvetica-Bold", fontSize=9.2, leading=12.4, textColor=colors.white),
    }


def _fit_status_text(result: FitCheckResult | None) -> str:
    if result is None:
        return "Incomplete"
    return f"{result.headline}: {result.message}"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}_{index:03d}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not allocate a unique packet filename in {path.parent}")


def _clean_filename(value: str) -> str:
    text = "".join(character if character.isalnum() or character in "._-" else "_" for character in str(value or "packet.pdf"))
    while "___" in text:
        text = text.replace("___", "__")
    return text.strip("_") or "EOAT_Packet.pdf"


def _field_or_unknown(value: Any) -> str:
    text = display_value(value)
    return text if text else "Unknown"


def _normalized_text(value: Any) -> str:
    return " ".join(display_value(value).casefold().split())


def _first(*values: Any) -> str:
    return next((display_value(value) for value in values if display_value(value)), "Not listed")


__all__ = [
    "PACKET_TYPE_CHANGEOVER",
    "PACKET_TYPE_SETUP",
    "PacketSetup",
    "RecentPacket",
    "build_change_summary",
    "changeover_checklist",
    "changeover_packet_filename",
    "export_changeover_packet_pdf",
    "is_valid_fit_result",
    "load_recent_packets",
    "make_recent_packet",
    "packet_output_dir",
    "recent_packets_path",
    "save_recent_packets",
    "setup_checklist",
    "setup_packet_filename",
    "upsert_recent_packet",
]
