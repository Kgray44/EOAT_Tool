from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

from .atlas_models import (
    AtlasDataBundle,
    AtlasIndexes,
    AtlasSourceStatus,
    EOATRecord,
    MachineRecord,
    PhotoSet,
    StandardReference,
    ToolRecord,
    WarningItem,
)
from .atlas_performance import AtlasDiagnostics, timed_step
from .atlas_utils import (
    display_value,
    first_present,
    machine_tokens,
    normalized_eoat_key,
    normalized_machine_key,
    normalized_tool_key,
    row_value,
    sorted_unique,
    split_multi_value,
)
from .audit_compatibility import (
    load_required_relationships,
    machine_from_audit_row,
    normalize_machine_token,
    part_description_from_row,
    part_number_from_row,
)
from .documentation_score import calculate_documentation_status
from .eoat_ids import is_valid_eoat_assembly_id, normalize_eoat_assembly_id
from .paths import get_press_capacity_file, resolve_project_paths
from .performance import log_perf_marker, perf_timer
from .photo_index import build_photo_index
from .standards_index import STANDARD_EXTENSIONS, STANDARDIZATION_KEYWORDS, build_standards_index, standards_for_record
from .tool_fields import TOOL_FIELD
from .workbook_cache import row_dicts_cached, workbook_file_signature


@dataclass(frozen=True)
class CurrentEoatResolution:
    eoat_id: str = ""
    status: str = "unknown"
    source: str = ""
    confidence: str = "unknown"
    reason: str = "not indexed"
    source_row_index: int = -1
    matching_rows_count: int = 0
    eoat_ids_found: tuple[str, ...] = ()
    ambiguous: bool = False


_CACHE_LOCK = RLock()
_CACHE: dict[str, tuple[tuple[tuple[str, bool, int, int], ...], AtlasDataBundle]] = {}


def load_atlas_data(
    project_root: str | Path,
    *,
    force_refresh: bool = False,
    exclude_unaudited_tools: bool = True,
    source_paths: dict[str, str] | None = None,
) -> AtlasDataBundle:
    from .globalization.workbook_import import load_atlas_data_from_sqlite_cache, should_use_sqlite_cache

    if should_use_sqlite_cache(source_paths):
        return load_atlas_data_from_sqlite_cache(
            project_root,
            force_refresh=force_refresh,
            exclude_unaudited_tools=exclude_unaudited_tools,
            source_paths=source_paths,
            legacy_loader=_load_atlas_data_uncached,
        )
    root = Path(project_root)
    with perf_timer(
        root,
        "atlas.load.cache_signature",
        details={"ui_sensitive": "cached_data_load", "force_refresh": bool(force_refresh)},
        source="atlas_data_loader",
        page_tool="atlas_backend",
    ):
        signature = _cache_signature(root, source_paths=source_paths)
    cache_key = _cache_key(root, exclude_unaudited_tools=exclude_unaudited_tools, source_paths=source_paths)
    if not force_refresh:
        with (
            perf_timer(
                root,
                "atlas.load.memory_cache_lookup",
                details={"ui_sensitive": "cached_data_load", "cache_key": cache_key},
                source="atlas_data_loader",
                page_tool="atlas_backend",
            ),
            _CACHE_LOCK,
        ):
            cached = _CACHE.get(cache_key)
            if cached and cached[0] == signature:
                log_perf_marker(
                    root,
                    "atlas.load.memory_cache_hit",
                    details={
                        "ui_sensitive": "cached_data_load",
                        "eoats": len(cached[1].eoats),
                        "tools": len(cached[1].tools),
                        "machines": len(cached[1].machines),
                    },
                    source="atlas_data_loader",
                    page_tool="atlas_backend",
                )
                return cached[1]
        log_perf_marker(
            root,
            "atlas.load.memory_cache_miss",
            details={"ui_sensitive": "cached_data_load", "force_refresh": bool(force_refresh)},
            source="atlas_data_loader",
            page_tool="atlas_backend",
        )

    with perf_timer(
        root,
        "atlas.load.uncached",
        details={"ui_sensitive": "cached_data_load", "force_refresh": bool(force_refresh)},
        source="atlas_data_loader",
        page_tool="atlas_backend",
    ):
        bundle = _load_atlas_data_uncached(
            root, exclude_unaudited_tools=exclude_unaudited_tools, source_paths=source_paths
        )
    with _CACHE_LOCK:
        _CACHE[cache_key] = (signature, bundle)
    return bundle


def invalidate_atlas_data_cache(project_root: str | Path | None = None) -> None:
    with _CACHE_LOCK:
        if project_root is None:
            _CACHE.clear()
            return
        key = _cache_key_root(Path(project_root))
        for cache_key in tuple(_CACHE):
            if cache_key.startswith(key):
                _CACHE.pop(cache_key, None)


def _load_atlas_data_uncached(
    project_root: Path,
    *,
    exclude_unaudited_tools: bool,
    source_paths: dict[str, str] | None = None,
) -> AtlasDataBundle:
    diagnostics = AtlasDiagnostics()
    paths = _source_path_overrides(project_root, source_paths)
    source_statuses = _source_statuses(project_root, source_paths=source_paths)
    warnings: list[WarningItem] = []
    excluded_unaudited_tool_count = 0

    with (
        timed_step(diagnostics, "workbook_load"),
        perf_timer(
            project_root,
            "atlas.workbook_load",
            details={"ui_sensitive": "excel_read", "workbooks": "master tracker, photo index, robot info"},
            source="atlas_data_loader",
            page_tool="atlas_backend",
        ),
    ):
        inventory_rows, inventory_warnings = _safe_rows(
            paths["eoat_master_tracker"], "EOAT Inventory", "EOAT Master Tracker"
        )
        photo_rows, photo_warnings = _safe_rows(paths["eoat_master_tracker"], "Photo Index", "EOAT Photo Index")
        robot_rows, robot_warnings = _safe_rows(paths["robot_workbook"], "Robot Info", "Robot Info", optional=True)
    warnings.extend(inventory_warnings)
    warnings.extend(photo_warnings)
    warnings.extend(robot_warnings)

    with (
        timed_step(diagnostics, "press_capacity_load"),
        perf_timer(
            project_root,
            "atlas.press_capacity_load",
            details={"ui_sensitive": "excel_read", "exclude_unaudited_tools": bool(exclude_unaudited_tools)},
            source="atlas_data_loader",
            page_tool="atlas_backend",
        ),
    ):
        press_relationships, press_warnings = load_required_relationships(paths["press_capacity_workbook"])
        if exclude_unaudited_tools:
            audited_tool_keys = _audited_tool_keys(inventory_rows)
            before_count = len(press_relationships)
            press_relationships = [
                relationship
                for relationship in press_relationships
                if normalized_tool_key(relationship.part_number) in audited_tool_keys
            ]
            excluded_unaudited_tool_count = before_count - len(press_relationships)
    warnings.extend(
        _warning("warning", "Press Capacity", warning, source="Press Capacity") for warning in press_warnings
    )

    with (
        timed_step(diagnostics, "standards_index"),
        perf_timer(
            project_root,
            "atlas.standards_index",
            details={"ui_sensitive": "folder_scan"},
            source="atlas_data_loader",
            page_tool="atlas_backend",
        ),
    ):
        standards, standards_warnings = build_standards_index(
            project_root, standards_root=paths["reference_docs_folder"]
        )
    warnings.extend(_warning("info", "Standards", warning, source="Standards") for warning in standards_warnings)

    with (
        timed_step(diagnostics, "photo_index"),
        perf_timer(
            project_root,
            "atlas.photo_index",
            details={"ui_sensitive": "photo_index_scan"},
            source="atlas_data_loader",
            page_tool="atlas_backend",
        ),
    ):
        photo_sets, photos_by_tool, photo_warnings = build_photo_index(
            project_root,
            inventory_rows,
            photo_rows,
            photos_root=paths["photos_root"],
        )
    warnings.extend(_warning("warning", "Photos", warning, source="Photos") for warning in photo_warnings)

    robot_by_machine = _robot_rows_by_machine(robot_rows)
    with (
        timed_step(diagnostics, "cache_build"),
        perf_timer(
            project_root,
            "atlas.cache_build",
            details={"ui_sensitive": "cached_data_load"},
            source="atlas_data_loader",
            page_tool="atlas_backend",
        ),
    ):
        eoats = _build_eoat_records(inventory_rows, press_relationships, photo_sets, standards, warnings)
        machines = _build_machine_records(inventory_rows, press_relationships, eoats, robot_by_machine)
        tools = _build_tool_records(inventory_rows, press_relationships, eoats)
        indexes = _build_indexes(eoats, machines, tools, photos_by_tool, robot_by_machine)
        bundle_warnings = _bundle_warnings(eoats, machines, tools, indexes)
        warnings.extend(bundle_warnings)

    diagnostics.counters.update(
        {
            "atlas_eoats": len(eoats),
            "atlas_machines": len(machines),
            "atlas_tools": len(tools),
            "atlas_warnings": len(warnings),
            "atlas_standards": len(standards),
        }
    )
    metrics = {
        **diagnostics.to_metrics(),
        "eoats_documented": len(eoats),
        "machines_covered": len(machines),
        "tools_covered": len(tools),
        "photos_linked": sum(record.photo_count for record in eoats),
        "documentation_average": _average(record.documentation.score for record in eoats),
        "open_warnings": len(warnings) + sum(record.warning_count for record in eoats),
        "exclude_unaudited_tools": exclude_unaudited_tools,
        "unaudited_press_capacity_relationships_excluded": excluded_unaudited_tool_count,
        "last_refreshed": datetime.now().isoformat(timespec="seconds"),
    }
    return AtlasDataBundle(
        project_root=str(project_root),
        loaded_at=metrics["last_refreshed"],
        source_statuses=tuple(source_statuses),
        eoats=tuple(eoats),
        machines=tuple(machines),
        tools=tuple(tools),
        press_capacity_rows=tuple(_press_capacity_rows(press_relationships)),
        standards=tuple(standards),
        warnings=tuple(warnings),
        indexes=indexes,
        metrics=metrics,
    )


def _cache_key_root(root: Path) -> str:
    return str(root.resolve(strict=False)).casefold()


def _cache_key(root: Path, *, exclude_unaudited_tools: bool, source_paths: dict[str, str] | None = None) -> str:
    override_key = "|".join(
        f"{key}={Path(value).expanduser().resolve(strict=False)}"
        for key, value in sorted((source_paths or {}).items())
        if str(value or "").strip()
    )
    return (
        f"{_cache_key_root(root)}::exclude_unaudited_tools={int(bool(exclude_unaudited_tools))}::sources={override_key}"
    )


def _audited_tool_keys(inventory_rows: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for row in inventory_rows:
        for tool in _tools_for_rows([row]):
            key = normalized_tool_key(tool)
            if key:
                keys.add(key)
    return keys


def _press_capacity_rows(press_relationships) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relationship in press_relationships:
        row = dict(getattr(relationship, "machine_data", {}) or {})
        row.setdefault("Machine No.", display_value(getattr(relationship, "machine_no", "")))
        row.setdefault(TOOL_FIELD, display_value(getattr(relationship, "part_number", "")))
        row.setdefault("NGW Part Number", display_value(getattr(relationship, "part_number", "")))
        if display_value(getattr(relationship, "part_description", "")):
            row.setdefault("NGW Part Description", display_value(getattr(relationship, "part_description", "")))
        row["Source"] = "Press Capacity"
        if getattr(relationship, "source_row", 0):
            row["Source Row"] = getattr(relationship, "source_row", 0)
        rows.append(row)
    return rows


def _build_eoat_records(
    inventory_rows: list[dict[str, Any]],
    press_relationships,
    photo_sets: dict[str, PhotoSet],
    standards: list[StandardReference],
    global_warnings: list[WarningItem],
) -> list[EOATRecord]:
    rows_by_eoat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(inventory_rows, start=2):
        group_id = _eoat_group_id(row, index)
        rows_by_eoat[group_id].append(row)

    machines_by_tool_from_capacity: dict[str, set[str]] = defaultdict(set)
    for relationship in press_relationships:
        machines_by_tool_from_capacity[normalized_tool_key(relationship.part_number)].add(relationship.machine_no)

    records: list[EOATRecord] = []
    duplicate_eoat_ids = [
        eoat_id
        for eoat_id, count in Counter(
            normalize_eoat_assembly_id(row.get("EOAT Assembly ID"))
            for row in inventory_rows
            if normalize_eoat_assembly_id(row.get("EOAT Assembly ID"))
        ).items()
        if count > 1
    ]
    for eoat_id in duplicate_eoat_ids:
        global_warnings.append(
            _warning(
                "info",
                "EOAT has multiple rows",
                f"{eoat_id} appears on multiple inventory rows. Atlas merged them into one profile.",
                source="EOAT Inventory",
                related_eoat_id=eoat_id,
            )
        )

    for group_id, rows in rows_by_eoat.items():
        primary = _best_primary_row(rows)
        display_id = _display_eoat_id(primary, group_id)
        eoat_key = normalized_eoat_key(display_id)
        tools = _tools_for_rows(rows)
        machines = set(_machines_for_rows(rows))
        for tool in tools:
            machines.update(machines_by_tool_from_capacity.get(normalized_tool_key(tool), set()))
        photo_set = photo_sets.get(eoat_key, PhotoSet(eoat_id=display_id))
        documentation = calculate_documentation_status(primary, photo_count=photo_set.total_count)
        record_warnings = _warnings_for_eoat(primary, display_id, tools, machines, photo_set, documentation)
        records.append(
            EOATRecord(
                eoat_id=display_id,
                display_id=display_id,
                audit_ids=tuple(_row_values(rows, "Audit ID")),
                tools=tuple(tools),
                molds=tuple(_row_values(rows, "Mold #", "Mold Number")),
                parts=tuple(_parts_for_rows(rows)),
                machines=tuple(_sort_machine_values(machines)),
                part_family=first_present(primary, "Part Family"),
                part_description=part_description_from_row(primary),
                eoat_type=first_present(primary, "EOAT Type"),
                status=first_present(primary, "Status"),
                robot_types=tuple(_row_values(rows, "Robot Type")),
                robot_models=tuple(_row_values(rows, "Robot Model/Controller", "Robot Model")),
                connection_type=_connection_summary(primary),
                vacuum_info=_vacuum_summary(primary),
                pressure_info=_pressure_summary(primary),
                gripper_info=_gripper_summary(primary),
                sensor_info=_sensor_summary(primary),
                tubing_notes=first_present(primary, "Tubing Routing Notes", "Tubing Notes"),
                install_notes=_install_notes(primary),
                known_issues=first_present(primary, "Known Issues", "Drop/Mis-Pick History", "Notes"),
                documentation=documentation,
                photos=photo_set,
                warnings=tuple(record_warnings),
                standards=standards_for_record(primary, standards),
                source_rows=tuple(rows),
            )
        )
    return sorted(records, key=lambda record: record.display_id.casefold())


def _build_machine_records(inventory_rows: list[dict[str, Any]], press_relationships, eoats, robot_by_machine):
    rows_by_machine: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tools_by_machine_from_capacity: dict[str, set[str]] = defaultdict(set)
    parts_by_machine_from_capacity: dict[str, set[str]] = defaultdict(set)
    for relationship in press_relationships:
        machine = normalize_machine_token(relationship.machine_no)
        if not machine:
            continue
        tools_by_machine_from_capacity[machine].add(display_value(relationship.part_number))
        if relationship.part_description:
            parts_by_machine_from_capacity[machine].add(display_value(relationship.part_description))
    for row in inventory_rows:
        for machine in machine_tokens(row.get("Press/Machine #")) or tuple([machine_from_audit_row(row)]):
            if machine:
                rows_by_machine[normalize_machine_token(machine)].append(row)
    machines = set(rows_by_machine) | set(tools_by_machine_from_capacity) | set(robot_by_machine)
    eoats_by_machine: dict[str, set[str]] = defaultdict(set)
    for record in eoats:
        for machine in record.machines:
            eoats_by_machine[normalize_machine_token(machine)].add(record.eoat_id)
    records: list[MachineRecord] = []
    for machine in sorted(machines, key=_machine_sort_key):
        rows = rows_by_machine.get(machine, [])
        robot = robot_by_machine.get(machine, {})
        first_row = rows[0] if rows else {}
        tools = set(tools_by_machine_from_capacity.get(machine, set()))
        parts = set(parts_by_machine_from_capacity.get(machine, set()))
        for row in rows:
            tools.update(_tools_for_rows([row]))
            parts.update(_parts_for_rows([row]))
        doc_scores = [
            calculate_documentation_status(row).score
            for row in rows
            if any(display_value(value) for value in row.values())
        ]
        warnings = _warnings_for_machine(machine, rows, robot, eoats_by_machine.get(machine, set()))
        current_resolution = _current_eoat_resolution_for_rows(rows)
        if current_resolution.ambiguous:
            warnings.append(
                _warning(
                    "info",
                    "Ambiguous current EOAT",
                    f"Multiple EOAT IDs were found for Machine {machine}: {', '.join(current_resolution.eoat_ids_found)}. Atlas selected {current_resolution.eoat_id or 'none'} from {current_resolution.reason}.",
                    source="EOAT Inventory",
                    machine=machine,
                )
            )
        records.append(
            MachineRecord(
                machine=machine,
                label=f"Machine {machine}",
                robot_type=display_value(robot.get("Robot Type")) or first_present(first_row, "Robot Type"),
                robot_model=display_value(robot.get("Robot Identifier"))
                or display_value(robot.get("Robot Model/Controller"))
                or first_present(first_row, "Robot Model/Controller"),
                controller=display_value(robot.get("Controller Type")),
                compatible_eoats=tuple(sorted(eoats_by_machine.get(machine, set()), key=str.casefold)),
                compatible_tools=tuple(sorted(tools, key=str.casefold)),
                compatible_parts=tuple(sorted(parts, key=str.casefold)),
                current_eoat=current_resolution.eoat_id,
                current_eoat_status=current_resolution.status,
                current_eoat_source=current_resolution.source,
                current_eoat_confidence=current_resolution.confidence,
                current_eoat_resolution_reason=current_resolution.reason,
                documentation_score=_average(doc_scores),
                warnings=tuple(warnings),
                source_rows=tuple(rows),
            )
        )
    return records


def _build_tool_records(inventory_rows: list[dict[str, Any]], press_relationships, eoats) -> list[ToolRecord]:
    rows_by_tool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    capacity_by_tool: dict[str, list[Any]] = defaultdict(list)
    eoats_by_tool: dict[str, set[str]] = defaultdict(set)
    machines_by_tool: dict[str, set[str]] = defaultdict(set)
    for row in inventory_rows:
        for tool in _tools_for_rows([row]):
            rows_by_tool[normalized_tool_key(tool)].append(row)
    for relationship in press_relationships:
        key = normalized_tool_key(relationship.part_number)
        capacity_by_tool[key].append(relationship)
        machines_by_tool[key].add(relationship.machine_no)
    for record in eoats:
        for tool in record.tools:
            key = normalized_tool_key(tool)
            eoats_by_tool[key].add(record.eoat_id)
            machines_by_tool[key].update(record.machines)
    records: list[ToolRecord] = []
    for key in sorted(set(rows_by_tool) | set(capacity_by_tool)):
        rows = rows_by_tool.get(key, [])
        capacity = capacity_by_tool.get(key, [])
        tool = display_value(rows[0].get(TOOL_FIELD)) if rows else display_value(capacity[0].part_number)
        parts = set(_parts_for_rows(rows))
        parts.update(display_value(item.part_description) for item in capacity if display_value(item.part_description))
        machines = set(machines_by_tool.get(key, set()))
        warnings = []
        if not eoats_by_tool.get(key):
            warnings.append(
                _warning(
                    "warning",
                    "No EOAT found for tool",
                    f"Tool {tool} appears in source data, but no EOAT record is linked.",
                    source="Atlas",
                    tool=tool,
                    suggested_fix="Link an EOAT Assembly ID to the tool in the master tracker.",
                )
            )
        records.append(
            ToolRecord(
                tool=tool,
                label=f"Tool {tool}",
                molds=tuple(_row_values(rows, "Mold #", "Mold Number")),
                parts=tuple(sorted(parts, key=str.casefold)),
                part_family=first_present(rows[0], "Part Family") if rows else "",
                part_description=part_description_from_row(rows[0])
                if rows
                else (capacity[0].part_description if capacity else ""),
                compatible_eoats=tuple(sorted(eoats_by_tool.get(key, set()), key=str.casefold)),
                compatible_machines=tuple(_sort_machine_values(machines)),
                source="EOAT Master Tracker + Press Capacity"
                if rows and capacity
                else ("EOAT Master Tracker" if rows else "Press Capacity"),
                warnings=tuple(warnings),
                source_rows=tuple(rows),
            )
        )
    return records


def _build_indexes(eoats, machines, tools, photos_by_tool, robot_by_machine) -> AtlasIndexes:
    eoat_by_id = {normalized_eoat_key(record.eoat_id): record.eoat_id for record in eoats}
    eoats_by_tool: dict[str, list[str]] = defaultdict(list)
    eoats_by_machine: dict[str, list[str]] = defaultdict(list)
    machines_by_eoat: dict[str, tuple[str, ...]] = {}
    warnings_by_eoat: dict[str, tuple[WarningItem, ...]] = {}
    documentation_status_by_eoat = {}
    photos_by_eoat = {}
    for record in eoats:
        eoat_key = normalized_eoat_key(record.eoat_id)
        machines_by_eoat[eoat_key] = record.machines
        warnings_by_eoat[eoat_key] = record.warnings
        documentation_status_by_eoat[eoat_key] = record.documentation
        photos_by_eoat[eoat_key] = tuple(photo.path for photo in (*record.photos.photos, *record.photos.indexed_photos))
        for tool in record.tools:
            eoats_by_tool[normalized_tool_key(tool)].append(record.eoat_id)
        for machine in record.machines:
            eoats_by_machine[normalized_machine_key(machine)].append(record.eoat_id)
    machines_by_tool = {normalized_tool_key(record.tool): record.compatible_machines for record in tools}
    tools_by_machine: dict[str, list[str]] = defaultdict(list)
    for record in tools:
        for machine in record.compatible_machines:
            tools_by_machine[normalized_machine_key(machine)].append(record.tool)
    warnings_by_machine = {normalized_machine_key(record.machine): record.warnings for record in machines}
    return AtlasIndexes(
        eoat_by_id=eoat_by_id,
        eoats_by_tool={key: tuple(sorted(set(values), key=str.casefold)) for key, values in eoats_by_tool.items()},
        eoats_by_machine={
            key: tuple(sorted(set(values), key=str.casefold)) for key, values in eoats_by_machine.items()
        },
        machines_by_tool=machines_by_tool,
        machines_by_eoat=machines_by_eoat,
        tools_by_machine={
            key: tuple(sorted(set(values), key=str.casefold)) for key, values in tools_by_machine.items()
        },
        photos_by_eoat=photos_by_eoat,
        photos_by_tool={key: tuple(photo.path for photo in photos) for key, photos in photos_by_tool.items()},
        robot_info_by_machine={normalized_machine_key(key): value for key, value in robot_by_machine.items()},
        warnings_by_eoat=warnings_by_eoat,
        warnings_by_machine=warnings_by_machine,
        documentation_status_by_eoat=documentation_status_by_eoat,
    )


def _source_path_overrides(project_root: Path, source_paths: dict[str, str] | None = None) -> dict[str, Path]:
    paths = resolve_project_paths(project_root)
    resolved = {
        "eoat_master_tracker": paths.master_workbook,
        "press_capacity_workbook": get_press_capacity_file(project_root),
        "robot_workbook": paths.robot_info_workbook,
        "photos_root": paths.cell_photos,
        "output_folder": paths.final_handoff / "Atlas_Exports",
        "reference_docs_folder": paths.standards,
    }
    for key, value in (source_paths or {}).items():
        text = str(value or "").strip()
        if key in resolved and text:
            resolved[key] = Path(text).expanduser()
    return resolved


def _source_statuses(project_root: Path, *, source_paths: dict[str, str] | None = None) -> list[AtlasSourceStatus]:
    paths = _source_path_overrides(project_root, source_paths)
    sources = [
        ("EOAT Master Tracker", paths["eoat_master_tracker"], "Required for Atlas inventory/search data."),
        (
            "Press Capacity",
            paths["press_capacity_workbook"],
            "Optional, but needed for capacity-derived tool/machine compatibility.",
        ),
        ("Robot Info", paths["robot_workbook"], "Optional robot-side circuit details."),
        ("EOAT Photos", paths["photos_root"], "Optional visual/photo profile support."),
        ("Standards", paths["reference_docs_folder"], "Optional standards/documentation navigation."),
    ]
    statuses = []
    for label, path, hint in sources:
        exists = path.exists()
        statuses.append(
            AtlasSourceStatus(
                label=label,
                path=str(path),
                exists=exists,
                available=exists,
                message="Available" if exists else f"Not found. {hint}",
            )
        )
    return statuses


def _safe_rows(
    path: Path, sheet_name: str, label: str, *, optional: bool = False
) -> tuple[list[dict[str, Any]], list[WarningItem]]:
    if not path.exists():
        severity = "info" if optional else "warning"
        return [], [
            _warning(
                severity,
                f"{label} not found",
                f"{label} is unavailable until this path is configured: {path}",
                source=label,
            )
        ]
    try:
        return row_dicts_cached(path, sheet_name), []
    except Exception as exc:
        severity = "info" if optional else "warning"
        return [], [_warning(severity, f"{label} could not be read", str(exc), source=label)]


def _cache_signature(
    project_root: Path, *, source_paths: dict[str, str] | None = None
) -> tuple[tuple[str, bool, int, int], ...]:
    paths = _source_path_overrides(project_root, source_paths)
    project_paths = resolve_project_paths(project_root)
    candidates = [
        paths["eoat_master_tracker"],
        paths["press_capacity_workbook"],
        paths["robot_workbook"],
        paths["photos_root"],
        paths["reference_docs_folder"],
    ]
    candidates.extend(_root_standardization_candidates(project_root))
    candidates.extend(
        _standards_document_candidates(project_root, project_paths, standards_root=paths["reference_docs_folder"])
    )
    signature = []
    seen: set[str] = set()
    for path in candidates:
        file_signature = workbook_file_signature(path)
        cache_path = file_signature.path.casefold()
        if cache_path in seen:
            continue
        seen.add(cache_path)
        signature.append((file_signature.path, file_signature.exists, file_signature.mtime_ns, file_signature.size))
    return tuple(signature)


def _standards_document_candidates(project_root: Path, paths, *, standards_root: Path | None = None) -> list[Path]:
    folders = [
        standards_root or paths.standards,
        paths.work_instructions,
        project_root / "Project_Help_Documents",
        project_root / "output" / "documents",
        project_root / "output" / "pdf",
    ]
    documents: list[Path] = []
    for folder in folders:
        if not folder.exists():
            continue
        try:
            documents.extend(
                path
                for path in folder.rglob("*")
                if path.is_file() and path.suffix.lower() in STANDARD_EXTENSIONS and not path.name.startswith("~$")
            )
        except OSError:
            continue
    return sorted(documents, key=lambda path: str(path).casefold())


def _root_standardization_candidates(project_root: Path) -> list[Path]:
    try:
        return [
            path
            for path in sorted(project_root.iterdir())
            if path.is_file()
            and path.suffix.lower() in {".docx", ".pdf", ".md", ".txt"}
            and any(
                keyword in path.name.casefold().replace("_", " ").replace("-", " ")
                for keyword in STANDARDIZATION_KEYWORDS
            )
        ]
    except OSError:
        return []


def _eoat_group_id(row: dict[str, Any], row_index: int) -> str:
    eoat_id = normalize_eoat_assembly_id(row.get("EOAT Assembly ID") or row.get("EOAT ID"))
    if eoat_id:
        return eoat_id
    audit_id = display_value(row.get("Audit ID"))
    if audit_id:
        return f"audit::{audit_id}"
    return f"row::{row_index}"


def _display_eoat_id(row: dict[str, Any], group_id: str) -> str:
    eoat_id = normalize_eoat_assembly_id(row.get("EOAT Assembly ID") or row.get("EOAT ID"))
    if eoat_id:
        return eoat_id
    audit_id = display_value(row.get("Audit ID"))
    if audit_id:
        return audit_id
    return group_id


def _best_primary_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return max(rows, key=lambda row: sum(bool(display_value(value)) for value in row.values()))


def _tools_for_rows(rows: list[dict[str, Any]]) -> list[str]:
    tools: list[str] = []
    for row in rows:
        value = part_number_from_row(row) or row_value(row, ("Tool #", "Tool Number", "Mold #", "Part #"))
        tools.extend(split_multi_value(value))
    return list(sorted_unique(tools))


def _machines_for_rows(rows: list[dict[str, Any]]) -> list[str]:
    machines: list[str] = []
    for row in rows:
        for alias in ("Press/Machine #", "Machine #", "Machine Number", "Press"):
            machines.extend(machine_tokens(row.get(alias)))
    return list(_sort_machine_values(machines))


def _parts_for_rows(rows: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for row in rows:
        for field_name in ("Part #", "Part Number", "Part Name/Description", "Part Family", "Selected Part Number"):
            text = display_value(row.get(field_name))
            if text:
                values.append(text)
    return list(sorted_unique(values))


def _row_values(rows: list[dict[str, Any]], *field_names: str) -> list[str]:
    values: list[str] = []
    for row in rows:
        for field_name in field_names:
            values.extend(split_multi_value(row.get(field_name)))
    return list(sorted_unique(values))


def _sort_machine_values(values) -> tuple[str, ...]:
    normalized = {normalize_machine_token(value) for value in values if normalize_machine_token(value)}
    return tuple(sorted(normalized, key=_machine_sort_key))


def _machine_sort_key(value: str) -> tuple[int, int | str]:
    return (0, int(value)) if str(value).isdigit() else (1, str(value).casefold())


def _robot_rows_by_machine(robot_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    robots = {}
    for row in robot_rows:
        machine = normalize_machine_token(row.get("Machine Number") or row.get("Press/Machine #"))
        if machine:
            robots[machine] = row
    return robots


def _warnings_for_eoat(primary, eoat_id, tools, machines, photo_set, documentation):
    warnings: list[WarningItem] = []
    if not normalize_eoat_assembly_id(primary.get("EOAT Assembly ID")):
        warnings.append(
            _warning(
                "warning",
                "Missing EOAT Assembly ID",
                "This row does not have a formal EOAT Assembly ID, so Atlas is using the audit ID as a fallback.",
                source="EOAT Inventory",
                related_eoat_id=eoat_id,
                why_it_matters="Stable EOAT IDs make search, photos, and compatibility easier to trust.",
                suggested_fix="Assign an EOAT Assembly ID in the EOAT Atlas workbook workflow.",
            )
        )
    if not tools:
        warnings.append(
            _warning(
                "warning",
                "No tool linked",
                "No Tool # / Mold # / Part # was found.",
                source="EOAT Inventory",
                related_eoat_id=eoat_id,
            )
        )
    if not machines:
        warnings.append(
            _warning(
                "warning",
                "No compatible machine linked",
                "No machine compatibility is known.",
                source="EOAT Inventory",
                related_eoat_id=eoat_id,
            )
        )
    if photo_set.total_count == 0:
        warnings.append(
            _warning(
                "warning",
                "No photos linked",
                "No linked or folder-indexed EOAT photos were found.",
                source="Photos",
                related_eoat_id=eoat_id,
                suggested_fix="Use the EOAT Atlas photo workflow to link photos.",
            )
        )
    if documentation.score < 75:
        warnings.append(
            _warning(
                "warning",
                "Documentation below target",
                f"Documentation score is {documentation.score}%. Missing: {', '.join(documentation.missing_fields[:5])}",
                source="Documentation",
                related_eoat_id=eoat_id,
                suggested_fix="Complete missing documentation fields in the master tracker.",
            )
        )
    known_issues = first_present(primary, "Known Issues", "Drop/Mis-Pick History")
    if _has_real_known_issue(known_issues):
        warnings.append(
            _warning(
                "info",
                "Known issue noted",
                known_issues,
                source="EOAT Inventory",
                related_eoat_id=eoat_id,
            )
        )
    return warnings


def _has_real_known_issue(value: str) -> bool:
    text = display_value(value).casefold()
    normalized = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return bool(
        normalized
        and normalized
        not in {
            "no",
            "none",
            "n a",
            "na",
            "unknown",
            "not checked",
            "unknown not checked",
            "unchecked",
            "not indexed",
            "not available",
            "no issues observed",
        }
    )


def _warnings_for_machine(machine, rows, robot, eoat_ids):
    warnings: list[WarningItem] = []
    if not robot:
        warnings.append(
            _warning(
                "info",
                "Robot info missing",
                f"No Robot_Info workbook row was found for Machine {machine}.",
                source="Robot Info",
                machine=machine,
                suggested_fix="Capture robot-side circuit details in the EOAT Atlas workbook workflow.",
            )
        )
    if not eoat_ids:
        warnings.append(
            _warning(
                "warning",
                "No EOAT compatibility",
                f"No EOAT compatibility is known for Machine {machine}.",
                source="Atlas",
                machine=machine,
            )
        )
    if not rows:
        warnings.append(
            _warning(
                "info",
                "No master tracker row",
                f"Machine {machine} appears in reference data but not in EOAT Inventory.",
                source="Press Capacity",
                machine=machine,
            )
        )
    return warnings


def _bundle_warnings(eoats, machines, tools, indexes) -> list[WarningItem]:
    warnings: list[WarningItem] = []
    workbook_tools = {normalized_tool_key(tool.tool) for tool in tools if tool.compatible_eoats}
    for tool in tools:
        if normalized_tool_key(tool.tool) not in workbook_tools and tool.compatible_machines:
            warnings.extend(tool.warnings)
    for machine in machines:
        warnings.extend(machine.warnings)
    return warnings


def _connection_summary(row: dict[str, Any]) -> str:
    direct = first_present(row, "Connection Type")
    pieces = [direct]
    for field_name in ("Pneumatic Quick Disconnect Type", "Electrical Quick Disconnect Type"):
        value = display_value(row.get(field_name))
        if value:
            pieces.append(f"{field_name.replace(' Type', '')}: {value}")
    return "; ".join(piece for piece in pieces if piece)


def _vacuum_summary(row: dict[str, Any]) -> str:
    fields = (
        "Air Circuit Architecture",
        "# of Cups",
        "Cup Type/Material",
        "Cup Diameter/Size",
        "Vacuum Generator Type",
        "EOAT Vacuum Circuits",
        "External Vacuum Circuits",
    )
    return "; ".join(f"{field}: {display_value(row.get(field))}" for field in fields if display_value(row.get(field)))


def _pressure_summary(row: dict[str, Any]) -> str:
    fields = (
        "Air Circuit Architecture",
        "# of Cylinders",
        "Cylinder Type",
        "EOAT Pressure Circuits",
        "External Pressure Circuits",
        "EOAT Interchangeable Circuits",
        "External Interchangeable Circuits",
    )
    return "; ".join(f"{field}: {display_value(row.get(field))}" for field in fields if display_value(row.get(field)))


def _gripper_summary(row: dict[str, Any]) -> str:
    fields = ("# of Grippers", "Gripper Type", "Gripper Model")
    return "; ".join(f"{field}: {display_value(row.get(field))}" for field in fields if display_value(row.get(field)))


def _sensor_summary(row: dict[str, Any]) -> str:
    fields = (
        "Sensors Present?",
        "Sensor Type",
        "Sensor Brand/Model",
        "Vacuum Confirmation Present?",
        "Part-Present Detection Present?",
    )
    return "; ".join(f"{field}: {display_value(row.get(field))}" for field in fields if display_value(row.get(field)))


def _install_notes(row: dict[str, Any]) -> str:
    pieces = [
        first_present(row, "Tubing Routing Notes"),
        first_present(row, "Changeover Difficulty"),
        first_present(row, "Notes"),
    ]
    return "\n".join(piece for piece in pieces if piece)


def _current_eoat_for_rows(rows: list[dict[str, Any]]) -> str:
    return _current_eoat_resolution_for_rows(rows).eoat_id


def _current_eoat_resolution_for_rows(rows: list[dict[str, Any]]) -> CurrentEoatResolution:
    candidates: list[tuple[tuple[int, float, int, int], int, dict[str, Any], str, str, str]] = []
    explicit_no_current = False
    ids_found: list[str] = []
    for index, row in enumerate(rows):
        eoat_id = _eoat_id_for_current_row(row)
        context = _current_context_text(row)
        if eoat_id:
            ids_found.append(eoat_id)
        if _row_is_compatibility_only(context):
            continue
        if not eoat_id:
            explicit_no_current = explicit_no_current or _row_explicitly_has_no_current_eoat(context)
            continue
        date_value = _current_row_date_value(row)
        has_date = 1 if date_value else 0
        explicit_score = _current_row_explicit_score(context)
        source = _current_row_source(row, index)
        confidence = "high" if explicit_score >= 300 else "medium" if explicit_score >= 200 else "low"
        reason = (
            "latest audit"
            if has_date
            else "explicit installed audit"
            if explicit_score >= 300
            else "fallback audit row"
        )
        candidates.append(
            ((has_date, date_value, explicit_score, index), index, row, eoat_id, source, f"{confidence}|{reason}")
        )
    unique_ids = tuple(sorted(set(ids_found), key=str.casefold))
    if not candidates:
        if explicit_no_current:
            return CurrentEoatResolution(
                status="explicit_none",
                source="EOAT Inventory",
                confidence="high",
                reason="explicit no current EOAT",
                matching_rows_count=len(rows),
                eoat_ids_found=unique_ids,
            )
        return CurrentEoatResolution(matching_rows_count=len(rows), eoat_ids_found=unique_ids)
    _sort_key, source_index, _row, eoat_id, source, confidence_reason = max(
        candidates, key=lambda candidate: candidate[0]
    )
    confidence, reason = confidence_reason.split("|", 1)
    return CurrentEoatResolution(
        eoat_id=eoat_id,
        status="indexed",
        source=source,
        confidence=confidence,
        reason=reason,
        source_row_index=source_index,
        matching_rows_count=len(rows),
        eoat_ids_found=unique_ids,
        ambiguous=len(unique_ids) > 1,
    )


def _eoat_id_for_current_row(row: dict[str, Any]) -> str:
    for field_name in ("EOAT Assembly ID", "EOAT ID"):
        eoat_id = normalize_eoat_assembly_id(row.get(field_name))
        if eoat_id:
            return eoat_id
    audit_id = normalize_eoat_assembly_id(row.get("Audit ID"))
    return audit_id if is_valid_eoat_assembly_id(audit_id) else ""


def _current_context_text(row: dict[str, Any]) -> str:
    fields = (
        "Audit Context",
        "Entry Type",
        "Status",
        "Physical Audit Verified",
        "Compatibility Source",
        "Compatibility Confidence",
        "Notes",
        "Known Issues",
    )
    return " ".join(display_value(row.get(field)) for field in fields if display_value(row.get(field))).casefold()


def _row_is_compatibility_only(context: str) -> bool:
    if "compatibility row" in context or "entry type compatible" in context or "press capacity" in context:
        return True
    return "compatible" in context and not any(
        phrase in context for phrase in ("installed", "current", "audited", "physical audit")
    )


def _row_explicitly_has_no_current_eoat(context: str) -> bool:
    return any(
        phrase in context
        for phrase in (
            "no current eoat",
            "no eoat installed",
            "eoat not installed",
            "not installed / bench audit",
            "not installed",
        )
    )


def _current_row_explicit_score(context: str) -> int:
    if _row_explicitly_has_no_current_eoat(context):
        return 80
    if "installed on machine" in context or "current" in context or "installed" in context:
        return 360
    if "physical audit verified" in context or "audited" in context or "complete" in context:
        return 300
    if "in progress" in context or "needs review" in context:
        return 220
    return 100


def _current_row_date_value(row: dict[str, Any]) -> float:
    for field_name in ("Audit Date", "Completed Date", "Completion Date", "Date", "Updated", "Created"):
        value = row.get(field_name)
        if isinstance(value, datetime):
            return value.timestamp()
        text = display_value(value)
        if not text:
            continue
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y", "%m/%d/%y"):
            try:
                return datetime.strptime(text, fmt).timestamp()
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text).timestamp()
        except ValueError:
            continue
    return 0.0


def _current_row_source(row: dict[str, Any], index: int) -> str:
    audit_id = display_value(row.get("Audit ID"))
    audit_date = display_value(row.get("Audit Date"))
    pieces = [f"source row {index + 1}"]
    if audit_id:
        pieces.append(f"Audit {audit_id}")
    if audit_date:
        pieces.append(audit_date)
    return " | ".join(pieces)


def _warning(
    severity: str,
    title: str,
    message: str,
    *,
    source: str = "",
    related_eoat_id: str = "",
    machine: str = "",
    tool: str = "",
    why_it_matters: str = "",
    suggested_fix: str = "",
) -> WarningItem:
    return WarningItem(
        severity=severity,
        title=title,
        message=message,
        source=source,
        related_eoat_id=related_eoat_id,
        machine=machine,
        tool=tool,
        why_it_matters=why_it_matters,
        suggested_fix=suggested_fix,
    )


def _average(values) -> int:
    items = [int(value) for value in values if isinstance(value, int) or str(value).isdigit()]
    return round(sum(items) / len(items)) if items else 0


__all__ = ["invalidate_atlas_data_cache", "load_atlas_data"]
