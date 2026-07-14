from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from .analysis_common import timestamp_for_report, write_timestamped_csv, write_timestamped_report
from .atlas_models import AtlasDataBundle, EOATRecord, MachineRecord, RecommendationResult, ToolRecord
from .atlas_utils import normalized_eoat_key, normalized_machine_key, normalized_tool_key, row_value
from .compatibility_engine import compatibility_matrix_rows
from .paths import resolve_project_paths
from .safe_files import ensure_directory

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class InstallPacketSection:
    title: str
    rows: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class InstallPacket:
    title: str
    subtitle: str
    generated_at: str
    context: str
    eoat_id: str = ""
    tool: str = ""
    machine: str = ""
    sections: tuple[InstallPacketSection, ...] = ()
    summary_lines: tuple[str, ...] = ()

    def markdown(self) -> str:
        lines = [
            f"# {self.title}",
            "",
            self.subtitle,
            "",
            f"- Generated: {self.generated_at}",
            f"- Context: {self.context}",
        ]
        if self.summary_lines:
            lines.extend(["", "## Summary", *[f"- {line}" for line in self.summary_lines if line]])
        for section in self.sections:
            lines.extend(["", f"## {section.title}"])
            if section.rows:
                for key, value in section.rows:
                    lines.append(f"- **{key}:** {value or 'Not recorded'}")
            else:
                lines.append("- No data available.")
        return "\n".join(lines).strip() + "\n"


@dataclass(frozen=True)
class QRDecodeResult:
    payload: str
    state: str
    message: str = ""


def atlas_export_dir(project_root: str | Path) -> Path:
    return ensure_directory(resolve_project_paths(project_root).final_handoff / "Atlas_Exports")


def atlas_install_packet_dir(project_root: str | Path) -> Path:
    return ensure_directory(atlas_export_dir(project_root) / "Install_Packets")


def atlas_qr_label_dir(project_root: str | Path) -> Path:
    return ensure_directory(atlas_export_dir(project_root) / "QR_Labels")


def export_compatibility_matrix(bundle: AtlasDataBundle, *, mode: str = "eoat_machine") -> Path:
    rows = compatibility_matrix_rows(bundle, mode=mode)
    return write_timestamped_csv(atlas_export_dir(bundle.project_root), f"Atlas_Fit_Check_{mode}", rows)


def export_documentation_gap_report(bundle: AtlasDataBundle) -> Path:
    rows = []
    for warning in bundle.warnings:
        rows.append(
            {
                "Severity": warning.severity,
                "Title": warning.title,
                "Message": warning.message,
                "Source": warning.source,
                "EOAT": warning.related_eoat_id,
                "Machine": warning.machine,
                "Tool": warning.tool,
                "Suggested Fix": warning.suggested_fix,
            }
        )
    for eoat in bundle.eoats:
        for warning in eoat.warnings:
            rows.append(
                {
                    "Severity": warning.severity,
                    "Title": warning.title,
                    "Message": warning.message,
                    "Source": warning.source,
                    "EOAT": warning.related_eoat_id or eoat.eoat_id,
                    "Machine": warning.machine,
                    "Tool": warning.tool,
                    "Suggested Fix": warning.suggested_fix,
                }
            )
    return write_timestamped_csv(atlas_export_dir(bundle.project_root), "Atlas_Documentation_Gaps", rows)


def export_photo_coverage_report(bundle: AtlasDataBundle) -> Path:
    rows = [
        {
            "EOAT": eoat.eoat_id,
            "Photo Count": eoat.photo_count,
            "Folder": eoat.photos.folder_path,
            "Folder Exists": eoat.photos.folder_exists,
            "Missing Categories": "; ".join(eoat.photos.missing_categories),
        }
        for eoat in bundle.eoats
    ]
    return write_timestamped_csv(atlas_export_dir(bundle.project_root), "Atlas_Photo_Coverage", rows)


def build_install_packet(
    bundle: AtlasDataBundle,
    *,
    eoat: EOATRecord | None = None,
    machine: MachineRecord | None = None,
    tool: ToolRecord | None = None,
    recommendation: RecommendationResult | None = None,
    context: str = "Atlas",
) -> InstallPacket:
    if eoat is None and recommendation and recommendation.best:
        eoat = _find_eoat(bundle, recommendation.best.eoat_id)
    if eoat is None and tool and tool.compatible_eoats:
        eoat = _find_eoat(bundle, tool.compatible_eoats[0])
    if eoat is None and machine:
        target = machine.current_eoat or (machine.compatible_eoats[0] if machine.compatible_eoats else "")
        eoat = _find_eoat(bundle, target)

    if tool is None and eoat and eoat.tools:
        tool = _find_tool(bundle, eoat.tools[0])
    if tool is None and recommendation and recommendation.best and recommendation.best.tools:
        tool = _find_tool(bundle, recommendation.best.tools[0])

    if machine is None and eoat and eoat.machines:
        machine = _find_machine(bundle, eoat.machines[0])
    if machine is None and tool and tool.compatible_machines:
        machine = _find_machine(bundle, tool.compatible_machines[0])

    generated_at = _generated_timestamp()
    eoat_id = eoat.eoat_id if eoat else ""
    tool_id = tool.tool if tool else ((eoat.tools[0] if eoat and eoat.tools else "") or "")
    machine_id = machine.machine if machine else ((eoat.machines[0] if eoat and eoat.machines else "") or "")
    title_target = eoat_id or tool_id or machine_id or "Atlas Context"

    warning_titles = _warning_titles(eoat, machine, tool)
    standards = _standard_titles(eoat)
    summary_lines = tuple(
        item
        for item in [
            f"EOAT {eoat_id}" if eoat_id else "",
            f"Tool {tool_id}" if tool_id else "",
            f"Machine {machine_id}" if machine_id else "",
            f"{eoat.documentation.score}% documentation" if eoat else "",
            f"{eoat.photo_count} linked photo(s)" if eoat else "",
            f"{len(warning_titles)} warning(s) to review" if warning_titles else "No indexed warnings for this context",
        ]
        if item
    )

    sections = (
        InstallPacketSection(
            "Header",
            _rows(
                ("EOAT ID", eoat_id),
                ("Tool number(s)", _join(eoat.tools if eoat else ((tool.tool,) if tool else ()))),
                (
                    "Part name / description",
                    _first_present(
                        eoat.part_description if eoat else "",
                        tool.part_description if tool else "",
                        eoat.part_family if eoat else "",
                        tool.part_family if tool else "",
                    ),
                ),
                ("Generated timestamp", generated_at),
            ),
        ),
        InstallPacketSection(
            "Fit Check",
            _rows(
                ("Compatible machine(s)", _join(eoat.machines if eoat else (tool.compatible_machines if tool else ()))),
                ("Selected machine", machine_id),
                ("Compatible EOAT(s)", _join(tool.compatible_eoats if tool else ((eoat.eoat_id,) if eoat else ()))),
                ("Compatible tool(s)", _join(machine.compatible_tools if machine else (eoat.tools if eoat else ()))),
            ),
        ),
        InstallPacketSection(
            "Robot / Machine Context",
            _rows(
                ("Machine", machine_id),
                ("Robot type", _first_present(machine.robot_type if machine else "", _join(eoat.robot_types if eoat else ()))),
                ("Robot model / controller", _first_present(machine.robot_model if machine else "", _join(eoat.robot_models if eoat else ()))),
                ("Controller", machine.controller if machine else ""),
                ("Machine documentation score", f"{machine.documentation_score}%" if machine else ""),
            ),
        ),
        InstallPacketSection(
            "EOAT Setup Details",
            _rows(
                ("EOAT type", eoat.eoat_type if eoat else ""),
                ("Status", eoat.status if eoat else ""),
                ("Connection type", eoat.connection_type if eoat else ""),
                ("Vacuum circuit info", eoat.vacuum_info if eoat else ""),
                ("Pressure circuit info", eoat.pressure_info if eoat else ""),
                ("Interchangeable / tubing info", eoat.tubing_notes if eoat else ""),
                ("Gripper info", eoat.gripper_info if eoat else ""),
                ("Sensor info", eoat.sensor_info if eoat else ""),
                ("Install notes", eoat.install_notes if eoat else ""),
            ),
        ),
        InstallPacketSection(
            "Photos / Documentation",
            _rows(
                ("Documentation score", f"{eoat.documentation.score}% - {eoat.documentation.status_label}" if eoat else ""),
                ("Linked photo count", str(eoat.photo_count) if eoat else ""),
                ("Missing photo categories", _join(eoat.photos.missing_categories if eoat else ())),
                ("Critical missing fields", _join(eoat.documentation.critical_missing_fields if eoat else ())),
                ("Photo folder reference", _short_reference(eoat.photos.folder_path) if eoat else ""),
            ),
        ),
        InstallPacketSection(
            "Warnings / Notes",
            _rows(
                ("Known issues", eoat.known_issues if eoat else ""),
                ("Warnings", "; ".join(warning_titles)),
                ("Recommendation limits", _recommendation_limit_text(recommendation)),
            ),
        ),
        InstallPacketSection(
            "Standards / References",
            _rows(
                ("Relevant standards", "; ".join(standards)),
                ("PM / inspection references", _pm_reference_text(eoat)),
                ("Source / reference notes", _source_reference_text(eoat, machine, tool)),
            ),
        ),
    )
    return InstallPacket(
        title=f"Install Packet: {title_target}",
        subtitle="Ready-to-run setup summary generated from cached EOAT Atlas data.",
        generated_at=generated_at,
        context=context,
        eoat_id=eoat_id,
        tool=tool_id,
        machine=machine_id,
        sections=sections,
        summary_lines=summary_lines,
    )


def export_install_packet(bundle: AtlasDataBundle, packet: InstallPacket) -> Path:
    return write_timestamped_report(
        atlas_install_packet_dir(bundle.project_root),
        f"Atlas_Install_Packet_{_safe_name(packet.eoat_id or packet.tool or packet.machine)}",
        packet.markdown(),
    )


def build_eoat_qr_payload(eoat: EOATRecord, *, mode: str = "compact") -> str:
    normalized_mode = _normalize_qr_payload_mode(mode)
    if normalized_mode == "deep_link":
        query = urlencode({"tool": _prefixed_tool(eoat.tools[0])}) if eoat.tools else ""
        return f"eoat-atlas://record/eoat/{quote(eoat.eoat_id, safe='')}{'?' + query if query else ''}"
    if normalized_mode == "json":
        payload = {
            "app": "EOAT Atlas",
            "record_type": "eoat",
            "eoat_id": eoat.eoat_id,
            "tools": [_prefixed_tool(tool) for tool in eoat.tools],
            "machines": [_prefixed_machine(machine) for machine in eoat.machines],
            "eoat_type": eoat.eoat_type,
            "status": eoat.status,
            "docs": eoat.documentation.score,
            "photos": eoat.photo_count,
            "warnings": eoat.warning_count,
        }
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    if normalized_mode == "full":
        return _full_eoat_qr_payload(eoat)
    return _compact_eoat_qr_payload(eoat)


def validate_eoat_qr_payload(payload: str, *, mode: str = "compact", eoat_id: str = "") -> list[str]:
    text = str(payload or "").strip()
    errors: list[str] = []
    if not text:
        errors.append("QR payload is empty.")
        return errors
    folded = text.casefold()
    if folded.startswith("tel:"):
        errors.append("QR payload must not start with tel:.")
    if folded.startswith("call:"):
        errors.append("QR payload must not start with call:.")
    if text[:1].isdigit():
        errors.append("QR payload must not start with a digit.")
    digits = "".join(char for char in text if char.isdigit())
    phone_like_chars = set("0123456789+-(). ")
    if text.isdigit() or (len(digits) >= 7 and all(char in phone_like_chars for char in text)):
        errors.append("QR payload looks like a phone number. Add an EOAT Atlas prefix or app link.")
    if _normalize_qr_payload_mode(mode) == "compact":
        if not text.startswith("EOAT_ATLAS_RECORD"):
            errors.append("Compact QR payload must start with EOAT_ATLAS_RECORD.")
        if eoat_id and eoat_id.casefold() not in folded:
            errors.append("Compact QR payload must include the EOAT ID.")
        for tool_value in _compact_field_values(text, "TOOL"):
            if tool_value and tool_value.isdigit():
                errors.append("Compact QR payload tool values must be prefixed as T-<tool>.")
            if tool_value and not tool_value.startswith("T-") and tool_value != "Not recorded":
                errors.append("Compact QR payload tool values must use the T- prefix.")
    return errors


def decode_qr_payload_from_image(path: str | Path) -> QRDecodeResult:
    target = Path(path)
    if not target.exists():
        return QRDecodeResult("", "file_missing", f"QR image does not exist: {target}")
    try:
        import cv2  # type: ignore[import-not-found]
    except Exception as exc:
        return QRDecodeResult("", "decoder_missing", f"QR image decode requires opencv-python-headless: {exc}")
    image = cv2.imread(str(target))
    if image is None:
        return QRDecodeResult("", "decode_failed", f"Could not read QR image: {target}")
    detector = cv2.QRCodeDetector()
    payload, _points, _straight = detector.detectAndDecode(image)
    if payload:
        return QRDecodeResult(str(payload), "decoded")
    try:
        from PIL import Image

        with Image.open(target) as label:
            width, height = label.size
            crop = label.crop((0, 0, min(width, height), min(width, height)))
            crop_path = target.with_name(f"{target.stem}_qr_crop{target.suffix}")
            crop.save(crop_path)
        try:
            crop_image = cv2.imread(str(crop_path))
            if crop_image is not None:
                payload, _points, _straight = detector.detectAndDecode(crop_image)
                if payload:
                    return QRDecodeResult(str(payload), "decoded")
        finally:
            try:
                crop_path.unlink()
            except OSError:
                pass
    except Exception:
        pass
    return QRDecodeResult("", "decode_failed", f"No QR payload could be decoded from {target.name}.")


def recommended_qr_print_size(payload: str, *, error_correction: str = "high") -> str:
    length = len(str(payload or ""))
    if length <= 250:
        inches = 1.0
    elif length <= 600:
        inches = 1.25
    elif length <= 1000:
        inches = 1.5
    elif length <= 1600:
        inches = 2.0
    else:
        inches = 2.5
    correction = _normalize_qr_error_correction(error_correction)
    if correction in {"quartile", "high"} and length > 250:
        inches += 0.25
    if correction == "high" and length > 1000:
        inches += 0.25
    return f"{inches:.2f}\" square"


def qr_payload_warning(payload: str, *, mode: str = "compact", error_correction: str = "high") -> str:
    length = len(payload)
    normalized_mode = _normalize_qr_payload_mode(mode)
    recommended = recommended_qr_print_size(payload, error_correction=error_correction)
    if normalized_mode == "full":
        return (
            "Full Offline Record mode creates a large QR payload. Use Compact Label or Atlas Deep Link for small "
            f"printed labels.\nPayload length: {length} chars. Recommended minimum printed QR size: {recommended} "
            f"at {_qr_correction_label(error_correction)} error correction."
        )
    if length > 900:
        return (
            "This QR payload is large. Use Compact Human-Readable Text or Atlas Deep Link for small printed labels.\n"
            f"Payload length: {length} chars. Recommended minimum printed QR size: {recommended} "
            f"at {_qr_correction_label(error_correction)} error correction."
        )
    return ""


def export_eoat_qr_label(
    bundle: AtlasDataBundle,
    eoat: EOATRecord,
    *,
    payload_mode: str = "compact",
    error_correction: str = "high",
    label_size: str = "medium",
    packet_path: str | Path | None = None,
) -> Path:
    try:
        import qrcode
        from PIL import Image, ImageDraw
        from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q
    except Exception as exc:  # pragma: no cover - depends on optional runtime packages
        raise RuntimeError("QR label generation requires the optional qrcode and Pillow packages.") from exc

    output_dir = atlas_qr_label_dir(bundle.project_root)
    payload = build_eoat_qr_payload(eoat, mode=payload_mode)
    if packet_path and payload_mode == "full":
        payload = payload.rstrip() + f"\nPACKET:{Path(packet_path).name}\n"
    LOGGER.info("Generating EOAT Atlas QR label for %s with payload: %s", eoat.eoat_id, payload)
    validation_errors = validate_eoat_qr_payload(payload, mode=payload_mode, eoat_id=eoat.eoat_id)
    if validation_errors:
        raise ValueError(" ".join(validation_errors))
    correction_map = {
        "low": ERROR_CORRECT_L,
        "medium": ERROR_CORRECT_M,
        "quartile": ERROR_CORRECT_Q,
        "high": ERROR_CORRECT_H,
    }
    correction = correction_map[_normalize_qr_error_correction(error_correction)]
    qr = qrcode.QRCode(border=2, box_size=10, error_correction=correction)
    qr.add_data(payload)
    qr.make(fit=True)
    label_w, label_h, qr_size = _qr_label_dimensions(label_size)
    qr_image = qr.make_image(fill_color="black", back_color="white").convert("RGB").resize((qr_size, qr_size))

    label = Image.new("RGB", (label_w, label_h), "white")
    draw = ImageDraw.Draw(label)
    margin = 34
    label.paste(qr_image, (margin, margin))
    x_text = margin + qr_size + 36
    y_text = margin + 8
    mode_label = _qr_mode_label(payload_mode)
    lines = [
        eoat.eoat_id,
        f"Tool: {_join(eoat.tools[:5]) or 'Not recorded'}",
        f"Machines: {_join(eoat.machines[:9]) or 'Not recorded'}{_more_count(eoat.machines, 9)}",
        f"Type: {eoat.eoat_type or 'Not recorded'}",
        f"Docs: {eoat.documentation.score}% | Photos: {eoat.photo_count} | Warnings: {eoat.warning_count}",
        f"Payload mode: {mode_label}",
        f"Generated: {_generated_date()}",
        "Scan to view EOAT Atlas record",
        _qr_mode_instruction(payload_mode),
    ]
    if packet_path:
        lines.append(f"Packet: {Path(packet_path).name}")
    for index, line in enumerate(lines):
        draw.text((x_text, y_text + index * 34), line, fill="black")
    draw.rectangle((24, 24, label_w - 24, label_h - 24), outline="#111111", width=2)
    footer_y = margin + qr_size + 28
    draw.text(
        (margin, footer_y),
        (
            f"Payload: {len(payload)} chars | Error correction: {_qr_correction_label(error_correction)} | "
            f"Min QR size: {recommended_qr_print_size(payload, error_correction=error_correction)}"
        ),
        fill="#111111",
    )
    if warning := qr_payload_warning(payload, mode=payload_mode, error_correction=error_correction):
        draw.text((margin, footer_y + 30), warning.splitlines()[0][:120], fill="#8a4b00")
    path = _unique_timestamped_path(output_dir, f"Atlas_QR_{_safe_name(eoat.eoat_id)}", ".png")
    label.save(path)
    decoded = decode_qr_payload_from_image(path)
    if decoded.payload != payload:
        LOGGER.warning(
            "EOAT Atlas QR decode verification failed for %s. Intended=%r decoded=%r state=%s",
            path,
            payload,
            decoded.payload,
            decoded.state,
        )
        raise RuntimeError(f"Generated QR could not be verified. {decoded.message or 'Decoded payload did not match preview.'}")
    return path


def export_eoat_summary(bundle: AtlasDataBundle, eoat: EOATRecord) -> Path:
    warning_lines = [f"- {warning.title}: {warning.message}" for warning in eoat.warnings] or ["No warnings indexed."]
    markdown = "\n".join(
        [
            f"# EOAT Summary: {eoat.eoat_id}",
            "",
            f"- EOAT Type: {eoat.eoat_type}",
            f"- Status: {eoat.status}",
            f"- Tools: {', '.join(eoat.tools)}",
            f"- Machines: {', '.join(eoat.machines)}",
            f"- Connection: {eoat.connection_type}",
            f"- Documentation: {eoat.documentation.score}% ({eoat.documentation.status_label})",
            f"- Photos: {eoat.photo_count}",
            "",
            "## Install Checklist",
            "- Verify EOAT ID and tool/machine compatibility.",
            "- Inspect cups, grippers, tubing, sensors, quick disconnects, and mounting hardware as applicable.",
            "- Review all warnings before production.",
            "",
            "## Warnings",
            *warning_lines,
        ]
    )
    return write_timestamped_report(atlas_export_dir(bundle.project_root), f"Atlas_EOAT_{_safe_name(eoat.eoat_id)}", markdown)


def export_machine_summary(bundle: AtlasDataBundle, machine: MachineRecord) -> Path:
    warning_lines = [f"- {warning.title}: {warning.message}" for warning in machine.warnings] or ["No warnings indexed."]
    markdown = "\n".join(
        [
            f"# Machine Summary: {machine.machine}",
            "",
            f"- Robot Type: {machine.robot_type}",
            f"- Robot Model/Controller: {machine.robot_model}",
            f"- Compatible EOATs: {', '.join(machine.compatible_eoats)}",
            f"- Compatible Tools: {', '.join(machine.compatible_tools)}",
            f"- Documentation Score: {machine.documentation_score}%",
            "",
            "## Warnings",
            *warning_lines,
        ]
    )
    return write_timestamped_report(
        atlas_export_dir(bundle.project_root), f"Atlas_Machine_{_safe_name(machine.machine)}", markdown
    )


def export_tool_summary(bundle: AtlasDataBundle, tool: ToolRecord) -> Path:
    warning_lines = [f"- {warning.title}: {warning.message}" for warning in tool.warnings] or ["No warnings indexed."]
    markdown = "\n".join(
        [
            f"# Tool Summary: {tool.tool}",
            "",
            f"- Part Description: {_first_present(tool.part_description, tool.part_family, ', '.join(tool.parts))}",
            f"- Compatible EOATs: {', '.join(tool.compatible_eoats)}",
            f"- Compatible Machines: {', '.join(tool.compatible_machines)}",
            f"- Source: {tool.source or 'Atlas cached index'}",
            "",
            "## Warnings",
            *warning_lines,
        ]
    )
    return write_timestamped_report(atlas_export_dir(bundle.project_root), f"Atlas_Tool_{_safe_name(tool.tool)}", markdown)


def export_compare_summary(
    project_root: str | Path,
    title: str,
    rows: list[dict[str, str]],
    columns: list[str],
) -> Path:
    lines = [f"# {title}", "", f"- Generated: {_generated_timestamp()}", ""]
    current_category = ""
    for row in rows:
        category = row.get("Category", "")
        if category != current_category:
            current_category = category
            lines.extend(["", f"## {category or 'Comparison'}"])
        field = row.get("Field", "")
        difference = row.get("Difference", "")
        values = "; ".join(f"{column}: {row.get(column, '-') or '-'}" for column in columns)
        lines.append(f"- **{field}:** {values} ({difference or 'Same'})")
    return write_timestamped_report(atlas_export_dir(project_root), f"Atlas_Compare_{_safe_name(title)}", "\n".join(lines).strip() + "\n")


def export_recommendation_summary(bundle: AtlasDataBundle, result: RecommendationResult) -> Path:
    best = result.best.eoat_id if result.best else "No recommendation"
    candidate_lines = [
        f"- #{candidate.rank} {candidate.eoat_id} ({candidate.score}): {candidate.summary}"
        for candidate in result.candidates
    ] or ["No candidates found."]
    factor_lines = _recommendation_factor_lines(result.best) if result.best else ["No scoring factors available."]
    warning_lines = [f"- {warning.title}: {warning.message}" for warning in result.warnings] or ["No warnings indexed."]
    markdown = "\n".join(
        [
            f"# EOAT Atlas Recommendation: {result.query}",
            "",
            result.summary,
            "",
            f"- Best EOAT: {best}",
            f"- Compatible Machines: {', '.join(result.compatible_machines)}",
            "",
            "## Candidates",
            *candidate_lines,
            "",
            "## Score Breakdown",
            *factor_lines,
            "",
            "## Before Install",
            *[f"{index}. {item}" for index, item in enumerate(result.install_checklist, start=1)],
            "",
            "## Warnings",
            *warning_lines,
        ]
    )
    return write_timestamped_report(
        atlas_export_dir(bundle.project_root), f"Atlas_Recommendation_{_safe_name(result.query)[:40]}", markdown
    )


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value).strip("_") or "Summary"


def _generated_timestamp() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _unique_timestamped_path(folder: Path, base_name: str, suffix: str) -> Path:
    stamp = timestamp_for_report()
    path = folder / f"{base_name}_{stamp}{suffix}"
    if not path.exists():
        return path
    from datetime import datetime

    return folder / f"{base_name}_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}{suffix}"


def _rows(*rows: tuple[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple((key, str(value or "").strip()) for key, value in rows)


def _join(values) -> str:
    return ", ".join(str(value).strip() for value in values if str(value).strip())


def _first_present(*values: str) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _short_reference(value: str, *, keep_parts: int = 4) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parts = Path(text).parts
    if len(parts) <= keep_parts:
        return text
    return str(Path(*parts[-keep_parts:]))


def _warning_titles(eoat: EOATRecord | None, machine: MachineRecord | None, tool: ToolRecord | None) -> list[str]:
    warnings = []
    for source in (eoat, machine, tool):
        if source is None:
            continue
        warnings.extend(f"{warning.title}: {warning.message}" for warning in source.warnings)
    return warnings[:10]


def _standard_titles(eoat: EOATRecord | None) -> list[str]:
    if eoat is None:
        return []
    return [standard.title for standard in eoat.standards[:8] if standard.title]


def _recommendation_limit_text(recommendation: RecommendationResult | None) -> str:
    if recommendation is None:
        return ""
    if recommendation.best is None:
        return "No recommended EOAT was found for the original query."
    limitations = [reason for reason in recommendation.best.reasons if "warning" in reason.casefold()]
    if recommendation.warnings:
        limitations.extend(warning.title for warning in recommendation.warnings[:4])
    return "; ".join(dict.fromkeys(limitations))


def _pm_reference_text(eoat: EOATRecord | None) -> str:
    if eoat is None:
        return "Use PM / Inspection guidance after selecting an EOAT."
    frequency = ""
    for row in eoat.source_rows:
        frequency = row_value(row, ("Maintenance Frequency", "PM Frequency"))
        if frequency:
            break
    base = "PM / Inspection page: inspect cups/grippers, tubing, sensors, connections, fasteners, and warnings before install."
    return f"{base} Maintenance frequency: {frequency}." if frequency else base


def _source_reference_text(
    eoat: EOATRecord | None, machine: MachineRecord | None, tool: ToolRecord | None
) -> str:
    pieces = []
    if eoat is not None:
        pieces.append(f"{len(eoat.source_rows)} EOAT source row(s)")
    if machine is not None:
        pieces.append(f"{len(machine.source_rows)} machine source row(s)")
    if tool is not None:
        pieces.append(tool.source or "Tool source indexed")
    return "; ".join(piece for piece in pieces if piece)


def _generated_date() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d")


def _compact_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _more_count(values, visible: int) -> str:
    count = len(tuple(values))
    if count <= visible:
        return ""
    return f" (+{count - visible} more)"


def _normalize_qr_payload_mode(mode: str) -> str:
    text = str(mode or "compact").strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "compact_label": "compact",
        "compact_human_readable": "compact",
        "compact_human_readable_text": "compact",
        "text": "compact",
        "deep": "deep_link",
        "atlas_link": "deep_link",
        "atlas_deep_link": "deep_link",
        "deeplink": "deep_link",
        "json_record": "json",
        "full_offline": "full",
        "full_offline_record": "full",
        "id": "compact",
        "eoat_id": "compact",
        "id_only": "compact",
    }
    text = aliases.get(text, text)
    return text if text in {"compact", "deep_link", "json", "full"} else "compact"


def _normalize_qr_error_correction(value: str) -> str:
    text = str(value or "high").strip().casefold()
    if text.startswith("l"):
        return "low"
    if text.startswith("m"):
        return "medium"
    if text.startswith("q"):
        return "quartile"
    return "high"


def _compact_eoat_qr_payload(eoat: EOATRecord) -> str:
    tools = ",".join(_prefixed_tool(tool) for tool in eoat.tools[:3]) or "Not recorded"
    machines = ",".join(_prefixed_machine(machine) for machine in eoat.machines[:9]) or "Not recorded"
    pieces = [
        "EOAT_ATLAS_RECORD",
        f"EOAT={eoat.eoat_id}",
        f"TOOL={tools}{_more_count(eoat.tools, 3)}",
        f"MACHINES={machines}{_more_count(eoat.machines, 9)}",
        f"TYPE={eoat.eoat_type or 'Not recorded'}",
        f"STATUS={eoat.status or 'Not recorded'}",
        f"DOCS={eoat.documentation.score}%",
        f"PHOTOS={eoat.photo_count}",
        f"WARNINGS={eoat.warning_count}",
        f"GENERATED={_generated_date()}",
    ]
    return "; ".join(pieces)


def _full_eoat_qr_payload(eoat: EOATRecord) -> str:
    rows = [
        ("EOAT_ATLAS_FULL_RECORD", ""),
        ("EOAT", eoat.eoat_id),
        ("TYPE", _compact_text(eoat.eoat_type, 42)),
        ("STATUS", _compact_text(eoat.status, 36)),
        ("TOOLS", _join(_prefixed_tool(tool) for tool in eoat.tools)),
        ("PART", _compact_text(_first_present(eoat.part_description, eoat.part_family), 80)),
        ("MACHINES", _join(_prefixed_machine(machine) for machine in eoat.machines)),
        ("ROBOT", _compact_text(_first_present(_join(eoat.robot_models), _join(eoat.robot_types)), 80)),
        ("CONNECTION", _compact_text(eoat.connection_type, 90)),
        ("DOCS", f"{eoat.documentation.score}%"),
        ("PHOTOS", str(eoat.photo_count)),
        ("WARNINGS", str(eoat.warning_count)),
        ("MISSING_PHOTOS", _join(eoat.photos.missing_categories)),
        ("ROBOT_TYPE", _compact_text(_join(eoat.robot_types), 80)),
        ("ROBOT_MODEL", _compact_text(_join(eoat.robot_models), 100)),
        ("VACUUM", _compact_text(eoat.vacuum_info, 180)),
        ("PRESSURE", _compact_text(eoat.pressure_info, 180)),
        ("INTERCHANGEABLE", _compact_text(eoat.tubing_notes, 180)),
        ("GRIPPER", _compact_text(eoat.gripper_info, 180)),
        ("SENSORS", _compact_text(eoat.sensor_info, 160)),
        ("KNOWN_ISSUES", _compact_text(eoat.known_issues, 220)),
        ("INSTALL_NOTES", _compact_text(eoat.install_notes, 220)),
        ("STANDARDS", _compact_text("; ".join(_standard_titles(eoat)), 220)),
        ("PM", _compact_text(_pm_reference_text(eoat), 220)),
        ("NOTE", "SEARCH EOAT ID IN EOAT ATLAS FOR FULL PROFILE."),
        ("GENERATED", _generated_date()),
    ]
    lines = []
    for key, value in rows:
        lines.append(f"{key}:{value}" if value else key)
    return "\n".join(lines) + "\n"


def _qr_mode_label(mode: str) -> str:
    normalized = _normalize_qr_payload_mode(mode)
    return {
        "compact": "Compact Human-Readable Text",
        "deep_link": "Atlas Deep Link",
        "json": "JSON Record",
        "full": "Full Offline Record",
    }.get(normalized, "Compact Human-Readable Text")


def _qr_mode_instruction(mode: str) -> str:
    normalized = _normalize_qr_payload_mode(mode)
    if normalized == "deep_link":
        return "QR opens EOAT Atlas link where supported"
    if normalized == "json":
        return "QR contains compact EOAT Atlas JSON record"
    if normalized == "full":
        return "QR contains full offline EOAT Atlas text record"
    return "QR contains compact EOAT Atlas text record"


def _qr_correction_label(value: str) -> str:
    return {
        "low": "Low",
        "medium": "Medium",
        "quartile": "Quartile",
        "high": "High",
    }[_normalize_qr_error_correction(value)]


def _qr_label_dimensions(label_size: str) -> tuple[int, int, int]:
    normalized = str(label_size or "medium").strip().casefold()
    if normalized.startswith("s"):
        return 760, 480, 260
    if normalized.startswith("l"):
        return 1080, 680, 390
    return 900, 560, 310


def _prefixed_tool(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.upper().startswith("T-"):
        return text
    return f"T-{text}"


def _prefixed_machine(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.upper().startswith("M-"):
        return text
    key = normalized_machine_key(text)
    return f"M-{key or text}"


def _compact_field_values(payload: str, field_name: str) -> list[str]:
    prefix = f"{field_name}="
    values: list[str] = []
    for part in payload.split(";"):
        text = part.strip()
        if not text.startswith(prefix):
            continue
        raw = text[len(prefix) :].strip()
        values.extend(item.strip() for item in raw.split(",") if item.strip())
    return values


def _recommendation_factor_lines(candidate) -> list[str]:
    if candidate is None or not getattr(candidate, "factors", ()):
        return ["No scoring factors available."]
    lines = [f"- Total Score: {candidate.score}"]
    for label, polarity in (("Positive", "positive"), ("Neutral", "neutral"), ("Penalties / Warnings", "negative")):
        group = [factor for factor in candidate.factors if factor.polarity == polarity]
        if not group:
            continue
        lines.append(f"- {label}:")
        for factor in group:
            evidence = f" Evidence: {factor.evidence}." if factor.evidence else ""
            details = f" {factor.details}" if factor.details else ""
            lines.append(f"  - {factor.points:+d} {factor.label}.{evidence}{details}".rstrip())
    return lines


def _find_eoat(bundle: AtlasDataBundle, eoat_id: str) -> EOATRecord | None:
    key = normalized_eoat_key(eoat_id)
    return next((record for record in bundle.eoats if normalized_eoat_key(record.eoat_id) == key), None)


def _find_machine(bundle: AtlasDataBundle, machine_id: str) -> MachineRecord | None:
    key = normalized_machine_key(machine_id)
    return next((record for record in bundle.machines if normalized_machine_key(record.machine) == key), None)


def _find_tool(bundle: AtlasDataBundle, tool_id: str) -> ToolRecord | None:
    key = normalized_tool_key(tool_id)
    return next((record for record in bundle.tools if normalized_tool_key(record.tool) == key), None)


__all__ = [
    "InstallPacket",
    "InstallPacketSection",
    "QRDecodeResult",
    "atlas_export_dir",
    "atlas_install_packet_dir",
    "atlas_qr_label_dir",
    "build_eoat_qr_payload",
    "build_install_packet",
    "decode_qr_payload_from_image",
    "export_compatibility_matrix",
    "export_documentation_gap_report",
    "export_eoat_summary",
    "export_eoat_qr_label",
    "export_install_packet",
    "export_machine_summary",
    "export_photo_coverage_report",
    "export_recommendation_summary",
    "export_tool_summary",
    "export_compare_summary",
    "qr_payload_warning",
    "recommended_qr_print_size",
    "validate_eoat_qr_payload",
]
