from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .atlas_models import AtlasDataBundle, EOATRecord, MachineRecord, PhotoItem, ToolRecord, WarningItem
from .atlas_utils import display_value, normalized_eoat_key, normalized_machine_key, normalized_tool_key
from .paths import resolve_project_paths
from .performance import perf_timer
from .workbook_io import row_dicts


ENTITY_EOAT = "eoat"
ENTITY_TOOL = "tool"
ENTITY_MACHINE = "machine"
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}


@dataclass(frozen=True)
class RecordField:
    label: str
    value: str | tuple[str, ...]
    tone: str = "normal"


@dataclass(frozen=True)
class RecordSection:
    title: str
    fields: tuple[RecordField, ...]


@dataclass(frozen=True)
class RecordPhoto:
    path: str
    filename: str
    category: str
    photo_id: str = ""
    date_taken: str = ""
    association: str = ""
    description: str = ""
    source: str = ""
    folder_path: str = ""
    stored_relative_path: str = ""
    stored_filename: str = ""
    photo_filename: str = ""
    original_filename: str = ""
    eoat_id: str = ""
    tool: str = ""
    machine: str = ""
    path_candidates: tuple[str, ...] = ()

    @property
    def exists(self) -> bool:
        return bool(self.path and Path(self.path).exists())


@dataclass(frozen=True)
class RecordPhotoGroup:
    title: str
    photos: tuple[RecordPhoto, ...]


@dataclass(frozen=True)
class RecordWorkbookRow:
    source: str
    label: str
    fields: tuple[RecordField, ...]


@dataclass(frozen=True)
class RecordWorkbookSection:
    title: str
    rows: tuple[RecordWorkbookRow, ...]


@dataclass(frozen=True)
class RecordDetailData:
    record_type: str
    record_id: str
    title: str
    subtitle: str
    condition: str
    plant_area: str
    hero_fields: tuple[RecordField, ...]
    detail_sections: tuple[RecordSection, ...]
    documentation_fields: tuple[RecordField, ...]
    photo_groups: tuple[RecordPhotoGroup, ...]
    history_fields: tuple[RecordField, ...]
    summary_fields: tuple[RecordField, ...]
    report_sections: tuple[RecordSection, ...]
    workbook_sections: tuple[RecordWorkbookSection, ...] = ()
    warnings: tuple[WarningItem, ...] = ()
    source_rows: tuple[dict[str, Any], ...] = ()

    @property
    def photo_count(self) -> int:
        return sum(len(group.photos) for group in self.photo_groups)


def build_record_detail_data(bundle: AtlasDataBundle, record_type: str, record_id: str) -> RecordDetailData:
    normalized_type = str(record_type or "").casefold()
    with perf_timer(
        bundle.project_root,
        f"record.detail.build.{normalized_type or 'unknown'}",
        details={"record_type": normalized_type, "record_id": record_id},
        source="atlas_record_details",
        page_tool="library_record",
    ):
        if normalized_type == ENTITY_EOAT:
            record = _find_eoat(bundle, record_id)
            if record is None:
                raise ValueError(f"EOAT record not found: {record_id}")
            return _eoat_detail(bundle, record)
        if normalized_type == ENTITY_TOOL:
            record = _find_tool(bundle, record_id)
            if record is None:
                raise ValueError(f"Tool record not found: {record_id}")
            return _tool_detail(bundle, record)
        if normalized_type == ENTITY_MACHINE:
            record = _find_machine(bundle, record_id)
            if record is None:
                raise ValueError(f"Machine record not found: {record_id}")
            return _machine_detail(bundle, record)
    raise ValueError(f"Unsupported record type: {record_type}")


def get_photos_for_record(bundle: AtlasDataBundle, record_type: str, record_id: str) -> tuple[RecordPhotoGroup, ...]:
    normalized_type = str(record_type or "").casefold()
    with perf_timer(
        bundle.project_root,
        "record.photo_records_lookup",
        details={"record_type": normalized_type, "record_id": record_id},
        source="atlas_record_details",
        page_tool="library_record",
    ):
        if normalized_type == ENTITY_EOAT:
            record = _find_eoat(bundle, record_id)
            return _eoat_photo_groups(bundle, record) if record else ()
        if normalized_type == ENTITY_TOOL:
            record = _find_tool(bundle, record_id)
            return _tool_photo_groups(bundle, record) if record else ()
        if normalized_type == ENTITY_MACHINE:
            record = _find_machine(bundle, record_id)
            return _machine_photo_groups(bundle, record) if record else ()
    return ()


def _eoat_detail(bundle: AtlasDataBundle, record: EOATRecord) -> RecordDetailData:
    rows = tuple(getattr(record, "source_rows", ()) or ())
    condition = _eoat_condition(bundle, record)
    current_machine = _current_machine_for_eoat(bundle, record.eoat_id)
    plant_area = _first_row(rows, "Plant/Area", "Plant", "Area") or _area_from_rows(rows)
    photos = _eoat_photo_groups(bundle, record)
    photo_count = _photo_count(photos)
    doc_score = int(getattr(record.documentation, "score", 0) or 0)
    last_audit = _last_audit(rows)
    tool_values = tuple(getattr(record, "tools", ()) or ())
    machine_values = tuple(getattr(record, "machines", ()) or ())
    details = (
        RecordSection(
            "Identification",
            _fields(
                ("EOAT Assembly ID", record.eoat_id),
                ("Audit ID", tuple(getattr(record, "audit_ids", ()) or ()) or _first_row(rows, "Audit ID")),
                ("Audit Date", last_audit),
                ("Auditor", _first_row(rows, "Auditor")),
                ("Plant / Area", plant_area),
                ("Press / Machine #", machine_values or _first_row(rows, "Press/Machine #", "Machine #")),
                ("Tool #", tool_values or _first_row(rows, "Tool #", "Tool Number")),
                ("Part Family", record.part_family or _first_row(rows, "Part Family")),
                ("Part Name / Description", record.part_description or _first_row(rows, "Part Name/Description", "Part Name")),
            ),
        ),
        RecordSection(
            "EOAT Configuration",
            _fields(
                ("EOAT Type", record.eoat_type or _first_row(rows, "EOAT Type")),
                ("EOAT Moves", _first_row(rows, "EOAT Moves")),
                ("Connection Type", record.connection_type or _first_row(rows, "Connection Type")),
                ("Parts Picked", _first_row(rows, "Number of Parts Picked", "# Parts Picked")),
                ("# of Cylinders", _first_row(rows, "# of Cylinders")),
                ("Cylinder Type", _first_row(rows, "Cylinder Type")),
                ("# of Grippers", _first_row(rows, "# of Grippers")),
                ("Gripper Type", _first_row(rows, "Gripper Type")),
                ("Gripper Model", _first_row(rows, "Gripper Model")),
                ("# of Cups", _first_row(rows, "# of Cups")),
                ("Cup Type / Material", _first_row(rows, "Cup Type/Material")),
                ("Cup Diameter / Size", _first_row(rows, "Cup Diameter/Size")),
                ("Vacuum Generator", _first_row(rows, "Vacuum Generator Type")),
            ),
        ),
        RecordSection(
            "Air / Electrical / Sensors",
            _fields(
                ("Air Circuit Architecture", _air_architecture(rows, record)),
                ("EOAT Vacuum Circuits", _first_row(rows, "EOAT Vacuum Circuits")),
                ("EOAT Pressure Circuits", _first_row(rows, "EOAT Pressure Circuits")),
                ("EOAT Interchangeable", _first_row(rows, "EOAT Interchangeable Circuits")),
                ("External Vacuum", _first_row(rows, "External Vacuum Circuits")),
                ("External Pressure", _first_row(rows, "External Pressure Circuits")),
                ("External Interchangeable", _first_row(rows, "External Interchangeable Circuits")),
                ("Sensors?", _first_row(rows, "Sensors?", "Sensors Present?")),
                ("Sensor Type", _first_row(rows, "Sensor Type") or record.sensor_info),
                ("Part Present Sensor?", _first_row(rows, "Part Present Sensor?", "Part-Present Detection Present?")),
                ("Electrical QD", _first_row(rows, "Electrical Quick Disconnect Type")),
                ("Pneumatic QD", _first_row(rows, "Pneumatic Quick Disconnect Type")),
            ),
        ),
        RecordSection(
            "Documentation / Maintenance / Notes",
            _fields(
                ("Photo Link / Count", f"{photo_count} photo(s)"),
                ("Tubing Routing Notes", record.tubing_notes or _first_row(rows, "Tubing Routing Notes", "Tubing Notes")),
                ("Known Issues / Observations", record.known_issues or _first_row(rows, "Known Issues / Observations", "Known Issues")),
                ("Maintenance Frequency", _first_row(rows, "Maintenance Frequency")),
                ("Documentation Score", f"{doc_score}%"),
                ("Missing Documentation", tuple(getattr(record.documentation, "missing_fields", ()) or ()) or "None indexed"),
            ),
        ),
    )
    hero = _fields(
        ("Type", record.eoat_type or "EOAT"),
        ("Condition / Location", condition),
        ("Current Machine", current_machine or _first(machine_values)),
        ("Plant / Area", plant_area),
        ("Tool #", _first(tool_values) if len(tool_values) <= 1 else f"{len(tool_values)} tools"),
        ("Part Family", record.part_family or record.part_description),
        ("Parts Picked", _first_row(rows, "Number of Parts Picked", "# Parts Picked")),
        ("Connection Type", record.connection_type or _first_row(rows, "Connection Type")),
        ("Air Architecture", _air_architecture(rows, record)),
        ("Sensors", _sensor_summary(rows, record)),
        ("Photos", str(photo_count)),
        ("Last Audit", last_audit),
    )
    docs = _documentation_fields(doc_score, tuple(getattr(record.documentation, "missing_fields", ()) or ()), photo_count, _photo_folder(photos, record.photos.folder_path))
    summary = _fields(("Machines", str(len(machine_values))), ("Tools", str(len(tool_values))), ("Documentation", f"{doc_score}%"))
    return RecordDetailData(
        record_type=ENTITY_EOAT,
        record_id=record.eoat_id,
        title=record.eoat_id,
        subtitle=record.eoat_type or record.part_description or "EOAT",
        condition=condition,
        plant_area=plant_area,
        hero_fields=hero,
        detail_sections=details,
        documentation_fields=docs,
        photo_groups=photos,
        history_fields=_history_fields(rows, getattr(record, "audit_ids", ())),
        summary_fields=summary,
        report_sections=details,
        workbook_sections=_workbook_sections(bundle, ENTITY_EOAT, record, rows, photos),
        warnings=tuple(getattr(record, "warnings", ()) or ()),
        source_rows=rows,
    )


def _tool_detail(bundle: AtlasDataBundle, record: ToolRecord) -> RecordDetailData:
    rows = _tool_rows(bundle, record)
    related_eoats = tuple(getattr(record, "compatible_eoats", ()) or ())
    related_machines = tuple(getattr(record, "compatible_machines", ()) or ())
    photos = _tool_photo_groups(bundle, record)
    photo_count = _photo_count(photos)
    doc_score = 100 if not getattr(record, "warnings", ()) else 68
    plant_area = _first_row(rows, "Plant/Area", "Plant", "Area") or _area_from_rows(rows)
    current_machine = _first_current_machine_for_tool(bundle, record)
    current_eoat = _first_current_eoat_for_tool(bundle, record)
    details = (
        RecordSection(
            "Identification",
            _fields(
                ("Tool #", record.tool),
                ("Mold #", tuple(getattr(record, "molds", ()) or ()) or _first_row(rows, "Mold #", "Mold Number")),
                ("Part #", tuple(getattr(record, "parts", ()) or ()) or _first_row(rows, "Part #", "Part Number")),
                ("Part Family", record.part_family or _first_row(rows, "Part Family")),
                ("Part Name / Description", record.part_description or _first_row(rows, "Part Name/Description", "Part Name")),
                ("Plant / Area", plant_area),
                ("Last Audit Date", _last_audit(rows)),
            ),
        ),
        RecordSection(
            "Compatibility",
            _fields(
                ("Compatible EOATs", related_eoats or "Not Indexed"),
                ("Compatible Machines", related_machines or "Not Indexed"),
                ("Current Machine", current_machine),
                ("Current EOAT", current_eoat),
                ("Parts Picked", _first_row(rows, "Number of Parts Picked", "# Parts Picked")),
            ),
        ),
        RecordSection(
            "EOAT Requirements",
            _fields(
                ("EOAT Type", _first_row(rows, "EOAT Type")),
                ("Moves", _first_row(rows, "EOAT Moves")),
                ("Connection Type", _first_row(rows, "Connection Type")),
                ("Air Architecture", _first_row(rows, "Air Circuit Architecture")),
                ("Sensors / Part Present", _sensor_summary(rows, None)),
                ("Quick Disconnects", _quick_disconnect_summary(rows)),
            ),
        ),
        RecordSection(
            "Documentation / Notes",
            _fields(
                ("Photo Count", str(photo_count)),
                ("Known Issues / Observations", _first_row(rows, "Known Issues / Observations", "Known Issues")),
                ("Maintenance Frequency", _first_row(rows, "Maintenance Frequency")),
                ("Missing Documentation", "Review warnings" if getattr(record, "warning_count", 0) else "None indexed"),
            ),
        ),
    )
    hero = _fields(
        ("Part Family", record.part_family or _first_row(rows, "Part Family")),
        ("Part Name", record.part_description or _first_row(rows, "Part Name/Description", "Part Name")),
        ("Plant / Area", plant_area),
        ("Last Audit", _last_audit(rows)),
        ("Compatible EOATs", str(len(related_eoats))),
        ("Compatible Machines", str(len(related_machines))),
        ("Parts Picked", _first_row(rows, "Number of Parts Picked", "# Parts Picked")),
        ("Connection / EOAT Type", _first_row(rows, "Connection Type") or _first_row(rows, "EOAT Type")),
        ("Current Machine", current_machine),
        ("Documentation Score", f"{doc_score}%"),
        ("Photos", str(photo_count)),
        ("Known Issues", _issue_summary(rows, getattr(record, "warnings", ()))),
    )
    docs = _documentation_fields(doc_score, ("Review warnings",) if getattr(record, "warning_count", 0) else (), photo_count, _photo_folder(photos, ""))
    summary = _fields(("EOATs", str(len(related_eoats))), ("Machines", str(len(related_machines))), ("Parts Picked", str(len(getattr(record, "parts", ()) or ())) or "Not Indexed"))
    return RecordDetailData(
        record_type=ENTITY_TOOL,
        record_id=record.tool,
        title=record.tool,
        subtitle=record.part_description or record.part_family or "Tool / Mold / Part",
        condition=current_machine or "Not Indexed",
        plant_area=plant_area,
        hero_fields=hero,
        detail_sections=details,
        documentation_fields=docs,
        photo_groups=photos,
        history_fields=_history_fields(rows, ()),
        summary_fields=summary,
        report_sections=details,
        workbook_sections=_workbook_sections(bundle, ENTITY_TOOL, record, rows, photos),
        warnings=tuple(getattr(record, "warnings", ()) or ()),
        source_rows=rows,
    )


def _machine_detail(bundle: AtlasDataBundle, record: MachineRecord) -> RecordDetailData:
    rows = tuple(getattr(record, "source_rows", ()) or ())
    current_eoat = display_value(getattr(record, "current_eoat", "")) or _machine_current_fallback(record)
    current_tool_values = _current_tools_for_machine(bundle, record)
    photos = _machine_photo_groups(bundle, record)
    photo_count = _photo_count(photos)
    doc_score = int(getattr(record, "documentation_score", 0) or 0)
    plant_area = _first_row(rows, "Plant/Area", "Plant", "Area") or _area_from_rows(rows)
    area = _first_row(rows, "Cleanroom/Non-Cleanroom", "Area") or ("Cleanroom" if "cleanroom" in _rows_blob(rows) else "Production")
    details = (
        RecordSection(
            "Identification",
            _fields(
                ("Machine #", record.machine),
                ("Plant / Area", plant_area),
                ("Cleanroom / Non-Cleanroom", area),
                ("Robot Type", record.robot_type or _first_row(rows, "Robot Type")),
                ("Robot Model / Controller", record.robot_model or record.controller or _first_row(rows, "Robot Model/Controller")),
                ("Last Audit Date", _last_audit(rows)),
            ),
        ),
        RecordSection(
            "Current Setup",
            _fields(
                ("Current EOAT", current_eoat),
                ("Current Tool(s)", current_tool_values or "Not Indexed"),
                ("Part Family", _first_row(rows, "Part Family")),
                ("Part Name / Description", _first_row(rows, "Part Name/Description", "Part Name")),
                ("Connection Type", _first_row(rows, "Connection Type")),
                ("Parts Picked", _first_row(rows, "Number of Parts Picked", "# Parts Picked")),
            ),
        ),
        RecordSection(
            "Compatibility",
            _fields(
                ("Compatible EOATs", tuple(getattr(record, "compatible_eoats", ()) or ()) or "Not Indexed"),
                ("Compatible Tools", tuple(getattr(record, "compatible_tools", ()) or ()) or "Not Indexed"),
                ("EOAT Count", str(len(getattr(record, "compatible_eoats", ()) or ()))),
                ("Tool Count", str(len(getattr(record, "compatible_tools", ()) or ()))),
            ),
        ),
        RecordSection(
            "Air / External Circuits / Notes",
            _fields(
                ("Air Circuit Architecture", _first_row(rows, "Air Circuit Architecture")),
                ("External Pressure", _first_row(rows, "External Pressure Circuits")),
                ("External Vacuum", _first_row(rows, "External Vacuum Circuits")),
                ("External Interchangeable", _first_row(rows, "External Interchangeable Circuits")),
                ("Known Issues / Observations", _first_row(rows, "Known Issues / Observations", "Known Issues")),
                ("Maintenance Frequency", _first_row(rows, "Maintenance Frequency")),
            ),
        ),
    )
    hero = _fields(
        ("Robot Type", record.robot_type or _first_row(rows, "Robot Type")),
        ("Robot Model", record.robot_model or record.controller or _first_row(rows, "Robot Model/Controller")),
        ("Area", area),
        ("Last Audit", _last_audit(rows)),
        ("Current EOAT", current_eoat),
        ("Compatible EOATs", str(len(getattr(record, "compatible_eoats", ()) or ()))),
        ("Compatible Tools", str(len(getattr(record, "compatible_tools", ()) or ()))),
        ("Plant / Area", plant_area),
        ("Air Architecture", _first_row(rows, "Air Circuit Architecture")),
        ("External Circuits", _external_circuit_summary(rows)),
        ("Documentation Score", f"{doc_score}%"),
        ("Known Issues", _issue_summary(rows, getattr(record, "warnings", ()))),
    )
    docs = _documentation_fields(doc_score, ("Machine documentation incomplete",) if doc_score < 75 else (), photo_count, _photo_folder(photos, ""))
    summary = _fields(("EOATs", str(len(getattr(record, "compatible_eoats", ()) or ()))), ("Tools", str(len(getattr(record, "compatible_tools", ()) or ()))), ("Current EOAT", current_eoat))
    return RecordDetailData(
        record_type=ENTITY_MACHINE,
        record_id=record.machine,
        title=f"Machine {record.machine}",
        subtitle=record.robot_type or record.robot_model or "Machine",
        condition=current_eoat,
        plant_area=plant_area,
        hero_fields=hero,
        detail_sections=details,
        documentation_fields=docs,
        photo_groups=photos,
        history_fields=_history_fields(rows, ()),
        summary_fields=summary,
        report_sections=details,
        workbook_sections=_workbook_sections(bundle, ENTITY_MACHINE, record, rows, photos),
        warnings=tuple(getattr(record, "warnings", ()) or ()),
        source_rows=rows,
    )


def _eoat_photo_groups(bundle: AtlasDataBundle, record: EOATRecord) -> tuple[RecordPhotoGroup, ...]:
    with perf_timer(
        bundle.project_root,
        "record.photo_records_lookup.eoat",
        details={"record_type": ENTITY_EOAT, "record_id": record.eoat_id},
        source="atlas_record_details",
        page_tool="library_record",
    ):
        audit_ids = {str(value).casefold() for value in getattr(record, "audit_ids", ()) or ()}
        eoat_key = normalized_eoat_key(record.eoat_id)
        photos = [
            photo
            for photo in _all_photo_items(bundle)
            if normalized_eoat_key(photo.eoat_id) == eoat_key
            or (photo.related_audit_id and photo.related_audit_id.casefold() in audit_ids)
        ]
        return _group_photos(photos, default_association=record.eoat_id, project_root=bundle.project_root)


def _tool_photo_groups(bundle: AtlasDataBundle, record: ToolRecord) -> tuple[RecordPhotoGroup, ...]:
    with perf_timer(
        bundle.project_root,
        "record.photo_records_lookup.tool",
        details={"record_type": ENTITY_TOOL, "record_id": record.tool},
        source="atlas_record_details",
        page_tool="library_record",
    ):
        tool_key = normalized_tool_key(record.tool)
        direct: list[PhotoItem] = []
        related: list[PhotoItem] = []
        indexed_paths = set(bundle.indexes.photos_by_tool.get(tool_key, ()))
        eoat_keys = {normalized_eoat_key(value) for value in getattr(record, "compatible_eoats", ()) or ()}
        for photo in _all_photo_items(bundle):
            if normalized_tool_key(photo.tool) == tool_key or photo.path in indexed_paths:
                direct.append(photo)
            elif normalized_eoat_key(photo.eoat_id) in eoat_keys:
                related.append(photo)
        groups = []
        if direct:
            groups.extend(_group_photos(direct, default_association=f"Tool {record.tool}", title_prefix="Direct", project_root=bundle.project_root))
        if related:
            groups.extend(_group_photos(related, default_association="Related EOAT", title_prefix="Related EOAT", project_root=bundle.project_root))
        return tuple(groups)


def _machine_photo_groups(bundle: AtlasDataBundle, record: MachineRecord) -> tuple[RecordPhotoGroup, ...]:
    with perf_timer(
        bundle.project_root,
        "record.photo_records_lookup.machine",
        details={"record_type": ENTITY_MACHINE, "record_id": record.machine},
        source="atlas_record_details",
        page_tool="library_record",
    ):
        machine_key = normalized_machine_key(record.machine)
        direct: list[PhotoItem] = []
        related: list[PhotoItem] = []
        current_key = normalized_eoat_key(getattr(record, "current_eoat", ""))
        for photo in _all_photo_items(bundle):
            if normalized_machine_key(photo.machine) == machine_key:
                direct.append(photo)
            elif current_key and normalized_eoat_key(photo.eoat_id) == current_key:
                related.append(photo)
        groups = []
        if direct:
            groups.extend(_group_photos(direct, default_association=f"Machine {record.machine}", title_prefix="Machine", project_root=bundle.project_root))
        if related:
            groups.extend(_group_photos(related, default_association="Current EOAT", title_prefix="Current EOAT", project_root=bundle.project_root))
        return tuple(groups)


def _group_photos(
    photos: Iterable[PhotoItem],
    *,
    default_association: str,
    title_prefix: str = "",
    project_root: str | Path = "",
) -> tuple[RecordPhotoGroup, ...]:
    deduped = _dedupe_photo_items(tuple(photos))
    with perf_timer(
        project_root,
        "record.photo_group_build",
        details={"photo_count": len(deduped), "title_prefix": title_prefix},
        source="atlas_record_details",
        page_tool="library_record",
    ):
        groups: dict[str, list[RecordPhoto]] = {}
        for photo in deduped:
            category = display_value(photo.photo_type) or display_value(photo.area_shown) or display_value(photo.category) or "Other"
            title = _friendly_photo_group(category)
            if title_prefix:
                title = f"{title_prefix}: {title}"
            association = _photo_association(photo) or default_association
            resolved_path, path_candidates = _resolve_record_photo_path(project_root, photo)
            groups.setdefault(title, []).append(
                RecordPhoto(
                    path=str(resolved_path),
                    filename=photo.filename or resolved_path.name or Path(photo.path).name,
                    category=category,
                    photo_id=photo.photo_id,
                    date_taken=photo.date_taken,
                    association=association,
                    description=photo.description,
                    source=photo.source,
                    folder_path=photo.folder_path,
                    stored_relative_path=photo.stored_relative_path,
                    stored_filename=photo.stored_filename,
                    photo_filename=photo.photo_filename,
                    original_filename=photo.original_filename,
                    eoat_id=photo.eoat_id,
                    tool=photo.tool,
                    machine=photo.machine,
                    path_candidates=tuple(str(path) for path in path_candidates),
                )
            )
        return tuple(RecordPhotoGroup(title, tuple(items)) for title, items in sorted(groups.items(), key=lambda item: item[0].casefold()))


def _resolve_record_photo_path(project_root: str | Path, photo: PhotoItem) -> tuple[Path, tuple[Path, ...]]:
    with perf_timer(
        project_root,
        "record.photo_path_resolution",
        details={
            "ui_sensitive": "photo_path_resolution",
            "photo_id": photo.photo_id,
            "filename": photo.filename or (Path(photo.path).name if photo.path else ""),
        },
        source="atlas_record_details",
        page_tool="library_record",
    ):
        root = Path(project_root) if project_root else None
        candidates: list[Path] = []

        def add_candidate(value: str | Path) -> None:
            text = display_value(value)
            if not text:
                return
            if text.casefold().startswith("file://"):
                text = text[7:]
            text = text.strip("\"'")
            path = Path(text)
            if not path.is_absolute() and root is not None:
                path = root / path
            if path not in candidates:
                candidates.append(path)

        add_candidate(photo.path)

        stored_relative_path = display_value(photo.stored_relative_path)
        if stored_relative_path:
            add_candidate(stored_relative_path)
            if root is not None:
                add_candidate(root / stored_relative_path)
                add_candidate(resolve_project_paths(root).master_workbook.parent / stored_relative_path)
                add_candidate(resolve_project_paths(root).cell_photos / stored_relative_path)

        folder_text = display_value(photo.folder_path)
        filenames = tuple(
            name
            for name in (photo.stored_filename, photo.photo_filename, photo.filename, photo.original_filename, Path(photo.path).name if photo.path else "")
            if display_value(name)
        )
        if folder_text:
            folder = Path(folder_text.strip("\"'"))
            if not folder.is_absolute() and root is not None:
                folder = root / folder
            if folder.suffix.casefold() in PHOTO_EXTENSIONS:
                add_candidate(folder)
            for filename in filenames:
                add_candidate(folder / filename)

        for filename in filenames:
            add_candidate(filename)
            if root is not None:
                paths = resolve_project_paths(root)
                add_candidate(paths.cell_photos / filename)
                try:
                    match = next(paths.cell_photos.rglob(filename), None) if paths.cell_photos.exists() else None
                except OSError:
                    match = None
                if match is not None:
                    add_candidate(match)

        for candidate in candidates:
            if candidate.exists() and candidate.suffix.casefold() in PHOTO_EXTENSIONS:
                return candidate.resolve(strict=False), tuple(candidates)
        return (candidates[0].resolve(strict=False) if candidates else Path(display_value(photo.path))), tuple(candidates)


def _all_photo_items(bundle: AtlasDataBundle) -> tuple[PhotoItem, ...]:
    photos: list[PhotoItem] = []
    for eoat in getattr(bundle, "eoats", ()) or ():
        photo_set = getattr(eoat, "photos", None)
        if photo_set is None:
            continue
        photos.extend(getattr(photo_set, "photos", ()) or ())
        photos.extend(getattr(photo_set, "indexed_photos", ()) or ())
    for paths in getattr(bundle.indexes, "photos_by_tool", {}).values():
        for path in paths:
            photos.append(PhotoItem(path=path, filename=Path(path).name, source="tool photo index"))
    return tuple(_dedupe_photo_items(tuple(photos)))


def _dedupe_photo_items(photos: tuple[PhotoItem, ...]) -> tuple[PhotoItem, ...]:
    deduped: dict[str, PhotoItem] = {}
    for photo in photos:
        key = (photo.path or photo.filename).casefold()
        if not key:
            continue
        existing = deduped.get(key)
        if existing is None or (photo.source == "photo index" and existing.source != "photo index"):
            deduped[key] = photo
    return tuple(sorted(deduped.values(), key=lambda item: ((item.date_taken or "9999").casefold(), item.category.casefold(), item.filename.casefold())))


def _documentation_fields(score: int, missing: tuple[str, ...], photo_count: int, folder: str) -> tuple[RecordField, ...]:
    return _fields(
        ("Documentation Score", f"{score}%"),
        ("Photo Folder / Link", folder or ("Indexed" if photo_count else "Not Indexed")),
        ("CAD Status", _doc_status_for(missing, "cad")),
        ("BOM Status", _doc_status_for(missing, "bom")),
        ("Revision Status", _doc_status_for(missing, "revision")),
        ("Process Binder", _doc_status_for(missing, "process binder")),
        ("Missing Items", missing or ("None indexed",)),
    )


def _doc_status_for(missing: tuple[str, ...], keyword: str) -> str:
    return "Missing" if any(keyword in item.casefold() for item in missing) else "Indexed"


def _fields(*items: tuple[str, Any]) -> tuple[RecordField, ...]:
    fields: list[RecordField] = []
    for label, value in items:
        fields.append(RecordField(label, _field_value(value), "muted" if not _has_value(value) else "normal"))
    return tuple(fields)


def _field_value(value: Any) -> str | tuple[str, ...]:
    if isinstance(value, (tuple, list, set)):
        cleaned = tuple(display_value(item) for item in value if display_value(item))
        return cleaned or "Not Indexed"
    text = display_value(value)
    return text or "Not Indexed"


def _has_value(value: Any) -> bool:
    if isinstance(value, (tuple, list, set)):
        return any(display_value(item) for item in value)
    return bool(display_value(value))


def _find_eoat(bundle: AtlasDataBundle, value: str) -> EOATRecord | None:
    key = normalized_eoat_key(value)
    return next((record for record in bundle.eoats if normalized_eoat_key(record.eoat_id) == key), None)


def _find_tool(bundle: AtlasDataBundle, value: str) -> ToolRecord | None:
    key = normalized_tool_key(value)
    return next((record for record in bundle.tools if normalized_tool_key(record.tool) == key), None)


def _find_machine(bundle: AtlasDataBundle, value: str) -> MachineRecord | None:
    key = normalized_machine_key(value)
    return next((record for record in bundle.machines if normalized_machine_key(record.machine) == key), None)


def _first_row(rows: Iterable[dict[str, Any]], *names: str) -> str:
    wanted = {name.casefold(): name for name in names}
    for row in rows:
        if not isinstance(row, dict):
            continue
        folded = {str(key).casefold(): key for key in row}
        for name in names:
            key = folded.get(name.casefold())
            if key is not None:
                value = display_value(row.get(key))
                if value:
                    return value
        for key in row:
            if str(key).casefold() in wanted:
                value = display_value(row.get(key))
                if value:
                    return value
    return ""


def _last_audit(rows: tuple[dict[str, Any], ...]) -> str:
    for name in ("Audit Date", "Completed Date", "Completion Date", "Date", "Updated"):
        value = _first_row(rows, name)
        if value:
            return value
    return ""


def _history_fields(rows: tuple[dict[str, Any], ...], audit_ids: Iterable[str]) -> tuple[RecordField, ...]:
    fields: list[RecordField] = []
    for index, audit_id in enumerate(audit_ids or (), start=1):
        if display_value(audit_id):
            fields.append(RecordField(f"Audit {index}", display_value(audit_id)))
    if not fields:
        for index, row in enumerate(rows[:6], start=1):
            label = display_value(row.get("Audit Date") or row.get("Completed Date") or row.get("Date") or f"Source row {index}")
            value = display_value(row.get("Status") or row.get("Entry Type") or row.get("Audit ID") or "Indexed")
            fields.append(RecordField(label, value))
    return tuple(fields) or (RecordField("History", "No history indexed for this record.", "muted"),)


def _workbook_sections(
    bundle: AtlasDataBundle,
    record_type: str,
    record: EOATRecord | ToolRecord | MachineRecord,
    source_rows: tuple[dict[str, Any], ...],
    photo_groups: tuple[RecordPhotoGroup, ...],
) -> tuple[RecordWorkbookSection, ...]:
    context = _record_match_context(record_type, record, source_rows)
    sections: list[RecordWorkbookSection] = []
    if source_rows:
        sections.append(_workbook_section_from_rows("EOAT Inventory Source Rows", "EOAT Inventory", source_rows))
    for sheet_name in (
        "Photo Index",
        "Audit by Press",
        "Issue Log",
        "Action Items",
        "Pilot Candidates",
        "FMEA Draft",
        "KPI Baseline",
    ):
        rows = _matching_sheet_rows(bundle, sheet_name, context)
        if rows:
            sections.append(_workbook_section_from_rows(f"{sheet_name} Rows", sheet_name, tuple(rows)))
    capacity_rows = _matching_press_capacity_rows(bundle, context)
    if capacity_rows:
        sections.append(_workbook_section_from_rows("Press Capacity Rows", "Press Capacity", tuple(capacity_rows)))
    if not sections and photo_groups:
        sections.append(
            RecordWorkbookSection(
                "Photo References",
                tuple(
                    RecordWorkbookRow(
                        source=group.title,
                        label=photo.filename,
                        fields=_fields(
                            ("Category", photo.category),
                            ("Date Taken", photo.date_taken),
                            ("Association", photo.association),
                            ("Description", photo.description),
                            ("Path", photo.path),
                        ),
                    )
                    for group in photo_groups
                    for photo in group.photos
                ),
            )
        )
    return tuple(section for section in sections if section.rows)


def _record_match_context(
    record_type: str,
    record: EOATRecord | ToolRecord | MachineRecord,
    source_rows: tuple[dict[str, Any], ...],
) -> dict[str, set[str]]:
    context: dict[str, set[str]] = {"audits": set(), "eoats": set(), "tools": set(), "machines": set()}
    if record_type == ENTITY_EOAT and isinstance(record, EOATRecord):
        _add_context_value(context, "eoats", record.eoat_id, normalizer=normalized_eoat_key)
        for value in getattr(record, "audit_ids", ()) or ():
            _add_context_value(context, "audits", value)
        for value in getattr(record, "tools", ()) or ():
            _add_context_value(context, "tools", value, normalizer=normalized_tool_key)
        for value in getattr(record, "machines", ()) or ():
            _add_context_value(context, "machines", value, normalizer=normalized_machine_key)
    elif record_type == ENTITY_TOOL and isinstance(record, ToolRecord):
        _add_context_value(context, "tools", record.tool, normalizer=normalized_tool_key)
        for value in getattr(record, "compatible_eoats", ()) or ():
            _add_context_value(context, "eoats", value, normalizer=normalized_eoat_key)
        for value in getattr(record, "compatible_machines", ()) or ():
            _add_context_value(context, "machines", value, normalizer=normalized_machine_key)
    elif record_type == ENTITY_MACHINE and isinstance(record, MachineRecord):
        _add_context_value(context, "machines", record.machine, normalizer=normalized_machine_key)
        _add_context_value(context, "eoats", getattr(record, "current_eoat", ""), normalizer=normalized_eoat_key)
        for value in getattr(record, "compatible_eoats", ()) or ():
            _add_context_value(context, "eoats", value, normalizer=normalized_eoat_key)
        for value in getattr(record, "compatible_tools", ()) or ():
            _add_context_value(context, "tools", value, normalizer=normalized_tool_key)
    for row in source_rows:
        _add_row_context(context, row)
    return context


def _add_row_context(context: dict[str, set[str]], row: dict[str, Any]) -> None:
    for field_name in ("Audit ID", "Related Audit ID", "Source Audit ID", "Linked Audit Field"):
        _add_context_value(context, "audits", _row_lookup(row, field_name))
    for field_name in ("EOAT Assembly ID", "EOAT ID", "Related EOAT", "EOAT"):
        _add_context_value(context, "eoats", _row_lookup(row, field_name), normalizer=normalized_eoat_key)
    for field_name in ("Tool #", "Tool Number", "Tool No.", "Tool", "Mold #", "Mold Number", "NGW Part Number"):
        _add_context_value(context, "tools", _row_lookup(row, field_name), normalizer=normalized_tool_key)
    for field_name in ("Press/Machine #", "Machine #", "Machine No.", "Machine Number", "Press", "Related Cell/Press"):
        _add_context_value(context, "machines", _row_lookup(row, field_name), normalizer=normalized_machine_key)


def _add_context_value(context: dict[str, set[str]], key: str, value: Any, *, normalizer=None) -> None:
    text = display_value(value)
    if not text:
        return
    normalized = normalizer(text) if normalizer is not None else text.casefold()
    if normalized:
        context[key].add(normalized)


def _matching_sheet_rows(bundle: AtlasDataBundle, sheet_name: str, context: dict[str, set[str]]) -> list[dict[str, Any]]:
    with perf_timer(
        bundle.project_root,
        "record.workbook_matching_sheet_rows",
        details={"ui_sensitive": "excel_read", "sheet": sheet_name},
        source="atlas_record_details",
        page_tool="library_record",
    ):
        try:
            rows = row_dicts(resolve_project_paths(bundle.project_root).master_workbook, sheet_name)
        except Exception:
            return []
        return [dict(row) for row in rows if _row_matches_context(row, context)]


def _matching_press_capacity_rows(bundle: AtlasDataBundle, context: dict[str, set[str]]) -> list[dict[str, Any]]:
    with perf_timer(
        bundle.project_root,
        "record.press_capacity_relationship_lookup",
        details={"row_count": len(getattr(bundle, "press_capacity_rows", ()) or ())},
        source="atlas_record_details",
        page_tool="library_record",
    ):
        rows = []
        for row in getattr(bundle, "press_capacity_rows", ()) or ():
            if _row_matches_context(row, context):
                rows.append(dict(row))
        return rows


def _row_matches_context(row: dict[str, Any], context: dict[str, set[str]]) -> bool:
    row_context = {"audits": set(), "eoats": set(), "tools": set(), "machines": set()}
    _add_row_context(row_context, row)
    return any(row_context[key] & context.get(key, set()) for key in row_context)


def _workbook_section_from_rows(title: str, source: str, rows: tuple[dict[str, Any], ...]) -> RecordWorkbookSection:
    return RecordWorkbookSection(
        title=title,
        rows=tuple(
            RecordWorkbookRow(
                source=source,
                label=_source_row_label(row, index),
                fields=_row_fields(row),
            )
            for index, row in enumerate(rows, start=1)
            if _row_fields(row)
        ),
    )


def _source_row_label(row: dict[str, Any], index: int) -> str:
    for field_name in ("Audit ID", "Photo ID", "Issue ID", "Action ID", "Pilot ID", "FMEA ID", "Machine No.", "Press/Machine #", "Tool #"):
        value = _row_lookup(row, field_name)
        if display_value(value):
            return display_value(value)
    return f"Row {index}"


def _row_fields(row: dict[str, Any]) -> tuple[RecordField, ...]:
    fields = []
    for key, value in row.items():
        label = display_value(key)
        if not label or label.startswith("__"):
            continue
        text = display_value(value)
        if not text:
            continue
        fields.append(RecordField(label, text))
    return tuple(fields)


def _row_lookup(row: dict[str, Any], field_name: str) -> Any:
    wanted = field_name.casefold()
    for key, value in row.items():
        if str(key).casefold() == wanted:
            return value
    return ""


def _air_architecture(rows: tuple[dict[str, Any], ...], record: EOATRecord | None) -> str:
    return _first_row(rows, "Air Circuit Architecture") or (record.vacuum_info if record else "") or (record.pressure_info if record else "")


def _sensor_summary(rows: tuple[dict[str, Any], ...], record: EOATRecord | None) -> str:
    present = _first_row(rows, "Sensors?", "Sensors Present?")
    sensor_type = _first_row(rows, "Sensor Type") or (record.sensor_info if record else "")
    part_present = _first_row(rows, "Part Present Sensor?", "Part-Present Detection Present?")
    pieces = [piece for piece in (present, sensor_type, part_present) if piece]
    return " | ".join(pieces)


def _quick_disconnect_summary(rows: tuple[dict[str, Any], ...]) -> str:
    electrical = _first_row(rows, "Electrical Quick Disconnect Type")
    pneumatic = _first_row(rows, "Pneumatic Quick Disconnect Type")
    return " | ".join(piece for piece in (electrical, pneumatic) if piece)


def _external_circuit_summary(rows: tuple[dict[str, Any], ...]) -> str:
    return " | ".join(
        piece
        for piece in (
            _first_row(rows, "External Pressure Circuits"),
            _first_row(rows, "External Vacuum Circuits"),
            _first_row(rows, "External Interchangeable Circuits"),
        )
        if piece
    )


def _issue_summary(rows: tuple[dict[str, Any], ...], warnings: Iterable[WarningItem]) -> str:
    row_issue = _first_row(rows, "Known Issues / Observations", "Known Issues", "Drop/Mis-Pick History")
    if row_issue:
        return row_issue
    first_warning = next(iter(warnings or ()), None)
    return display_value(getattr(first_warning, "title", "")) if first_warning else ""


def _eoat_condition(bundle: AtlasDataBundle, record: EOATRecord) -> str:
    current_machine = _current_machine_for_eoat(bundle, record.eoat_id)
    if current_machine:
        return f"On Machine {current_machine}"
    blob = _rows_blob(tuple(getattr(record, "source_rows", ()) or ())).casefold()
    if "cabinet" in blob:
        return "In Cabinet"
    if "storage" in blob or "stored" in blob:
        return "In Storage"
    if "off-machine" in blob or "off machine" in blob or "bench audit" in blob:
        return "Off-Machine"
    if "not installed" in blob:
        return "Not Installed"
    first_machine = _first(tuple(getattr(record, "machines", ()) or ()))
    return f"On Machine {first_machine}" if first_machine else "Not Indexed"


def _current_machine_for_eoat(bundle: AtlasDataBundle, eoat_id: str) -> str:
    key = normalized_eoat_key(eoat_id)
    current = [machine.machine for machine in bundle.machines if normalized_eoat_key(getattr(machine, "current_eoat", "")) == key]
    return sorted(current, key=_machine_sort_key)[0] if current else ""


def _machine_current_fallback(record: MachineRecord) -> str:
    status = display_value(getattr(record, "current_eoat_status", ""))
    if status == "explicit_none":
        return "No Current EOAT"
    blob = _rows_blob(tuple(getattr(record, "source_rows", ()) or ())).casefold()
    if "no current eoat" in blob or "eoat not installed" in blob or "no eoat installed" in blob:
        return "No Current EOAT"
    return "Not Indexed"


def _current_tools_for_machine(bundle: AtlasDataBundle, record: MachineRecord) -> tuple[str, ...]:
    current_eoat = display_value(getattr(record, "current_eoat", ""))
    if current_eoat:
        eoat = _find_eoat(bundle, current_eoat)
        if eoat and getattr(eoat, "tools", ()):
            return tuple(eoat.tools)
    return tuple(getattr(record, "compatible_tools", ()) or ())


def _first_current_machine_for_tool(bundle: AtlasDataBundle, record: ToolRecord) -> str:
    eoat_keys = {normalized_eoat_key(value) for value in getattr(record, "compatible_eoats", ()) or ()}
    for machine in bundle.machines:
        if normalized_eoat_key(getattr(machine, "current_eoat", "")) in eoat_keys:
            return machine.machine
    return _first(tuple(getattr(record, "compatible_machines", ()) or ()))


def _first_current_eoat_for_tool(bundle: AtlasDataBundle, record: ToolRecord) -> str:
    machines = {normalized_machine_key(value) for value in getattr(record, "compatible_machines", ()) or ()}
    for machine in bundle.machines:
        if normalized_machine_key(machine.machine) in machines and display_value(getattr(machine, "current_eoat", "")):
            return machine.current_eoat
    return _first(tuple(getattr(record, "compatible_eoats", ()) or ()))


def _tool_rows(bundle: AtlasDataBundle, record: ToolRecord) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = list(getattr(record, "source_rows", ()) or ())
    key = normalized_tool_key(record.tool)
    for eoat in bundle.eoats:
        if any(normalized_tool_key(tool) == key for tool in getattr(eoat, "tools", ()) or ()):
            rows.extend(getattr(eoat, "source_rows", ()) or ())
    return tuple(_dedupe_rows(rows))


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[int] = set()
    deduped = []
    for row in rows:
        marker = id(row)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(row)
    return deduped


def _area_from_rows(rows: tuple[dict[str, Any], ...]) -> str:
    blob = _rows_blob(rows).casefold()
    if "plant 3" in blob:
        return "Plant 3"
    if "cleanroom" in blob:
        return "Cleanroom"
    if rows:
        return "Plant 4"
    return ""


def _rows_blob(rows: tuple[dict[str, Any], ...]) -> str:
    return " ".join(str(value) for row in rows if isinstance(row, dict) for value in row.values() if display_value(value))


def _photo_count(groups: tuple[RecordPhotoGroup, ...]) -> int:
    return sum(len(group.photos) for group in groups)


def _photo_folder(groups: tuple[RecordPhotoGroup, ...], fallback: str) -> str:
    for group in groups:
        for photo in group.photos:
            folder = display_value(photo.folder_path)
            if folder:
                return folder
            if photo.path:
                return str(Path(photo.path).parent)
    return display_value(fallback)


def _photo_association(photo: PhotoItem) -> str:
    pieces = []
    if photo.eoat_id:
        pieces.append(photo.eoat_id)
    if photo.tool:
        pieces.append(f"Tool {photo.tool}")
    if photo.machine:
        pieces.append(f"Machine {photo.machine}")
    if photo.part_name:
        pieces.append(photo.part_name)
    return " | ".join(pieces)


def _friendly_photo_group(value: str) -> str:
    text = display_value(value).replace("_", " ").replace("-", " ").strip()
    if not text:
        return "Other"
    lowered = text.casefold()
    if "cup" in lowered or "gripper" in lowered:
        return "Vacuum Cups / Grippers"
    if "tubing" in lowered:
        return "Tubing Routing"
    if "sensor" in lowered:
        return "Sensors"
    if "disconnect" in lowered or "qd" in lowered:
        return "Quick Disconnects"
    if "mount" in lowered:
        return "Mounting Hardware"
    if "cable" in lowered:
        return "Cable Management"
    if "wear" in lowered or "damage" in lowered:
        return "Wear / Damage"
    if "front" in lowered or "overall" in lowered:
        return "Overall / Front View"
    return text.title()


def _machine_sort_key(value: str) -> tuple[int, int | str]:
    text = str(value or "").strip()
    return (0, int(text)) if text.isdigit() else (1, text.casefold())


def _first(values: Iterable[str]) -> str:
    return next((display_value(value) for value in values if display_value(value)), "")


__all__ = [
    "ENTITY_EOAT",
    "ENTITY_MACHINE",
    "ENTITY_TOOL",
    "RecordDetailData",
    "RecordField",
    "RecordPhoto",
    "RecordPhotoGroup",
    "RecordSection",
    "RecordWorkbookRow",
    "RecordWorkbookSection",
    "build_record_detail_data",
    "get_photos_for_record",
]
