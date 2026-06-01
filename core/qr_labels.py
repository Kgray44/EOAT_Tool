from __future__ import annotations

import html
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .analysis_common import timestamp_for_report
from .audit_entries import repair_legacy_audit_lookup_shift
from .logging import log_tool_run
from .paths import resolve_project_paths
from .result import ToolResult
from .safe_files import ensure_directory, safe_write_text
from .workbook_io import row_dicts

TOOL_ID = "qr_label_generator"
TOOL_NAME = "EOAT QR Label Generator"
ALLOWED_QR_PREFIXES = ("eoat://machine/", "eoat://audit/")


@dataclass(frozen=True)
class QRLabel:
    label_type: str
    target_id: str
    display_label: str
    qr_value: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def machine_qr_value(machine: str | int) -> str:
    machine_id = _minimal_machine_id(machine)
    return f"eoat://machine/{quote(machine_id, safe='')}"


def audit_qr_value(audit_id: str) -> str:
    clean = _clean(audit_id)
    if not clean:
        raise ValueError("Audit ID is required for an audit QR value.")
    return f"eoat://audit/{quote(clean, safe='')}"


def validate_qr_value(value: str) -> bool:
    text = _clean(value)
    if not text.startswith(ALLOWED_QR_PREFIXES):
        return False
    payload = text.split("/", 3)[-1]
    if not payload:
        return False
    forbidden_fragments = ["plant", "tool", "part", "customer", "operator", "path", "\\", " "]
    return not any(fragment in payload.casefold() for fragment in forbidden_fragments)


def build_qr_labels(
    project_root: str | Path,
    *,
    include_machines: bool = True,
    include_audits: bool = True,
    machines: list[str] | None = None,
    audit_ids: list[str] | None = None,
) -> list[QRLabel]:
    labels: list[QRLabel] = []
    if machines is None or audit_ids is None:
        rows = _inventory_rows(project_root)
    else:
        rows = []
    machine_values = machines if machines is not None else _unique(_clean(row.get("Press/Machine #")) for row in rows)
    audit_values = audit_ids if audit_ids is not None else _unique(_clean(row.get("Audit ID")) for row in rows)
    if include_machines:
        for machine in machine_values:
            if not _clean(machine):
                continue
            value = machine_qr_value(machine)
            labels.append(
                QRLabel("machine", _minimal_machine_id(machine), f"Machine {_minimal_machine_id(machine)}", value)
            )
    if include_audits:
        for audit_id in audit_values:
            if not _clean(audit_id):
                continue
            value = audit_qr_value(audit_id)
            labels.append(QRLabel("audit", _clean(audit_id), f"Audit {_clean(audit_id)}", value))
    return [label for label in labels if validate_qr_value(label.qr_value)]


def export_qr_label_sheet(
    project_root: str | Path,
    *,
    include_machines: bool = True,
    include_audits: bool = True,
    machines: list[str] | None = None,
    audit_ids: list[str] | None = None,
    log_activity: bool = True,
) -> ToolResult:
    start = time.perf_counter()
    labels = build_qr_labels(
        project_root,
        include_machines=include_machines,
        include_audits=include_audits,
        machines=machines,
        audit_ids=audit_ids,
    )
    if not labels:
        return ToolResult.fail(TOOL_ID, TOOL_NAME, "No QR labels were generated.")
    output_dir = ensure_directory(resolve_project_paths(project_root).qr_labels)
    stamp = timestamp_for_report()
    files_created: list[str] = []
    warnings: list[str] = []
    try:
        png_path = _write_png_sheet_if_supported(output_dir, labels, stamp)
        if png_path:
            files_created.append(str(png_path))
        else:
            warnings.append(
                "Scannable QR image export requires the optional qrcode package; wrote printable SVG value sheet instead."
            )
        svg_path = safe_write_text(output_dir / f"EOAT_QR_Label_Sheet_{stamp}.svg", _svg_sheet(labels), overwrite=False)
        markdown_path = safe_write_text(
            output_dir / f"EOAT_QR_Label_Values_{stamp}.md", _markdown_sheet(labels), overwrite=False
        )
        files_created.extend([str(svg_path), str(markdown_path)])
    except Exception as exc:
        return ToolResult.fail(TOOL_ID, TOOL_NAME, "Could not export QR label sheet.", errors=[str(exc)])
    result = ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        f"Generated {len(labels)} QR label value(s).",
        details=[
            "QR values contain only local EOAT route identifiers.",
            "No plant, tool, part, customer, workbook path, or operational detail is encoded.",
        ],
        warnings=warnings,
        files_created=files_created,
        output_reports=files_created,
        structured_data={"labels": [label.to_dict() for label in labels]},
        metrics={"label_count": len(labels), "png_exported": any(path.endswith(".png") for path in files_created)},
        duration_seconds=time.perf_counter() - start,
    )
    if log_activity:
        warning = log_tool_run(result, project_root)
        if warning:
            result.warnings.append(warning)
    return result


def _write_png_sheet_if_supported(output_dir: Path, labels: list[QRLabel], stamp: str) -> Path | None:
    try:
        import qrcode
        from PIL import Image, ImageDraw
    except Exception:
        return None
    cell_w, cell_h = 360, 430
    columns = 3
    rows = (len(labels) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell_w, rows * cell_h), "white")
    draw = ImageDraw.Draw(sheet)
    for index, label in enumerate(labels):
        x = (index % columns) * cell_w
        y = (index // columns) * cell_h
        qr = qrcode.make(label.qr_value).resize((250, 250))
        sheet.paste(qr, (x + 55, y + 28))
        draw.text((x + 20, y + 300), label.display_label, fill="black")
        draw.text((x + 20, y + 330), label.qr_value, fill="black")
    path = output_dir / f"EOAT_QR_Label_Sheet_{stamp}.png"
    sheet.save(path)
    return path


def _svg_sheet(labels: list[QRLabel]) -> str:
    cell_w, cell_h = 360, 210
    columns = 2
    rows = (len(labels) + columns - 1) // columns
    width = columns * cell_w
    height = max(cell_h, rows * cell_h)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    for index, label in enumerate(labels):
        x = (index % columns) * cell_w
        y = (index // columns) * cell_h
        parts.extend(
            [
                f'<rect x="{x + 16}" y="{y + 16}" width="{cell_w - 32}" height="{cell_h - 32}" fill="white" stroke="#111" stroke-width="1"/>',
                f'<rect x="{x + 34}" y="{y + 42}" width="92" height="92" fill="none" stroke="#111" stroke-width="3"/>',
                f'<text x="{x + 144}" y="{y + 58}" font-family="Arial" font-size="18" font-weight="700">{html.escape(label.display_label)}</text>',
                f'<text x="{x + 144}" y="{y + 88}" font-family="Arial" font-size="12">{html.escape(label.qr_value)}</text>',
                f'<text x="{x + 34}" y="{y + 160}" font-family="Arial" font-size="10">Install optional qrcode package for scannable image export.</text>',
            ]
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _markdown_sheet(labels: list[QRLabel]) -> str:
    lines = [
        "# EOAT QR Label Values",
        "",
        "These values intentionally encode only minimal local route identifiers.",
        "",
        "| Type | Target | QR Value |",
        "| --- | --- | --- |",
    ]
    for label in labels:
        lines.append(f"| {label.label_type} | {label.target_id} | `{label.qr_value}` |")
    return "\n".join(lines) + "\n"


def _inventory_rows(project_root: str | Path) -> list[dict[str, Any]]:
    paths = resolve_project_paths(project_root)
    if not paths.master_workbook.exists():
        return []
    try:
        return [repair_legacy_audit_lookup_shift(row) for row in row_dicts(paths.master_workbook, "EOAT Inventory")]
    except Exception:
        return []


def _minimal_machine_id(machine: str | int) -> str:
    text = _clean(machine)
    digits = "".join(char for char in text if char.isdigit())
    return digits or text.replace("Press", "").replace("Machine", "").strip() or text


def _unique(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _clean(value)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


__all__ = [
    "ALLOWED_QR_PREFIXES",
    "QRLabel",
    "audit_qr_value",
    "build_qr_labels",
    "export_qr_label_sheet",
    "machine_qr_value",
    "validate_qr_value",
]
