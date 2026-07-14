from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .atlas_models import (
    AtlasDataBundle,
    EOATRecord,
    MachineRecord,
    PhotoItem,
    StandardReference,
    ToolRecord,
    WarningItem,
)
from .atlas_utils import display_value, normalized_eoat_key, normalized_machine_key, normalized_tool_key, row_value
from .paths import resolve_project_paths
from .safe_files import ensure_directory

COMPATIBILITY_CONFIRMED = "Confirmed"
COMPATIBILITY_PARTIAL = "Partially Confirmed"
COMPATIBILITY_NOT_CONFIRMED = "Not Confirmed"
COMPATIBILITY_MISSING_DATA = "Missing Data"
COMPATIBILITY_MANUAL_OVERRIDE = "Manual Override Used"

PACKET_TYPE_STANDARD = "standard_changeover"
PACKET_TYPE_SETUP_VERIFICATION = "setup_verification"
PACKET_TYPE_MAINTENANCE_PM = "maintenance_pm"
PACKET_TYPE_DOCUMENTATION_REVIEW = "documentation_review"
PACKET_TYPE_CHOICES = (
    PACKET_TYPE_STANDARD,
    PACKET_TYPE_SETUP_VERIFICATION,
    PACKET_TYPE_MAINTENANCE_PM,
    PACKET_TYPE_DOCUMENTATION_REVIEW,
)
PACKET_TYPE_LABELS = {
    PACKET_TYPE_STANDARD: "Standard Changeover Packet",
    PACKET_TYPE_SETUP_VERIFICATION: "Setup Verification Packet",
    PACKET_TYPE_MAINTENANCE_PM: "Maintenance / PM Packet",
    PACKET_TYPE_DOCUMENTATION_REVIEW: "Documentation Review Packet",
}

PHOTO_NONE = "none"
PHOTO_KEY = "key"
PHOTO_ALL = "all"
PHOTO_INCLUSION_CHOICES = (PHOTO_NONE, PHOTO_KEY, PHOTO_ALL)
PHOTO_INCLUSION_LABELS = {
    PHOTO_NONE: "No photos",
    PHOTO_KEY: "Key photos only",
    PHOTO_ALL: "All photos",
}

OPEN_PACKET_CHOICES = ("in_app", "external_pdf", "open_folder", "ask_each_time")
DETAIL_LEVEL_CHOICES = ("standard", "detailed")
STARTING_ITEM_CHOICES = ("machine", "tool", "eoat")


@dataclass(frozen=True)
class SetupPacketOptions:
    packet_type: str = PACKET_TYPE_STANDARD
    photo_inclusion: str = PHOTO_KEY
    open_after_generation: str = "ask_each_time"
    include_qr_label: bool = False
    detail_level: str = "standard"
    manual_override_used: bool = False
    manual_override_note: str = ""
    include_setup_summary: bool = True
    include_compatibility_result: bool = True
    include_requirements_check: bool = True
    include_warnings: bool = True
    include_alternatives: bool = True
    include_eoat_photo: bool = True
    include_setup_checklist: bool = True
    include_detailed_record_information: bool = False
    include_related_records: bool = False
    include_extra_notes: bool = False

    def normalized(self) -> SetupPacketOptions:
        return SetupPacketOptions(
            packet_type=_choice(self.packet_type, PACKET_TYPE_CHOICES, PACKET_TYPE_STANDARD),
            photo_inclusion=_choice(self.photo_inclusion, PHOTO_INCLUSION_CHOICES, PHOTO_KEY),
            open_after_generation=_choice(self.open_after_generation, OPEN_PACKET_CHOICES, "ask_each_time"),
            include_qr_label=bool(self.include_qr_label),
            detail_level=_choice(self.detail_level, DETAIL_LEVEL_CHOICES, "standard"),
            manual_override_used=bool(self.manual_override_used),
            manual_override_note=str(self.manual_override_note or "").strip(),
            include_setup_summary=bool(self.include_setup_summary),
            include_compatibility_result=bool(self.include_compatibility_result),
            include_requirements_check=bool(self.include_requirements_check),
            include_warnings=bool(self.include_warnings),
            include_alternatives=bool(self.include_alternatives),
            include_eoat_photo=bool(self.include_eoat_photo),
            include_setup_checklist=bool(self.include_setup_checklist),
            include_detailed_record_information=bool(self.include_detailed_record_information),
            include_related_records=bool(self.include_related_records),
            include_extra_notes=bool(self.include_extra_notes),
        )

    @property
    def packet_type_label(self) -> str:
        return PACKET_TYPE_LABELS[self.normalized().packet_type]

    @property
    def photo_inclusion_label(self) -> str:
        return PHOTO_INCLUSION_LABELS[self.normalized().photo_inclusion]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.normalized())


@dataclass(frozen=True)
class RelationshipCheck:
    relationship: str
    status: str
    source: str = ""
    notes: tuple[str, ...] = ()

    @property
    def confirmed(self) -> bool:
        return self.status == COMPATIBILITY_CONFIRMED

    @property
    def missing_data(self) -> bool:
        return self.status == COMPATIBILITY_MISSING_DATA


@dataclass(frozen=True)
class SetupPacketValidationResult:
    status: str
    checks: tuple[RelationshipCheck, ...] = ()
    confirmed_links: tuple[str, ...] = ()
    missing_data: tuple[str, ...] = ()
    warnings: tuple[WarningItem, ...] = ()
    sources: tuple[str, ...] = ()
    manual_override_used: bool = False

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SetupPacketSection:
    title: str
    rows: tuple[tuple[str, str], ...] = ()
    bullets: tuple[str, ...] = ()
    checklist: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SetupPacketContext:
    project_root: str
    machine_id: str
    tool_id: str
    eoat_id: str
    options: SetupPacketOptions
    validation: SetupPacketValidationResult
    generated_at: str
    machine: MachineRecord | None = None
    tool: ToolRecord | None = None
    eoat: EOATRecord | None = None
    robot_info: dict[str, Any] = field(default_factory=dict)
    photos: tuple[PhotoItem, ...] = ()
    selected_photos: tuple[PhotoItem, ...] = ()
    standards: tuple[StandardReference, ...] = ()
    warnings: tuple[WarningItem, ...] = ()
    missing_key_data: tuple[str, ...] = ()
    source_files: tuple[tuple[str, str, str], ...] = ()
    estimated_sections: tuple[str, ...] = ()
    export_path: str = ""

    @property
    def packet_type_label(self) -> str:
        return self.options.packet_type_label

    @property
    def photo_inclusion_label(self) -> str:
        return self.options.photo_inclusion_label

    @property
    def documentation_score(self) -> int:
        return self.eoat.documentation.score if self.eoat else 0

    @property
    def photo_count(self) -> int:
        return len(self.photos)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)


@dataclass(frozen=True)
class SetupPacketExportResult:
    path: Path
    status: str = "ok"
    message: str = ""


def atlas_setup_packet_dir(project_root: str | Path) -> Path:
    return ensure_directory(resolve_project_paths(project_root).final_handoff / "Atlas_Exports" / "Setup_Packets")


def compatible_tools_for_machine(bundle: AtlasDataBundle, machine_id: str) -> tuple[str, ...]:
    machine_key = normalized_machine_key(machine_id)
    values: list[str] = []
    values.extend(bundle.indexes.tools_by_machine.get(machine_key, ()))
    machine = find_machine(bundle, machine_id)
    if machine:
        values.extend(machine.compatible_tools)
    for tool in bundle.tools:
        if any(normalized_machine_key(value) == machine_key for value in tool.compatible_machines):
            values.append(tool.tool)
    return _sort_tools(values)


def compatible_eoats_for_machine(bundle: AtlasDataBundle, machine_id: str) -> tuple[str, ...]:
    machine_key = normalized_machine_key(machine_id)
    values: list[str] = []
    values.extend(bundle.indexes.eoats_by_machine.get(machine_key, ()))
    machine = find_machine(bundle, machine_id)
    if machine:
        values.extend(machine.compatible_eoats)
    for eoat in bundle.eoats:
        if any(normalized_machine_key(value) == machine_key for value in eoat.machines):
            values.append(eoat.eoat_id)
    return _sort_eoats(values)


def compatible_machines_for_tool(bundle: AtlasDataBundle, tool_id: str) -> tuple[str, ...]:
    tool_key = normalized_tool_key(tool_id)
    values: list[str] = []
    values.extend(bundle.indexes.machines_by_tool.get(tool_key, ()))
    tool = find_tool(bundle, tool_id)
    if tool:
        values.extend(tool.compatible_machines)
    for machine in bundle.machines:
        if any(normalized_tool_key(value) == tool_key for value in machine.compatible_tools):
            values.append(machine.machine)
    return _sort_machines(values)


def compatible_eoats_for_tool(bundle: AtlasDataBundle, tool_id: str) -> tuple[str, ...]:
    tool_key = normalized_tool_key(tool_id)
    values: list[str] = []
    values.extend(bundle.indexes.eoats_by_tool.get(tool_key, ()))
    tool = find_tool(bundle, tool_id)
    if tool:
        values.extend(tool.compatible_eoats)
    for eoat in bundle.eoats:
        if any(normalized_tool_key(value) == tool_key for value in eoat.tools):
            values.append(eoat.eoat_id)
    return _sort_eoats(values)


def compatible_tools_for_eoat(bundle: AtlasDataBundle, eoat_id: str) -> tuple[str, ...]:
    eoat_key = normalized_eoat_key(eoat_id)
    values: list[str] = []
    eoat = find_eoat(bundle, eoat_id)
    if eoat:
        values.extend(eoat.tools)
    for tool in bundle.tools:
        if any(normalized_eoat_key(value) == eoat_key for value in tool.compatible_eoats):
            values.append(tool.tool)
    return _sort_tools(values)


def compatible_machines_for_eoat(bundle: AtlasDataBundle, eoat_id: str) -> tuple[str, ...]:
    eoat_key = normalized_eoat_key(eoat_id)
    values: list[str] = []
    values.extend(bundle.indexes.machines_by_eoat.get(eoat_key, ()))
    eoat = find_eoat(bundle, eoat_id)
    if eoat:
        values.extend(eoat.machines)
    for machine in bundle.machines:
        if any(normalized_eoat_key(value) == eoat_key for value in machine.compatible_eoats):
            values.append(machine.machine)
    return _sort_machines(values)


def selectable_tools(
    bundle: AtlasDataBundle,
    *,
    machine_id: str = "",
    eoat_id: str = "",
    allow_unconfirmed: bool = False,
) -> tuple[ToolRecord, ...]:
    if allow_unconfirmed:
        return tuple(bundle.tools)
    if not machine_id and not eoat_id:
        return tuple(bundle.tools)
    groups = []
    if machine_id:
        groups.append(compatible_tools_for_machine(bundle, machine_id))
    if eoat_id:
        groups.append(compatible_tools_for_eoat(bundle, eoat_id))
    allowed = _intersection(*groups)
    allowed_keys = {normalized_tool_key(value) for value in allowed}
    return tuple(tool for tool in bundle.tools if normalized_tool_key(tool.tool) in allowed_keys)


def selectable_machines(
    bundle: AtlasDataBundle,
    *,
    tool_id: str = "",
    eoat_id: str = "",
    allow_unconfirmed: bool = False,
) -> tuple[MachineRecord, ...]:
    if allow_unconfirmed:
        return tuple(bundle.machines)
    if not tool_id and not eoat_id:
        return tuple(bundle.machines)
    groups = []
    if tool_id:
        groups.append(compatible_machines_for_tool(bundle, tool_id))
    if eoat_id:
        groups.append(compatible_machines_for_eoat(bundle, eoat_id))
    allowed = _intersection(*groups)
    allowed_keys = {normalized_machine_key(value) for value in allowed}
    return tuple(machine for machine in bundle.machines if normalized_machine_key(machine.machine) in allowed_keys)


def selectable_eoats(
    bundle: AtlasDataBundle,
    *,
    machine_id: str = "",
    tool_id: str = "",
    allow_unconfirmed: bool = False,
) -> tuple[EOATRecord, ...]:
    if allow_unconfirmed:
        return tuple(bundle.eoats)
    if not machine_id and not tool_id:
        return tuple(bundle.eoats)
    groups = []
    if machine_id:
        groups.append(compatible_eoats_for_machine(bundle, machine_id))
    if tool_id:
        groups.append(compatible_eoats_for_tool(bundle, tool_id))
    allowed = _intersection(*groups)
    allowed_keys = {normalized_eoat_key(value) for value in allowed}
    return tuple(eoat for eoat in bundle.eoats if normalized_eoat_key(eoat.eoat_id) in allowed_keys)


def validate_setup_context(
    bundle: AtlasDataBundle,
    machine_id: str,
    tool_id: str,
    eoat_id: str,
    *,
    manual_override_used: bool = False,
) -> SetupPacketValidationResult:
    machine = find_machine(bundle, machine_id)
    tool = find_tool(bundle, tool_id)
    eoat = find_eoat(bundle, eoat_id)
    checks = (
        _relationship_check(
            "Machine -> Tool",
            bool(machine),
            bool(tool),
            compatible_tools_for_machine(bundle, machine_id),
            tool_id,
            normalize=normalized_tool_key,
            source="Press Capacity / Atlas machine-tool index",
            missing_note="Machine or tool compatibility data is missing.",
        ),
        _relationship_check(
            "Tool -> EOAT",
            bool(tool),
            bool(eoat),
            compatible_eoats_for_tool(bundle, tool_id),
            eoat_id,
            normalize=normalized_eoat_key,
            source="EOAT Inventory / Atlas tool-EOAT index",
            missing_note="Tool or EOAT compatibility data is missing.",
        ),
        _relationship_check(
            "Machine -> EOAT",
            bool(machine),
            bool(eoat),
            compatible_eoats_for_machine(bundle, machine_id),
            eoat_id,
            normalize=normalized_eoat_key,
            source="EOAT Inventory / Atlas machine-EOAT index",
            missing_note="Machine or EOAT compatibility data is missing.",
        ),
    )

    missing_data = []
    if not machine_id:
        missing_data.append("Machine is not selected.")
    elif machine is None:
        missing_data.append(f"Machine {machine_id} is not in the loaded Atlas bundle.")
    if not tool_id:
        missing_data.append("Tool / Mold / Part is not selected.")
    elif tool is None:
        missing_data.append(f"Tool {tool_id} is not in the loaded Atlas bundle.")
    if not eoat_id:
        missing_data.append("EOAT is not selected.")
    elif eoat is None:
        missing_data.append(f"EOAT {eoat_id} is not in the loaded Atlas bundle.")
    missing_data.extend(note for check in checks if check.missing_data for note in check.notes)

    confirmed_links = tuple(check.relationship for check in checks if check.confirmed)
    sources = tuple(dict.fromkeys(check.source for check in checks if check.confirmed and check.source))
    status = _validation_status(checks, missing_data, manual_override_used=manual_override_used)
    warnings = tuple(_validation_warnings(status, checks, missing_data, manual_override_used=manual_override_used))
    return SetupPacketValidationResult(
        status=status,
        checks=checks,
        confirmed_links=confirmed_links,
        missing_data=tuple(dict.fromkeys(missing_data)),
        warnings=warnings,
        sources=sources,
        manual_override_used=bool(manual_override_used),
    )


def build_setup_packet_context(
    bundle: AtlasDataBundle,
    machine_id: str,
    tool_id: str,
    eoat_id: str,
    options: SetupPacketOptions | None = None,
) -> SetupPacketContext:
    normalized_options = (options or SetupPacketOptions()).normalized()
    machine = find_machine(bundle, machine_id)
    tool = find_tool(bundle, tool_id)
    eoat = find_eoat(bundle, eoat_id)
    canonical_machine = machine.machine if machine else str(machine_id or "").strip()
    canonical_tool = tool.tool if tool else str(tool_id or "").strip()
    canonical_eoat = eoat.eoat_id if eoat else str(eoat_id or "").strip()
    validation = validate_setup_context(
        bundle,
        canonical_machine,
        canonical_tool,
        canonical_eoat,
        manual_override_used=normalized_options.manual_override_used,
    )
    photos = tuple(_combined_photos(eoat))
    selected_photos = select_photos_for_packet(eoat, normalized_options)
    robot_info = _robot_info(bundle, machine, canonical_machine)
    warnings = _dedupe_warnings((*validation.warnings, *getattr(machine, "warnings", ()), *getattr(tool, "warnings", ()), *getattr(eoat, "warnings", ())))
    missing_key_data = tuple(_missing_key_data(bundle, validation, machine, tool, eoat, robot_info, photos))
    standards = tuple(dict.fromkeys([*list(getattr(eoat, "standards", ())), *list(bundle.standards[:6])]))
    return SetupPacketContext(
        project_root=bundle.project_root,
        machine_id=canonical_machine,
        tool_id=canonical_tool,
        eoat_id=canonical_eoat,
        machine=machine,
        tool=tool,
        eoat=eoat,
        options=normalized_options,
        validation=validation,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        robot_info=robot_info,
        photos=photos,
        selected_photos=selected_photos,
        standards=standards,
        warnings=warnings,
        missing_key_data=missing_key_data,
        source_files=_source_files(bundle),
        estimated_sections=packet_section_names(normalized_options),
    )


def select_photos_for_packet(eoat: EOATRecord | None, options: SetupPacketOptions) -> tuple[PhotoItem, ...]:
    if eoat is None:
        return ()
    photo_mode = options.normalized().photo_inclusion
    if not options.normalized().include_eoat_photo:
        return ()
    photos = _combined_photos(eoat)
    if photo_mode == PHOTO_NONE:
        return ()
    if photo_mode == PHOTO_ALL:
        return tuple(photos)
    selected: list[PhotoItem] = []
    for keyword_group in _KEY_PHOTO_KEYWORDS:
        match = next((photo for photo in photos if _photo_matches(photo, keyword_group) and photo.path not in {p.path for p in selected}), None)
        if match is not None:
            selected.append(match)
        if len(selected) >= 6:
            break
    if not selected:
        selected.extend(photos[: min(6, len(photos))])
    return tuple(selected)


def packet_section_names(options: SetupPacketOptions) -> tuple[str, ...]:
    packet_type = options.normalized().packet_type
    sections_by_type = {
        PACKET_TYPE_STANDARD: (
            "Cover / Setup Summary",
            "Fit Check Summary",
            "Machine Information",
            "Robot Information",
            "Tool / Part Information",
            "EOAT Information",
            "Pneumatics / Vacuum / Gripper / Sensor Information",
            "Standard Changeover Checklist",
            "Documentation Checklist",
            "Photos / Visual References",
            "Standards / PM References",
            "Warnings / Missing Information",
            "Notes / Source Summary",
        ),
        PACKET_TYPE_SETUP_VERIFICATION: (
            "Cover / Verification Summary",
            "Fit Check Summary",
            "Machine / Tool / EOAT IDs",
            "Robot Information",
            "Key EOAT Setup Details",
            "Verification Checklist",
            "Warnings / Missing Information",
            "Notes / Source Summary",
        ),
        PACKET_TYPE_MAINTENANCE_PM: (
            "Cover / Maintenance Summary",
            "EOAT Information",
            "Machine / Robot Information",
            "Pneumatics / Vacuum / Gripper / Sensor Information",
            "Maintenance / PM Checklist",
            "Photos / Visual References",
            "Standards / PM References",
            "Warnings / Missing Information",
            "Notes / Source Summary",
        ),
        PACKET_TYPE_DOCUMENTATION_REVIEW: (
            "Cover / Documentation Summary",
            "Machine / Tool / EOAT Context",
            "Documentation Score And Missing Fields",
            "Photo Coverage",
            "Standards / PM References",
            "Documentation Checklist",
            "Warnings / Missing Information",
            "Notes / Source Summary",
        ),
    }
    return sections_by_type.get(packet_type, sections_by_type[PACKET_TYPE_STANDARD])


def build_standard_changeover_checklist() -> tuple[str, ...]:
    return (
        "Confirm selected Machine.",
        "Confirm selected Tool / Mold / Part.",
        "Confirm selected EOAT ID.",
        "Verify compatibility status in this packet.",
        "Inspect EOAT for visible damage.",
        "Inspect grippers and/or vacuum cups.",
        "Check tubing routing and strain relief.",
        "Check quick disconnects.",
        "Confirm robot-side pneumatic circuit connections.",
        "Confirm external peripheral IO-controlled air circuit connections if applicable.",
        "Confirm EOAT-side pneumatic circuit connections.",
        "Confirm sensor / part-present / vacuum detection if applicable.",
        "Mount EOAT using approved method.",
        "Verify EOAT alignment.",
        "Run/observe first cycle according to normal plant procedure.",
        "Check for part drops, mis-picks, tubing interference, or sensor faults.",
        "Record any missing documentation or issues in Command Center.",
    )


def build_documentation_checklist() -> tuple[str, ...]:
    return (
        "Confirm EOAT profile exists.",
        "Confirm Machine/Robot info exists.",
        "Confirm Tool compatibility exists.",
        "Confirm required photo categories exist.",
        "Capture missing photos if needed.",
        "Confirm standards/PM references are linked.",
        "Confirm notes/warnings are current.",
        "Record missing or incorrect information in Command Center.",
        "Do not edit source workbooks directly from Atlas.",
    )


def build_verification_checklist() -> tuple[str, ...]:
    return (
        "Confirm tool/mold number.",
        "Confirm machine number.",
        "Confirm EOAT ID.",
        "Inspect vacuum cups or grippers for wear/damage.",
        "Inspect pneumatic tubing.",
        "Verify sensor operation.",
        "Inspect mounting hardware.",
        "Verify EOAT alignment.",
        "Check quick disconnect fittings.",
        "Verify cable management condition.",
        "Dry-cycle robot before production.",
        "Confirm first-shot/first-part handling.",
    )


def build_pm_checklist() -> tuple[str, ...]:
    return (
        "Inspect frame, mounts, fasteners, and alignment features.",
        "Inspect grippers and/or vacuum cups for wear or damage.",
        "Inspect tubing routing, clamps, and strain relief.",
        "Check quick disconnects and electrical connectors.",
        "Confirm sensors and part-present or vacuum detection.",
        "Review known issues and open warnings.",
        "Record maintenance findings in Command Center.",
    )


def find_eoat(bundle: AtlasDataBundle, eoat_id: str) -> EOATRecord | None:
    key = normalized_eoat_key(eoat_id)
    canonical = bundle.indexes.eoat_by_id.get(key, eoat_id)
    canonical_key = normalized_eoat_key(canonical)
    return next((record for record in bundle.eoats if normalized_eoat_key(record.eoat_id) == canonical_key), None)


def find_machine(bundle: AtlasDataBundle, machine_id: str) -> MachineRecord | None:
    key = normalized_machine_key(machine_id)
    return next((record for record in bundle.machines if normalized_machine_key(record.machine) == key), None)


def find_tool(bundle: AtlasDataBundle, tool_id: str) -> ToolRecord | None:
    key = normalized_tool_key(tool_id)
    return next((record for record in bundle.tools if normalized_tool_key(record.tool) == key), None)


def _relationship_check(
    relationship: str,
    source_record_exists: bool,
    target_record_exists: bool,
    compatible_values: tuple[str, ...],
    target_value: str,
    *,
    normalize,
    source: str,
    missing_note: str,
) -> RelationshipCheck:
    if not source_record_exists or not target_record_exists:
        return RelationshipCheck(relationship, COMPATIBILITY_MISSING_DATA, notes=(missing_note,))
    if not compatible_values:
        return RelationshipCheck(relationship, COMPATIBILITY_MISSING_DATA, notes=(f"{relationship}: no compatibility values are indexed.",))
    target_key = normalize(target_value)
    if any(normalize(value) == target_key for value in compatible_values):
        return RelationshipCheck(relationship, COMPATIBILITY_CONFIRMED, source=source)
    return RelationshipCheck(
        relationship,
        COMPATIBILITY_NOT_CONFIRMED,
        source=source,
        notes=(f"{relationship}: selected value is not in the compatible list.",),
    )


def _validation_status(
    checks: tuple[RelationshipCheck, ...],
    missing_data: list[str],
    *,
    manual_override_used: bool,
) -> str:
    if manual_override_used:
        return COMPATIBILITY_MANUAL_OVERRIDE
    confirmed_count = sum(check.confirmed for check in checks)
    not_confirmed_count = sum(check.status == COMPATIBILITY_NOT_CONFIRMED for check in checks)
    missing_count = len(missing_data)
    if confirmed_count == len(checks):
        return COMPATIBILITY_CONFIRMED
    if confirmed_count > 0:
        return COMPATIBILITY_PARTIAL
    if missing_count and not not_confirmed_count:
        return COMPATIBILITY_MISSING_DATA
    return COMPATIBILITY_NOT_CONFIRMED


def _validation_warnings(
    status: str,
    checks: tuple[RelationshipCheck, ...],
    missing_data: list[str],
    *,
    manual_override_used: bool,
) -> list[WarningItem]:
    warnings: list[WarningItem] = []
    if manual_override_used:
        warnings.append(
            WarningItem(
                severity="warning",
                title="Manual override used",
                message=(
                    "This combination is not confirmed by Atlas compatibility data. Generate this packet only if "
                    "you have verified the setup through another approved source."
                ),
                source="Setup Packet Generator",
                why_it_matters="The packet may be used on the plant floor, so unconfirmed compatibility must be visible.",
                suggested_fix="Verify the setup through an approved source and record the missing compatibility in Command Center.",
            )
        )
    if status == COMPATIBILITY_NOT_CONFIRMED:
        warnings.append(
            WarningItem(
                severity="warning",
                title="Fit Check not confirmed",
                message="Atlas does not find the selected Machine + Tool + EOAT combination in compatibility data.",
                source="Setup Packet Generator",
                why_it_matters="Unconfirmed setups can cause changeover errors, robot connection issues, or part handling failures.",
                suggested_fix="Select a compatible item or use manual override only after external verification.",
            )
        )
    for check in checks:
        if check.status == COMPATIBILITY_NOT_CONFIRMED:
            warnings.append(
                WarningItem(
                    severity="warning",
                    title=f"{check.relationship} not confirmed",
                    message=" ".join(check.notes),
                    source=check.source or "Atlas compatibility data",
                    suggested_fix="Review Press Capacity, EOAT Inventory, and Command Center compatibility records.",
                )
            )
    for item in missing_data:
        warnings.append(
            WarningItem(
                severity="info",
                title="Missing compatibility data",
                message=item,
                source="Setup Packet Generator",
                suggested_fix="Record or repair missing compatibility fields in Command Center/source workflow.",
            )
        )
    return warnings


def _missing_key_data(
    bundle: AtlasDataBundle,
    validation: SetupPacketValidationResult,
    machine: MachineRecord | None,
    tool: ToolRecord | None,
    eoat: EOATRecord | None,
    robot_info: dict[str, Any],
    photos: tuple[PhotoItem, ...],
) -> list[str]:
    missing = list(validation.missing_data)
    if machine is not None and not robot_info and not (machine.robot_type or machine.robot_model):
        missing.append(f"Robot info is missing for Machine {machine.machine}.")
    if tool is not None and not tool.compatible_eoats:
        missing.append(f"Tool {tool.tool} has no compatible EOAT links.")
    if tool is not None and not tool.compatible_machines:
        missing.append(f"Tool {tool.tool} has no compatible machine links.")
    if eoat is not None:
        if not eoat.tools:
            missing.append(f"EOAT {eoat.eoat_id} has no linked tools.")
        if not eoat.machines:
            missing.append(f"EOAT {eoat.eoat_id} has no linked machines.")
        for field_name in eoat.documentation.critical_missing_fields:
            missing.append(f"Critical EOAT field missing: {field_name}.")
        if not photos:
            missing.append(f"No photos are linked for EOAT {eoat.eoat_id}.")
        for category in eoat.photos.missing_categories:
            missing.append(f"Missing photo category: {category}.")
    for status in bundle.source_statuses:
        if not status.available:
            missing.append(f"Source unavailable: {status.label} ({status.path}).")
    return list(dict.fromkeys(item for item in missing if item))


def _robot_info(bundle: AtlasDataBundle, machine: MachineRecord | None, machine_id: str) -> dict[str, Any]:
    key = normalized_machine_key(machine.machine if machine else machine_id)
    info = dict(bundle.indexes.robot_info_by_machine.get(key, {}))
    if machine is not None:
        info.setdefault("Machine Number", machine.machine)
        info.setdefault("Robot Type", machine.robot_type)
        info.setdefault("Robot Identifier", machine.robot_model)
        info.setdefault("Controller Type", machine.controller)
    return {key: display_value(value) for key, value in info.items() if display_value(value)}


def _source_files(bundle: AtlasDataBundle) -> tuple[tuple[str, str, str], ...]:
    rows = []
    for status in bundle.source_statuses:
        rows.append((status.label, status.path, "Available" if status.available else "Missing"))
    return tuple(rows)


def _combined_photos(eoat: EOATRecord | None) -> list[PhotoItem]:
    if eoat is None:
        return []
    photos: list[PhotoItem] = []
    seen: set[str] = set()
    for photo in (*eoat.photos.photos, *eoat.photos.indexed_photos):
        key = str(photo.path or photo.filename).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        photos.append(photo)
    return photos


_KEY_PHOTO_KEYWORDS = (
    ("overall", "front", "full"),
    ("mount", "mounting", "connection", "adapter", "plate"),
    ("tube", "tubing", "routing", "hose"),
    ("gripper", "vacuum", "cup", "cups"),
    ("sensor", "part-present", "presence", "switch"),
    ("disconnect", "quick", "m12", "pneumatic", "electrical"),
)


def _photo_matches(photo: PhotoItem, keywords: tuple[str, ...]) -> bool:
    text = " ".join([photo.filename, photo.category, photo.path]).casefold()
    return any(keyword in text for keyword in keywords)


def _dedupe_warnings(warnings: tuple[WarningItem, ...]) -> tuple[WarningItem, ...]:
    deduped: list[WarningItem] = []
    seen: set[tuple[str, str, str]] = set()
    for warning in warnings:
        key = (warning.severity.casefold(), warning.title.casefold(), warning.message.casefold())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(warning)
    return tuple(deduped)


def _intersection(*groups: tuple[str, ...]) -> tuple[str, ...]:
    populated = [tuple(group) for group in groups]
    if not populated or any(not group for group in populated):
        return ()
    allowed = {value.casefold(): value for value in populated[0]}
    for group in populated[1:]:
        group_keys = {value.casefold() for value in group}
        allowed = {key: value for key, value in allowed.items() if key in group_keys}
    return tuple(allowed.values())


def _choice(value: str, choices: tuple[str, ...], default: str) -> str:
    text = str(value or "").strip().casefold().replace(" ", "_").replace("-", "_").replace("/", "_")
    aliases = {
        "standard": PACKET_TYPE_STANDARD,
        "standard_changeover_packet": PACKET_TYPE_STANDARD,
        "changeover": PACKET_TYPE_STANDARD,
        "setup_verification_packet": PACKET_TYPE_SETUP_VERIFICATION,
        "maintenance": PACKET_TYPE_MAINTENANCE_PM,
        "maintenance_pm_packet": PACKET_TYPE_MAINTENANCE_PM,
        "pm": PACKET_TYPE_MAINTENANCE_PM,
        "documentation": PACKET_TYPE_DOCUMENTATION_REVIEW,
        "documentation_review_packet": PACKET_TYPE_DOCUMENTATION_REVIEW,
        "no_photos": PHOTO_NONE,
        "none": PHOTO_NONE,
        "key_photos_only": PHOTO_KEY,
        "key": PHOTO_KEY,
        "all_photos": PHOTO_ALL,
        "all": PHOTO_ALL,
        "external": "external_pdf",
        "external_viewer": "external_pdf",
        "folder": "open_folder",
        "ask": "ask_each_time",
        "detailed": "detailed",
    }
    text = aliases.get(text, text)
    return text if text in choices else default


def _sort_machines(values) -> tuple[str, ...]:
    normalized = {normalized_machine_key(value): display_value(value) for value in values if normalized_machine_key(value)}
    return tuple(normalized[key] for key in sorted(normalized, key=_machine_sort_key))


def _sort_tools(values) -> tuple[str, ...]:
    normalized = {normalized_tool_key(value): display_value(value) for value in values if normalized_tool_key(value)}
    return tuple(normalized[key] for key in sorted(normalized))


def _sort_eoats(values) -> tuple[str, ...]:
    normalized = {normalized_eoat_key(value): display_value(value) for value in values if normalized_eoat_key(value)}
    return tuple(normalized[key] for key in sorted(normalized))


def _machine_sort_key(value: str) -> tuple[int, int | str]:
    return (0, int(value)) if str(value).isdigit() else (1, str(value).casefold())


def row_first(record: Any, *fields: str) -> str:
    for row in getattr(record, "source_rows", ()) or ():
        value = row_value(row, fields)
        if value:
            return value
    return ""


__all__ = [
    "COMPATIBILITY_CONFIRMED",
    "COMPATIBILITY_MANUAL_OVERRIDE",
    "COMPATIBILITY_MISSING_DATA",
    "COMPATIBILITY_NOT_CONFIRMED",
    "COMPATIBILITY_PARTIAL",
    "DETAIL_LEVEL_CHOICES",
    "OPEN_PACKET_CHOICES",
    "PACKET_TYPE_CHOICES",
    "PACKET_TYPE_DOCUMENTATION_REVIEW",
    "PACKET_TYPE_LABELS",
    "PACKET_TYPE_MAINTENANCE_PM",
    "PACKET_TYPE_SETUP_VERIFICATION",
    "PACKET_TYPE_STANDARD",
    "PHOTO_ALL",
    "PHOTO_INCLUSION_CHOICES",
    "PHOTO_INCLUSION_LABELS",
    "PHOTO_KEY",
    "PHOTO_NONE",
    "STARTING_ITEM_CHOICES",
    "SetupPacketContext",
    "SetupPacketExportResult",
    "SetupPacketOptions",
    "SetupPacketSection",
    "SetupPacketValidationResult",
    "atlas_setup_packet_dir",
    "build_documentation_checklist",
    "build_pm_checklist",
    "build_setup_packet_context",
    "build_standard_changeover_checklist",
    "build_verification_checklist",
    "compatible_eoats_for_machine",
    "compatible_eoats_for_tool",
    "compatible_machines_for_eoat",
    "compatible_machines_for_tool",
    "compatible_tools_for_eoat",
    "compatible_tools_for_machine",
    "find_eoat",
    "find_machine",
    "find_tool",
    "packet_section_names",
    "row_first",
    "select_photos_for_packet",
    "selectable_eoats",
    "selectable_machines",
    "selectable_tools",
    "validate_setup_context",
]
