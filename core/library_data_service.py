from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any, Iterable

from .atlas_data_loader import load_atlas_data
from .atlas_models import (
    AtlasDataBundle,
    DocumentationStatus,
    EOATRecord,
    MachineRecord,
    PhotoItem,
    PhotoSet,
    ToolRecord,
    WarningItem,
)
from .atlas_record_details import (
    ENTITY_EOAT,
    ENTITY_MACHINE,
    ENTITY_TOOL,
    RecordDetailData,
    RecordField,
    RecordPhoto,
    RecordPhotoGroup,
    RecordSection,
)
from .atlas_utils import display_value, normalized_eoat_key, normalized_machine_key, normalized_tool_key
from .eoat_history import EOATHistoryService, EOATHistoryViewModel, configured_eoat_history_repository
from .paths import get_press_capacity_file, resolve_project_paths
from .performance import log_perf_marker, perf_timer
from .safe_files import ensure_directory


CACHE_VERSION = 3
INDEX_FILENAME = "library_index.json"
META_FILENAME = "library_index_meta.json"
NOT_INDEXED = "Not Indexed"
NO_CURRENT_EOAT = "No Current EOAT"
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}
LOGGER = logging.getLogger(__name__)

PHOTO_GROUP_ORDER = {
    "Overall / Front View": 0,
    "Side View": 1,
    "Vacuum Cups / Grippers": 2,
    "Tool Number": 3,
    "Mounting Hardware": 4,
    "Tubing / Air Routing": 5,
    "Sensors": 6,
    "Quick Disconnect": 7,
    "Cable Management": 8,
    "Wear / Damage": 9,
    "Other": 10,
}


class LibraryDataService:
    """Normalized, persistent Library index for fast UI navigation."""

    def __init__(self, project_root: str | Path | None = None, *, exclude_unaudited_tools: bool = True):
        self.exclude_unaudited_tools = exclude_unaudited_tools
        self._lock = threading.RLock()
        self._rebuild_thread: threading.Thread | None = None
        self._index: dict[str, Any] | None = None
        self._metadata: dict[str, Any] = {}
        self._stale = False
        self._generation = 0
        self.project_root: Path | None = None
        self.cache_path: Path | None = None
        self.meta_path: Path | None = None
        self.set_project_root(project_root)

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def stale(self) -> bool:
        return self._stale

    def set_project_root(self, project_root: str | Path | None) -> None:
        text = str(project_root or "").strip()
        if not text:
            self.project_root = None
            self.cache_path = None
            self.meta_path = None
            return
        root = Path(text)
        self.project_root = root
        cache_dir = resolve_project_paths(root).cache
        self.cache_path = cache_dir / INDEX_FILENAME
        self.meta_path = cache_dir / META_FILENAME

    def get_eoat_history(self, eoat_id: str) -> EOATHistoryViewModel:
        """Load documented lifecycle events through the configured history provider."""
        root = self._root()
        if root is None:
            return EOATHistoryViewModel(str(eoat_id or ""), (), (), ())
        service = EOATHistoryService(configured_eoat_history_repository(root))
        return service.history_for(eoat_id)

    def load_cached_index(self) -> None:
        root = self._root()
        if root is None or self.cache_path is None or self.meta_path is None:
            return
        with perf_timer(
            root,
            "library.cache.load",
            details={"cache_path": str(self.cache_path), "meta_path": str(self.meta_path)},
            source="library_data_service",
            page_tool="library",
        ):
            if not self.cache_path.exists() or not self.meta_path.exists():
                log_perf_marker(
                    root,
                    "library.cache.missing",
                    details={"cache_path": str(self.cache_path)},
                    source="library_data_service",
                    page_tool="library",
                )
                self.rebuild_index_in_background()
                return
            try:
                with self.cache_path.open("r", encoding="utf-8") as handle:
                    index = json.load(handle)
                with self.meta_path.open("r", encoding="utf-8") as handle:
                    metadata = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                log_perf_marker(
                    root,
                    "library.cache.load_failed",
                    details={"error": f"{type(exc).__name__}: {exc}"},
                    source="library_data_service",
                    page_tool="library",
                )
                self.rebuild_index_in_background()
                return
            if int(index.get("cache_version", 0) or 0) != CACHE_VERSION:
                self.rebuild_index_in_background()
            with self._lock:
                self._index = index
                self._metadata = metadata
                self._generation += 1
            self._stale = self._is_stale(metadata)
            if self._stale:
                log_perf_marker(
                    root,
                    "library.cache.stale",
                    details={"reason": "source workbook metadata changed; old cache remains usable"},
                    source="library_data_service",
                    page_tool="library",
                )
                self.rebuild_index_in_background()

    def rebuild_index(self) -> None:
        root = self._root()
        if root is None:
            return
        with perf_timer(
            root,
            "library.cache.rebuild",
            details={"cache_version": CACHE_VERSION},
            source="library_data_service",
            page_tool="library_index",
        ):
            with perf_timer(
                root,
                "library.index.parse_master_tracker",
                details={"ui_sensitive": "excel_read", "background_rebuild": threading.current_thread() is not threading.main_thread()},
                source="library_data_service",
                page_tool="library_index",
            ):
                bundle = load_atlas_data(
                    root,
                    force_refresh=True,
                    exclude_unaudited_tools=self.exclude_unaudited_tools,
                )
            self.rebuild_index_from_bundle(bundle)

    def rebuild_index_in_background(self) -> None:
        root = self._root()
        if root is None:
            return
        if self._rebuild_thread is not None and self._rebuild_thread.is_alive():
            return

        def _run() -> None:
            try:
                self.rebuild_index()
            except Exception as exc:
                log_perf_marker(
                    root,
                    "library.cache.rebuild_failed",
                    details={"error": f"{type(exc).__name__}: {exc}"},
                    source="library_data_service",
                    page_tool="library_index",
                )

        self._rebuild_thread = threading.Thread(target=_run, name="LibraryIndexRebuild", daemon=True)
        self._rebuild_thread.start()

    def rebuild_index_from_bundle(self, bundle: AtlasDataBundle) -> None:
        self.set_project_root(getattr(bundle, "project_root", "") or self.project_root)
        root = self._root()
        if root is None:
            return
        with perf_timer(
            root,
            "library.cache.rebuild",
            details={"cache_version": CACHE_VERSION, "source": "atlas_data_bundle"},
            source="library_data_service",
            page_tool="library_index",
        ):
            with perf_timer(
                root,
                "library.index.parse_press_capacity",
                details={"press_capacity_rows": len(getattr(bundle, "press_capacity_rows", ()) or ())},
                source="library_data_service",
                page_tool="library_index",
            ):
                press_capacity_rows = tuple(getattr(bundle, "press_capacity_rows", ()) or ())
            with perf_timer(
                root,
                "library.index.build_relationship_maps",
                details={
                    "eoats": len(getattr(bundle, "eoats", ()) or ()),
                    "tools": len(getattr(bundle, "tools", ()) or ()),
                    "machines": len(getattr(bundle, "machines", ()) or ()),
                },
                source="library_data_service",
                page_tool="library_index",
            ):
                relationships = self._build_relationship_maps(bundle)
            with perf_timer(
                root,
                "library.index.build_photo_maps",
                details={"eoats": len(getattr(bundle, "eoats", ()) or ())},
                source="library_data_service",
                page_tool="library_index",
            ):
                photos = self._build_photo_maps(bundle)
            with perf_timer(
                root,
                "library.index.compute_documentation",
                details={"record_groups": 3},
                source="library_data_service",
                page_tool="library_index",
            ):
                documentation = self._build_documentation_maps(bundle, photos)
            with perf_timer(
                root,
                "library.index.parse_master_tracker",
                details={"source": "atlas_data_bundle", "workbook_read": False},
                source="library_data_service",
                page_tool="library_index",
            ):
                records, order = self._build_record_maps(bundle, relationships, photos, documentation)
            metadata = {
                "cache_version": CACHE_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source_files": self._source_signature(),
                "press_capacity_rows": len(press_capacity_rows),
                "record_counts": {record_type: len(values) for record_type, values in records.items()},
            }
            index = {
                "cache_version": CACHE_VERSION,
                "created_at": metadata["created_at"],
                "records": records,
                "order": order,
                "relationships": relationships,
                "photos": photos,
                "documentation": documentation,
                "metadata": metadata,
            }
            self._write_cache(index, metadata)
            with self._lock:
                self._index = index
                self._metadata = metadata
                self._stale = False
                self._generation += 1

    def is_index_ready(self) -> bool:
        with self._lock:
            records = (self._index or {}).get("records", {})
            return any(records.get(record_type) for record_type in (ENTITY_EOAT, ENTITY_TOOL, ENTITY_MACHINE))

    def get_eoats(self) -> list[dict[str, Any]]:
        return self._records_for(ENTITY_EOAT)

    def get_tools(self) -> list[dict[str, Any]]:
        return self._records_for(ENTITY_TOOL)

    def get_machines(self) -> list[dict[str, Any]]:
        return self._records_for(ENTITY_MACHINE)

    def get_eoat_records(self) -> list[EOATRecord]:
        return [self.to_eoat_record(record) for record in self.get_eoats()]

    def get_tool_records(self) -> list[ToolRecord]:
        return [self.to_tool_record(record) for record in self.get_tools()]

    def get_machine_records(self) -> list[MachineRecord]:
        return [self.to_machine_record(record) for record in self.get_machines()]

    def get_record(self, record_type: str, record_id: str) -> dict[str, Any] | None:
        root = self._root_text()
        normalized_type = self._record_type(record_type)
        with perf_timer(
            root,
            "library.data_service.get_record",
            details={"record_type": normalized_type, "record_id": record_id},
            source="library_data_service",
            page_tool="library_record",
        ):
            return self.peek_record(normalized_type, record_id)

    def peek_record(self, record_type: str, record_id: str) -> dict[str, Any] | None:
        normalized_type = self._record_type(record_type)
        index = self._snapshot()
        key = self._record_key(normalized_type, record_id)
        return dict(index.get("records", {}).get(normalized_type, {}).get(key) or {}) or None

    def get_relationships(self, record_type: str, record_id: str) -> dict[str, Any]:
        root = self._root_text()
        normalized_type = self._record_type(record_type)
        with perf_timer(
            root,
            "library.data_service.get_relationships",
            details={"record_type": normalized_type, "record_id": record_id},
            source="library_data_service",
            page_tool="library_record",
        ):
            return self.peek_relationships(normalized_type, record_id)

    def peek_relationships(self, record_type: str, record_id: str) -> dict[str, Any]:
        normalized_type = self._record_type(record_type)
        relationships = self._snapshot().get("relationships", {})
        key = self._record_key(normalized_type, record_id)
        if normalized_type == ENTITY_EOAT:
            return {
                "machines": list(relationships.get("eoat_to_machines", {}).get(key, ())),
                "tools": list(relationships.get("eoat_to_tools", {}).get(key, ())),
                "current_machines": list(relationships.get("eoat_current_machines", {}).get(key, ())),
                "condition_location": relationships.get("eoat_current_location", {}).get(key, NOT_INDEXED),
            }
        if normalized_type == ENTITY_TOOL:
            return {
                "eoats": list(relationships.get("tool_to_eoats", {}).get(key, ())),
                "machines": list(relationships.get("tool_to_machines", {}).get(key, ())),
            }
        if normalized_type == ENTITY_MACHINE:
            return {
                "eoats": list(relationships.get("machine_to_eoats", {}).get(key, ())),
                "tools": list(relationships.get("machine_to_tools", {}).get(key, ())),
                "current_eoat": relationships.get("machine_current_eoat", {}).get(key, NOT_INDEXED),
            }
        return {}

    def get_photos(self, record_type: str, record_id: str) -> list[dict[str, Any]]:
        root = self._root_text()
        normalized_type = self._record_type(record_type)
        with perf_timer(
            root,
            "library.data_service.get_photos",
            details={"record_type": normalized_type, "record_id": record_id},
            source="library_data_service",
            page_tool="library_record",
        ):
            return self.peek_photos(normalized_type, record_id)

    def peek_photos(self, record_type: str, record_id: str) -> list[dict[str, Any]]:
        normalized_type = self._record_type(record_type)
        photos = self._snapshot().get("photos", {})
        key = self._record_key(normalized_type, record_id)
        map_name = {"eoat": "by_eoat", "tool": "by_tool", "machine": "by_machine"}.get(normalized_type, "")
        return [dict(photo) for photo in photos.get(map_name, {}).get(key, ())]

    def get_documentation_status(self, record_type: str, record_id: str) -> dict[str, Any]:
        root = self._root_text()
        normalized_type = self._record_type(record_type)
        with perf_timer(
            root,
            "library.data_service.get_documentation_status",
            details={"record_type": normalized_type, "record_id": record_id},
            source="library_data_service",
            page_tool="library_record",
        ):
            return self.peek_documentation_status(normalized_type, record_id)

    def peek_documentation_status(self, record_type: str, record_id: str) -> dict[str, Any]:
        normalized_type = self._record_type(record_type)
        key = self._record_key(normalized_type, record_id)
        docs = self._snapshot().get("documentation", {}).get(normalized_type, {})
        return dict(docs.get(key) or {})

    def search(self, query: str, filters: dict, sort: str, page: int, page_size: int):
        root = self._root_text()
        with perf_timer(
            root,
            "library.data_service.search",
            details={"query": query, "sort": sort, "page": page, "page_size": page_size},
            source="library_data_service",
            page_tool="library",
        ):
            records = [*self.get_eoats(), *self.get_tools(), *self.get_machines()]
            folded = str(query or "").strip().casefold()
            type_filter = str((filters or {}).get("type", "all") or "all").casefold()
            if folded:
                tokens = folded.split()
                records = [record for record in records if all(token in str(record.get("search_text", "")).casefold() for token in tokens)]
            if type_filter not in {"", "all"}:
                records = [record for record in records if str(record.get("record_type", "")).casefold() == type_filter]
            records = self._sort_records(records, sort)
            total = len(records)
            page_size = max(1, int(page_size or 50))
            page = max(1, int(page or 1))
            start = (page - 1) * page_size
            return {"total": total, "page": page, "page_size": page_size, "items": records[start : start + page_size]}

    def get_record_detail_data(self, record_type: str, record_id: str) -> RecordDetailData:
        normalized_type = self._record_type(record_type)
        record = self.peek_record(normalized_type, record_id)
        if record is None:
            raise ValueError(f"{normalized_type.title()} record not found: {record_id}")
        relationships = self.peek_relationships(normalized_type, record_id)
        photos = self.peek_photos(normalized_type, record_id)
        documentation = self.peek_documentation_status(normalized_type, record_id)
        if normalized_type == ENTITY_EOAT:
            return self._eoat_detail(record, relationships, photos, documentation)
        if normalized_type == ENTITY_TOOL:
            return self._tool_detail(record, relationships, photos, documentation)
        if normalized_type == ENTITY_MACHINE:
            return self._machine_detail(record, relationships, photos, documentation)
        raise ValueError(f"Unsupported record type: {record_type}")

    def to_eoat_record(self, record: dict[str, Any]) -> EOATRecord:
        docs = _documentation_from_cache(record.get("documentation") or {})
        photos = tuple(_photo_item_from_cache(photo) for photo in self._photos_for_cached_record(record))
        return EOATRecord(
            eoat_id=_text(record.get("eoat_id")),
            display_id=_text(record.get("display_name") or record.get("eoat_id")),
            audit_ids=_tuple(record.get("audit_ids")),
            tools=_tuple(record.get("tool_numbers")),
            molds=_tuple(record.get("molds")),
            parts=_tuple(record.get("parts")),
            machines=_tuple(record.get("machine_numbers")),
            part_family=_text(record.get("part_family")),
            part_description=_text(record.get("part_name_description")),
            eoat_type=_text(record.get("eoat_type")),
            status=_text(record.get("status_lifecycle")),
            robot_types=_tuple(record.get("robot_types")),
            robot_models=_tuple(record.get("robot_models")),
            connection_type=_text(record.get("connection_type")),
            vacuum_info=_text(record.get("vacuum_info")),
            pressure_info=_text(record.get("pressure_info")),
            gripper_info=_text(record.get("gripper_info")),
            sensor_info=_text(record.get("sensors_summary")),
            tubing_notes=_text(record.get("tubing_notes")),
            install_notes=_text(record.get("install_notes")),
            known_issues=_text(record.get("known_issues")),
            documentation=docs,
            photos=PhotoSet(eoat_id=_text(record.get("eoat_id")), indexed_photos=photos),
            warnings=tuple(_warning_from_cache(item) for item in record.get("warnings", ()) or ()),
        )

    def to_tool_record(self, record: dict[str, Any]) -> ToolRecord:
        return ToolRecord(
            tool=_text(record.get("tool_number")),
            label=_text(record.get("display_name") or record.get("tool_number")),
            molds=_tuple(record.get("molds")),
            parts=_tuple(record.get("parts")),
            part_family=_text(record.get("part_family")),
            part_description=_text(record.get("part_name_description")),
            compatible_eoats=_tuple(record.get("compatible_eoats")),
            compatible_machines=_tuple(record.get("compatible_machines")),
            source=_text(record.get("source")),
            warnings=tuple(_warning_from_cache(item) for item in record.get("warnings", ()) or ()),
        )

    def to_machine_record(self, record: dict[str, Any]) -> MachineRecord:
        current = _text(record.get("current_eoat_id"))
        if current in {NOT_INDEXED, NO_CURRENT_EOAT}:
            current = ""
        return MachineRecord(
            machine=_text(record.get("machine_number")),
            label=_text(record.get("display_name") or f"Machine {_text(record.get('machine_number'))}"),
            robot_type=_text(record.get("robot_type")),
            robot_model=_text(record.get("robot_model_controller")),
            controller=_text(record.get("controller")),
            compatible_eoats=_tuple(record.get("compatible_eoats")),
            compatible_tools=_tuple(record.get("compatible_tools")),
            compatible_parts=_tuple(record.get("compatible_parts")),
            current_eoat=current,
            current_eoat_status=_text(record.get("current_eoat_status")),
            current_eoat_source=_text(record.get("current_eoat_source")),
            current_eoat_confidence=_text(record.get("current_eoat_confidence")),
            current_eoat_resolution_reason=_text(record.get("current_eoat_resolution_reason")),
            documentation_score=int(record.get("documentation_score") or 0),
            warnings=tuple(_warning_from_cache(item) for item in record.get("warnings", ()) or ()),
        )

    def _root(self) -> Path | None:
        return self.project_root

    def _root_text(self) -> str:
        return str(self.project_root or "")

    def _snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._index or {}

    def _records_for(self, record_type: str) -> list[dict[str, Any]]:
        normalized_type = self._record_type(record_type)
        index = self._snapshot()
        records = index.get("records", {}).get(normalized_type, {})
        order = index.get("order", {}).get(normalized_type, ())
        return [dict(records[key]) for key in order if key in records]

    def _record_type(self, record_type: str) -> str:
        normalized = str(record_type or "").casefold()
        if normalized in {ENTITY_EOAT, ENTITY_TOOL, ENTITY_MACHINE}:
            return normalized
        return normalized

    def _record_key(self, record_type: str, record_id: str) -> str:
        if record_type == ENTITY_EOAT:
            return normalized_eoat_key(record_id)
        if record_type == ENTITY_TOOL:
            return normalized_tool_key(record_id)
        if record_type == ENTITY_MACHINE:
            return normalized_machine_key(record_id)
        return str(record_id or "").casefold()

    def _write_cache(self, index: dict[str, Any], metadata: dict[str, Any]) -> None:
        if self.cache_path is None or self.meta_path is None:
            return
        ensure_directory(self.cache_path.parent)
        with self.cache_path.open("w", encoding="utf-8") as handle:
            json.dump(index, handle, ensure_ascii=True, indent=2, sort_keys=True)
        with self.meta_path.open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, ensure_ascii=True, indent=2, sort_keys=True)

    def _source_signature(self) -> dict[str, Any]:
        root = self._root()
        if root is None:
            return {}
        paths = resolve_project_paths(root)
        return {
            "source_workbook": _file_signature(paths.master_workbook),
            "press_capacity": _file_signature(get_press_capacity_file(root)),
        }

    def _is_stale(self, metadata: dict[str, Any]) -> bool:
        root = self._root()
        if root is None:
            return False
        with perf_timer(
            root,
            "library.cache.stale_check",
            details={"cache_version": metadata.get("cache_version"), "expected_cache_version": CACHE_VERSION},
            source="library_data_service",
            page_tool="library",
        ):
            if int(metadata.get("cache_version", 0) or 0) != CACHE_VERSION:
                return True
            return metadata.get("source_files") != self._source_signature()

    def _build_relationship_maps(self, bundle: AtlasDataBundle) -> dict[str, Any]:
        eoat_to_machines: dict[str, list[str]] = {}
        eoat_to_tools: dict[str, list[str]] = {}
        tool_to_eoats: dict[str, list[str]] = {}
        tool_to_machines: dict[str, list[str]] = {}
        machine_to_eoats: dict[str, list[str]] = {}
        machine_to_tools: dict[str, list[str]] = {}
        machine_current_eoat: dict[str, str] = {}
        eoat_current_location: dict[str, str] = {}
        eoat_current_machines: dict[str, list[str]] = defaultdict(list)

        for eoat in getattr(bundle, "eoats", ()) or ():
            eoat_key = normalized_eoat_key(eoat.eoat_id)
            eoat_to_machines[eoat_key] = list(_sort_machines(getattr(eoat, "machines", ()) or ()))
            eoat_to_tools[eoat_key] = sorted(_tuple(getattr(eoat, "tools", ())), key=str.casefold)
        for tool in getattr(bundle, "tools", ()) or ():
            tool_key = normalized_tool_key(tool.tool)
            tool_to_eoats[tool_key] = sorted(_tuple(getattr(tool, "compatible_eoats", ())), key=str.casefold)
            tool_to_machines[tool_key] = list(_sort_machines(getattr(tool, "compatible_machines", ()) or ()))
        for machine in getattr(bundle, "machines", ()) or ():
            machine_key = normalized_machine_key(machine.machine)
            machine_to_eoats[machine_key] = sorted(_tuple(getattr(machine, "compatible_eoats", ())), key=str.casefold)
            machine_to_tools[machine_key] = sorted(_tuple(getattr(machine, "compatible_tools", ())), key=str.casefold)
            current = display_value(getattr(machine, "current_eoat", ""))
            if current:
                machine_current_eoat[machine_key] = current
                eoat_current_machines[normalized_eoat_key(current)].append(machine.machine)
            elif display_value(getattr(machine, "current_eoat_status", "")) == "explicit_none":
                machine_current_eoat[machine_key] = NO_CURRENT_EOAT
            else:
                machine_current_eoat[machine_key] = NOT_INDEXED

        for eoat in getattr(bundle, "eoats", ()) or ():
            eoat_key = normalized_eoat_key(eoat.eoat_id)
            current_machines = tuple(_sort_machines(eoat_current_machines.get(eoat_key, ())))
            if current_machines:
                eoat_current_location[eoat_key] = f"On Machine {current_machines[0]}"
            else:
                eoat_current_location[eoat_key] = _eoat_condition_from_rows(eoat) or NOT_INDEXED
        return {
            "eoat_to_machines": eoat_to_machines,
            "eoat_to_tools": eoat_to_tools,
            "tool_to_eoats": tool_to_eoats,
            "tool_to_machines": tool_to_machines,
            "machine_to_eoats": machine_to_eoats,
            "machine_to_tools": machine_to_tools,
            "machine_current_eoat": machine_current_eoat,
            "eoat_current_location": eoat_current_location,
            "eoat_current_machines": {key: list(_sort_machines(values)) for key, values in eoat_current_machines.items()},
        }

    def _build_photo_maps(self, bundle: AtlasDataBundle) -> dict[str, Any]:
        by_eoat: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_tool: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_machine: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_audit_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
        seen: dict[str, dict[str, int]] = {"eoat": {}, "tool": {}, "machine": {}, "audit": {}}

        def add(map_name: str, mapping: dict[str, list[dict[str, Any]]], key: str, photo: dict[str, Any]) -> None:
            normalized = str(key or "").strip()
            if not normalized:
                return
            fingerprint = f"{map_name}|{normalized}|{photo.get('photo_id')}|{photo.get('stored_filename')}|{photo.get('photo_filename')}|{photo.get('path')}"
            existing_index = seen[map_name].get(fingerprint)
            if existing_index is not None:
                mapping[normalized][existing_index] = _preferred_photo_record(
                    mapping[normalized][existing_index],
                    photo,
                    record_type=map_name,
                    record_id=normalized,
                )
                return
            seen[map_name][fingerprint] = len(mapping[normalized])
            mapping[normalized].append(photo)

        for eoat in getattr(bundle, "eoats", ()) or ():
            eoat_key = normalized_eoat_key(eoat.eoat_id)
            owner_tools = tuple(getattr(eoat, "tools", ()) or ())
            owner_machines = tuple(getattr(eoat, "machines", ()) or ())
            photo_set = getattr(eoat, "photos", None)
            source_photos = ()
            if photo_set is not None:
                source_photos = tuple(getattr(photo_set, "photos", ()) or ()) + tuple(getattr(photo_set, "indexed_photos", ()) or ())
            for item in source_photos:
                photo = _photo_record(item, root=self._root(), owner_eoat=eoat.eoat_id)
                add("eoat", by_eoat, eoat_key, photo)
                for audit_id in _tuple((item.related_audit_id, *getattr(eoat, "audit_ids", ()))):
                    add("audit", by_audit_id, audit_id.casefold(), photo)
                for tool in (*owner_tools, item.tool):
                    add("tool", by_tool, normalized_tool_key(tool), photo)
                for machine in (*owner_machines, item.machine):
                    add("machine", by_machine, normalized_machine_key(machine), photo)

        for tool_key, paths in getattr(getattr(bundle, "indexes", None), "photos_by_tool", {}).items():
            for path in paths or ():
                photo = _photo_record(PhotoItem(path=path, filename=Path(path).name, tool=tool_key, source="tool photo index"), root=self._root())
                add("tool", by_tool, normalized_tool_key(tool_key), photo)

        sort_key = lambda item: (_text(item.get("date_taken")), _text(item.get("photo_id")), _text(item.get("filename")))
        return {
            "by_eoat": {key: sorted(values, key=sort_key) for key, values in by_eoat.items()},
            "by_tool": {key: sorted(values, key=sort_key) for key, values in by_tool.items()},
            "by_machine": {key: sorted(values, key=sort_key) for key, values in by_machine.items()},
            "by_audit_id": {key: sorted(values, key=sort_key) for key, values in by_audit_id.items()},
        }

    def _build_documentation_maps(self, bundle: AtlasDataBundle, photos: dict[str, Any]) -> dict[str, Any]:
        eoat_docs: dict[str, dict[str, Any]] = {}
        tool_docs: dict[str, dict[str, Any]] = {}
        machine_docs: dict[str, dict[str, Any]] = {}
        for record in getattr(bundle, "eoats", ()) or ():
            key = normalized_eoat_key(record.eoat_id)
            docs = getattr(record, "documentation", DocumentationStatus())
            photo_count = len(photos.get("by_eoat", {}).get(key, ()))
            eoat_docs[key] = _documentation_record(docs.score, docs.missing_fields, photo_count, docs.status_label)
        for record in getattr(bundle, "tools", ()) or ():
            key = normalized_tool_key(record.tool)
            missing = ("Review warnings",) if getattr(record, "warning_count", 0) else ()
            score = 68 if missing else 100
            photo_count = len(photos.get("by_tool", {}).get(key, ()))
            tool_docs[key] = _documentation_record(score, missing, photo_count, "Needs Review" if missing else "Good")
        for record in getattr(bundle, "machines", ()) or ():
            key = normalized_machine_key(record.machine)
            score = int(getattr(record, "documentation_score", 0) or 0)
            missing = ("Machine documentation incomplete",) if score < 75 else ()
            photo_count = len(photos.get("by_machine", {}).get(key, ()))
            machine_docs[key] = _documentation_record(score, missing, photo_count, "Needs Review" if missing else "Good")
        return {ENTITY_EOAT: eoat_docs, ENTITY_TOOL: tool_docs, ENTITY_MACHINE: machine_docs}

    def _build_record_maps(
        self,
        bundle: AtlasDataBundle,
        relationships: dict[str, Any],
        photos: dict[str, Any],
        documentation: dict[str, Any],
    ) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, list[str]]]:
        records: dict[str, dict[str, dict[str, Any]]] = {ENTITY_EOAT: {}, ENTITY_TOOL: {}, ENTITY_MACHINE: {}}
        order: dict[str, list[str]] = {ENTITY_EOAT: [], ENTITY_TOOL: [], ENTITY_MACHINE: []}
        for record in getattr(bundle, "eoats", ()) or ():
            key = normalized_eoat_key(record.eoat_id)
            doc = documentation[ENTITY_EOAT].get(key, _documentation_record(0, (), 0, "Unknown"))
            eoat_photos = photos.get("by_eoat", {}).get(key, ())
            photo_count = len(eoat_photos)
            preview = _preview_cache_fields(_select_preview_photo(eoat_photos, record_type=ENTITY_EOAT, record_id=record.eoat_id))
            row_values = tuple(getattr(record, "source_rows", ()) or ())
            current_machines = relationships.get("eoat_current_machines", {}).get(key, ())
            current_machine = current_machines[0] if current_machines else NOT_INDEXED
            normalized = {
                "record_type": ENTITY_EOAT,
                "eoat_id": record.eoat_id,
                "display_name": record.display_id or record.eoat_id,
                "audit_ids": list(_tuple(getattr(record, "audit_ids", ()))),
                "eoat_type": _text(record.eoat_type) or NOT_INDEXED,
                "condition_location": relationships.get("eoat_current_location", {}).get(key, NOT_INDEXED),
                "current_machine": current_machine,
                "plant_area": _first_row(row_values, "Plant/Area", "Plant", "Area") or _area_from_rows(row_values),
                "tool_numbers": list(_tuple(getattr(record, "tools", ()))),
                "machine_numbers": list(_tuple(getattr(record, "machines", ()))),
                "molds": list(_tuple(getattr(record, "molds", ()))),
                "parts": list(_tuple(getattr(record, "parts", ()))),
                "part_family": _text(record.part_family) or NOT_INDEXED,
                "part_name_description": _text(record.part_description) or NOT_INDEXED,
                "connection_type": _text(record.connection_type) or NOT_INDEXED,
                "parts_picked": _first_row(row_values, "Number of Parts Picked", "# Parts Picked") or NOT_INDEXED,
                "air_architecture": _first_row(row_values, "Air Circuit Architecture") or _air_summary(record),
                "sensors_summary": _text(record.sensor_info) or _first_row(row_values, "Sensor Type", "Sensors?") or NOT_INDEXED,
                "photo_count": photo_count,
                **preview,
                "last_audit_date": _last_audit(row_values),
                "documentation_score": doc["documentation_score"],
                "documentation": doc,
                "status_lifecycle": _text(record.status) or NOT_INDEXED,
                "robot_types": list(_tuple(getattr(record, "robot_types", ()))),
                "robot_models": list(_tuple(getattr(record, "robot_models", ()))),
                "vacuum_info": _text(record.vacuum_info),
                "pressure_info": _text(record.pressure_info),
                "gripper_info": _text(record.gripper_info),
                "tubing_notes": _text(record.tubing_notes),
                "install_notes": _text(record.install_notes),
                "known_issues": _text(record.known_issues),
                "warnings": [_warning_dict(warning) for warning in getattr(record, "warnings", ()) or ()],
            }
            normalized["search_text"] = _search_text(normalized)
            records[ENTITY_EOAT][key] = normalized
            order[ENTITY_EOAT].append(key)

        for record in getattr(bundle, "tools", ()) or ():
            key = normalized_tool_key(record.tool)
            doc = documentation[ENTITY_TOOL].get(key, _documentation_record(0, (), 0, "Unknown"))
            row_values = tuple(getattr(record, "source_rows", ()) or ())
            machines = relationships.get("tool_to_machines", {}).get(key, ())
            tool_photos = photos.get("by_tool", {}).get(key, ())
            preview = _preview_cache_fields(
                _select_preview_photo(
                    tool_photos,
                    record_type=ENTITY_TOOL,
                    record_id=record.tool,
                    related_eoats=getattr(record, "compatible_eoats", ()) or (),
                )
            )
            normalized = {
                "record_type": ENTITY_TOOL,
                "tool_number": record.tool,
                "display_name": record.label or record.tool,
                "molds": list(_tuple(getattr(record, "molds", ()))),
                "parts": list(_tuple(getattr(record, "parts", ()))),
                "part_family": _text(record.part_family) or NOT_INDEXED,
                "part_name_description": _text(record.part_description) or NOT_INDEXED,
                "compatible_eoats": list(_tuple(getattr(record, "compatible_eoats", ()))),
                "compatible_machines": list(_sort_machines(getattr(record, "compatible_machines", ()) or ())),
                "current_machine": machines[0] if machines else NOT_INDEXED,
                "plant_area": _first_row(row_values, "Plant/Area", "Plant", "Area") or _area_from_rows(row_values),
                "parts_picked": _first_row(row_values, "Number of Parts Picked", "# Parts Picked") or NOT_INDEXED,
                "status_lifecycle": "Needs Review" if getattr(record, "warning_count", 0) else "In Service",
                "photo_count": len(tool_photos),
                **preview,
                "documentation_score": doc["documentation_score"],
                "documentation": doc,
                "last_audit_date": _last_audit(row_values),
                "source": _text(record.source),
                "warnings": [_warning_dict(warning) for warning in getattr(record, "warnings", ()) or ()],
            }
            normalized["search_text"] = _search_text(normalized)
            records[ENTITY_TOOL][key] = normalized
            order[ENTITY_TOOL].append(key)

        for record in getattr(bundle, "machines", ()) or ():
            key = normalized_machine_key(record.machine)
            doc = documentation[ENTITY_MACHINE].get(key, _documentation_record(0, (), 0, "Unknown"))
            row_values = tuple(getattr(record, "source_rows", ()) or ())
            current_display = relationships.get("machine_current_eoat", {}).get(key, NOT_INDEXED)
            current_id = _text(record.current_eoat) or current_display
            normalized = {
                "record_type": ENTITY_MACHINE,
                "machine_number": record.machine,
                "display_name": record.label or f"Machine {record.machine}",
                "robot_type": _text(record.robot_type) or NOT_INDEXED,
                "robot_model_controller": _text(record.robot_model or record.controller) or NOT_INDEXED,
                "controller": _text(record.controller),
                "area": _first_row(row_values, "Cleanroom/Non-Cleanroom", "Area") or ("Cleanroom" if "cleanroom" in _rows_blob(row_values) else "Production"),
                "plant_area": _first_row(row_values, "Plant/Area", "Plant", "Area") or _area_from_rows(row_values),
                "current_eoat_id": current_id,
                "current_eoat_status": _text(record.current_eoat_status),
                "current_eoat_source": _text(record.current_eoat_source),
                "current_eoat_confidence": _text(record.current_eoat_confidence),
                "current_eoat_resolution_reason": _text(record.current_eoat_resolution_reason),
                "compatible_eoats": list(_tuple(getattr(record, "compatible_eoats", ()))),
                "compatible_tools": list(_tuple(getattr(record, "compatible_tools", ()))),
                "compatible_parts": list(_tuple(getattr(record, "compatible_parts", ()))),
                "air_architecture": _first_row(row_values, "Air Circuit Architecture") or NOT_INDEXED,
                "external_pressure_circuits": _first_row(row_values, "External Pressure Circuits") or NOT_INDEXED,
                "external_vacuum_circuits": _first_row(row_values, "External Vacuum Circuits") or NOT_INDEXED,
                "status_lifecycle": "In Service" if current_display not in {NOT_INDEXED, NO_CURRENT_EOAT} else current_display,
                "last_audit_date": _last_audit(row_values),
                "documentation_score": doc["documentation_score"],
                "documentation": doc,
                "photo_count": len(photos.get("by_machine", {}).get(key, ())),
                "preview_photo_id": "",
                "preview_photo_path_candidates": [],
                "preview_photo_type": "",
                "warnings": [_warning_dict(warning) for warning in getattr(record, "warnings", ()) or ()],
            }
            normalized["search_text"] = _search_text(normalized)
            records[ENTITY_MACHINE][key] = normalized
            order[ENTITY_MACHINE].append(key)
        return records, order

    def _photos_for_cached_record(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        record_type = _text(record.get("record_type"))
        record_id = _text(record.get("eoat_id") or record.get("tool_number") or record.get("machine_number"))
        return self.peek_photos(record_type, record_id)

    def _photo_groups(self, photos: list[dict[str, Any]], default_association: str, record_type: str, record_id: str) -> tuple[RecordPhotoGroup, ...]:
        groups: dict[str, list[RecordPhoto]] = defaultdict(list)
        for photo in _dedupe_photo_records(photos, record_type=record_type, record_id=record_id):
            category = _text(photo.get("photo_type") or photo.get("area_shown") or photo.get("category")) or "Other"
            title = _friendly_photo_group(category)
            candidates = tuple(_tuple(photo.get("resolved_path_candidates")))
            path = candidates[0] if candidates else _text(photo.get("path"))
            groups[title].append(
                RecordPhoto(
                    path=path,
                    filename=_text(photo.get("photo_filename") or photo.get("stored_filename") or photo.get("filename") or Path(path).name),
                    category=category,
                    photo_id=_text(photo.get("photo_id")),
                    date_taken=_text(photo.get("date_taken")),
                    association=_photo_association(photo) or default_association,
                    description=_text(photo.get("description")),
                    source=_text(photo.get("source")),
                    folder_path=_text(photo.get("folder_path")),
                    stored_relative_path=_text(photo.get("stored_relative_path")),
                    stored_filename=_text(photo.get("stored_filename")),
                    photo_filename=_text(photo.get("photo_filename")),
                    original_filename=_text(photo.get("original_filename")),
                    eoat_id=_text(photo.get("eoat_id")),
                    tool=_text(photo.get("tool_number")),
                    machine=_text(photo.get("machine_number")),
                    path_candidates=candidates,
                )
            )
        return tuple(RecordPhotoGroup(title, tuple(items)) for title, items in sorted(groups.items(), key=lambda item: (PHOTO_GROUP_ORDER.get(item[0], 99), item[0].casefold())))

    def _eoat_detail(self, record: dict[str, Any], relationships: dict[str, Any], photos: list[dict[str, Any]], documentation: dict[str, Any]) -> RecordDetailData:
        photo_groups = self._photo_groups(photos, _text(record.get("eoat_id")), ENTITY_EOAT, _text(record.get("eoat_id")))
        unique_photo_count = sum(len(group.photos) for group in photo_groups)
        hero = _fields(
            ("Type", record.get("eoat_type")),
            ("Condition / Location", record.get("condition_location")),
            ("Current Machine", record.get("current_machine")),
            ("Plant / Area", record.get("plant_area")),
            ("Tool #", _one_or_count(record.get("tool_numbers"), "tools")),
            ("Part Family", record.get("part_family")),
            ("Parts Picked", record.get("parts_picked")),
            ("Connection Type", record.get("connection_type")),
            ("Air Architecture", record.get("air_architecture")),
            ("Sensors", record.get("sensors_summary")),
            ("Photos", str(unique_photo_count)),
            ("Last Audit", record.get("last_audit_date")),
        )
        details = (
            RecordSection(
                "Identification",
                _fields(
                    ("EOAT Assembly ID", record.get("eoat_id")),
                    ("Audit ID", record.get("audit_ids")),
                    ("Audit Date", record.get("last_audit_date")),
                    ("Plant / Area", record.get("plant_area")),
                    ("Press / Machine #", relationships.get("machines")),
                    ("Tool #", relationships.get("tools")),
                    ("Part Family", record.get("part_family")),
                    ("Part Name / Description", record.get("part_name_description")),
                ),
            ),
            RecordSection(
                "EOAT Configuration",
                _fields(
                    ("EOAT Type", record.get("eoat_type")),
                    ("Connection Type", record.get("connection_type")),
                    ("Parts Picked", record.get("parts_picked")),
                    ("Air Circuit Architecture", record.get("air_architecture")),
                    ("Sensors", record.get("sensors_summary")),
                ),
            ),
            RecordSection(
                "Documentation / Maintenance / Notes",
                _fields(
                    ("Photo Link / Count", f"{unique_photo_count} photo(s)"),
                    ("Tubing Routing Notes", record.get("tubing_notes")),
                    ("Known Issues / Observations", record.get("known_issues")),
                    ("Documentation Score", f"{documentation.get('documentation_score', 0)}%"),
                    ("Missing Documentation", documentation.get("missing_items") or ("None indexed",)),
                ),
            ),
        )
        docs = _documentation_fields(documentation, unique_photo_count)
        return RecordDetailData(
            record_type=ENTITY_EOAT,
            record_id=_text(record.get("eoat_id")),
            title=_text(record.get("display_name") or record.get("eoat_id")),
            subtitle=_text(record.get("eoat_type") or record.get("part_name_description") or "EOAT"),
            condition=_text(record.get("condition_location")),
            plant_area=_text(record.get("plant_area")),
            hero_fields=hero,
            detail_sections=details,
            documentation_fields=docs,
            photo_groups=photo_groups,
            history_fields=_fields(("Last Audit", record.get("last_audit_date")), ("Audit IDs", record.get("audit_ids"))),
            summary_fields=_fields(("Machines", str(len(relationships.get("machines", ())))), ("Tools", str(len(relationships.get("tools", ())))), ("Documentation", f"{documentation.get('documentation_score', 0)}%")),
            report_sections=details,
            workbook_sections=(),
            warnings=tuple(_warning_from_cache(item) for item in record.get("warnings", ()) or ()),
            source_rows=(),
        )

    def _tool_detail(self, record: dict[str, Any], relationships: dict[str, Any], photos: list[dict[str, Any]], documentation: dict[str, Any]) -> RecordDetailData:
        photo_groups = self._photo_groups(photos, f"Tool {_text(record.get('tool_number'))}", ENTITY_TOOL, _text(record.get("tool_number")))
        unique_photo_count = sum(len(group.photos) for group in photo_groups)
        details = (
            RecordSection(
                "Identification",
                _fields(
                    ("Tool #", record.get("tool_number")),
                    ("Mold #", record.get("molds")),
                    ("Part #", record.get("parts")),
                    ("Part Family", record.get("part_family")),
                    ("Part Name / Description", record.get("part_name_description")),
                    ("Plant / Area", record.get("plant_area")),
                    ("Last Audit Date", record.get("last_audit_date")),
                ),
            ),
            RecordSection(
                "Fit Check",
                _fields(
                    ("Compatible EOATs", relationships.get("eoats") or NOT_INDEXED),
                    ("Compatible Machines", relationships.get("machines") or NOT_INDEXED),
                    ("Current Machine", record.get("current_machine")),
                    ("Parts Picked", record.get("parts_picked")),
                ),
            ),
            RecordSection(
                "Documentation / Notes",
                _fields(
                    ("Photo Count", str(unique_photo_count)),
                    ("Documentation Score", f"{documentation.get('documentation_score', 0)}%"),
                    ("Missing Documentation", documentation.get("missing_items") or ("None indexed",)),
                ),
            ),
        )
        hero = _fields(
            ("Part Family", record.get("part_family")),
            ("Part Name", record.get("part_name_description")),
            ("Plant / Area", record.get("plant_area")),
            ("Last Audit", record.get("last_audit_date")),
            ("Compatible EOATs", str(len(relationships.get("eoats", ())))),
            ("Compatible Machines", str(len(relationships.get("machines", ())))),
            ("Parts Picked", record.get("parts_picked")),
            ("Current Machine", record.get("current_machine")),
            ("Documentation Score", f"{documentation.get('documentation_score', 0)}%"),
            ("Photos", str(unique_photo_count)),
        )
        return RecordDetailData(
            record_type=ENTITY_TOOL,
            record_id=_text(record.get("tool_number")),
            title=_text(record.get("display_name") or record.get("tool_number")),
            subtitle=_text(record.get("part_name_description") or record.get("part_family") or "Tool / Mold / Part"),
            condition=_text(record.get("current_machine")),
            plant_area=_text(record.get("plant_area")),
            hero_fields=hero,
            detail_sections=details,
            documentation_fields=_documentation_fields(documentation, unique_photo_count),
            photo_groups=photo_groups,
            history_fields=_fields(("Last Audit", record.get("last_audit_date"))),
            summary_fields=_fields(("EOATs", str(len(relationships.get("eoats", ())))), ("Machines", str(len(relationships.get("machines", ())))), ("Parts Picked", record.get("parts_picked"))),
            report_sections=details,
            workbook_sections=(),
            warnings=tuple(_warning_from_cache(item) for item in record.get("warnings", ()) or ()),
            source_rows=(),
        )

    def _machine_detail(self, record: dict[str, Any], relationships: dict[str, Any], photos: list[dict[str, Any]], documentation: dict[str, Any]) -> RecordDetailData:
        photo_groups = self._photo_groups(photos, f"Machine {_text(record.get('machine_number'))}", ENTITY_MACHINE, _text(record.get("machine_number")))
        unique_photo_count = sum(len(group.photos) for group in photo_groups)
        current = _text(relationships.get("current_eoat") or record.get("current_eoat_id") or NOT_INDEXED)
        details = (
            RecordSection(
                "Identification",
                _fields(
                    ("Machine #", record.get("machine_number")),
                    ("Plant / Area", record.get("plant_area")),
                    ("Cleanroom / Non-Cleanroom", record.get("area")),
                    ("Robot Type", record.get("robot_type")),
                    ("Robot Model / Controller", record.get("robot_model_controller")),
                    ("Last Audit Date", record.get("last_audit_date")),
                ),
            ),
            RecordSection(
                "Current Setup",
                _fields(
                    ("Current EOAT", current),
                    ("Current Tool(s)", relationships.get("tools") or NOT_INDEXED),
                    ("Air Architecture", record.get("air_architecture")),
                    ("External Pressure", record.get("external_pressure_circuits")),
                    ("External Vacuum", record.get("external_vacuum_circuits")),
                ),
            ),
            RecordSection(
                "Fit Check",
                _fields(
                    ("Compatible EOATs", relationships.get("eoats") or NOT_INDEXED),
                    ("Compatible Tools", relationships.get("tools") or NOT_INDEXED),
                    ("EOAT Count", str(len(relationships.get("eoats", ())))),
                    ("Tool Count", str(len(relationships.get("tools", ())))),
                ),
            ),
        )
        hero = _fields(
            ("Robot Type", record.get("robot_type")),
            ("Robot Model", record.get("robot_model_controller")),
            ("Area", record.get("area")),
            ("Last Audit", record.get("last_audit_date")),
            ("Current EOAT", current),
            ("Compatible EOATs", str(len(relationships.get("eoats", ())))),
            ("Compatible Tools", str(len(relationships.get("tools", ())))),
            ("Plant / Area", record.get("plant_area")),
            ("Air Architecture", record.get("air_architecture")),
            ("External Circuits", _external_circuits(record)),
            ("Documentation Score", f"{documentation.get('documentation_score', 0)}%"),
            ("Photos", str(unique_photo_count)),
        )
        return RecordDetailData(
            record_type=ENTITY_MACHINE,
            record_id=_text(record.get("machine_number")),
            title=_text(record.get("display_name") or f"Machine {_text(record.get('machine_number'))}"),
            subtitle=_text(record.get("robot_type") or record.get("robot_model_controller") or "Machine"),
            condition=current,
            plant_area=_text(record.get("plant_area")),
            hero_fields=hero,
            detail_sections=details,
            documentation_fields=_documentation_fields(documentation, unique_photo_count),
            photo_groups=photo_groups,
            history_fields=_fields(("Last Audit", record.get("last_audit_date"))),
            summary_fields=_fields(("EOATs", str(len(relationships.get("eoats", ())))), ("Tools", str(len(relationships.get("tools", ())))), ("Current EOAT", current)),
            report_sections=details,
            workbook_sections=(),
            warnings=tuple(_warning_from_cache(item) for item in record.get("warnings", ()) or ()),
            source_rows=(),
        )

    def _sort_records(self, records: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
        name = str(sort or "").casefold()
        if "machine" in name:
            return sorted(records, key=lambda item: _machine_sort_key(item.get("machine_number") or item.get("current_machine") or item.get("display_name")))
        if "tool" in name:
            return sorted(records, key=lambda item: _text(item.get("tool_number") or item.get("display_name")).casefold())
        if "eoat" in name:
            return sorted(records, key=lambda item: _text(item.get("eoat_id") or item.get("display_name")).casefold())
        if "missing docs" in name:
            return sorted(records, key=lambda item: int(item.get("documentation_score") or 0))
        return sorted(records, key=lambda item: _text(item.get("display_name") or item.get("eoat_id") or item.get("tool_number") or item.get("machine_number")).casefold())


def _file_signature(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
        return {"path": str(path), "exists": True, "modified_time": stat.st_mtime_ns, "size": stat.st_size}
    except OSError:
        return {"path": str(path), "exists": False, "modified_time": 0, "size": 0}


def _text(value: Any) -> str:
    return display_value(value)


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if display_value(value) else ()
    if isinstance(value, Iterable):
        return tuple(display_value(item) for item in value if display_value(item))
    text = display_value(value)
    return (text,) if text else ()


def _fields(*items: tuple[str, Any]) -> tuple[RecordField, ...]:
    fields: list[RecordField] = []
    for label, value in items:
        normalized = _field_value(value)
        fields.append(RecordField(label, normalized, "muted" if normalized == NOT_INDEXED else "normal"))
    return tuple(fields)


def _field_value(value: Any) -> str | tuple[str, ...]:
    if isinstance(value, (tuple, list, set)):
        cleaned = tuple(display_value(item) for item in value if display_value(item))
        return cleaned or NOT_INDEXED
    text = display_value(value)
    return text or NOT_INDEXED


def _first_row(rows: Iterable[dict[str, Any]], *names: str) -> str:
    for row in rows:
        if not isinstance(row, dict):
            continue
        folded = {str(key).casefold(): key for key in row}
        for name in names:
            key = folded.get(name.casefold())
            if key is not None and display_value(row.get(key)):
                return display_value(row.get(key))
    return ""


def _last_audit(rows: Iterable[dict[str, Any]]) -> str:
    values = [display_value(row.get("Audit Date")) for row in rows if isinstance(row, dict) and display_value(row.get("Audit Date"))]
    return values[-1] if values else NOT_INDEXED


def _area_from_rows(rows: Iterable[dict[str, Any]]) -> str:
    blob = _rows_blob(rows)
    if "plant 3" in blob:
        return "Plant 3"
    if "cleanroom" in blob:
        return "Cleanroom"
    if "plant 4" in blob:
        return "Plant 4"
    return NOT_INDEXED


def _rows_blob(rows: Iterable[dict[str, Any]]) -> str:
    return " ".join(str(value) for row in rows if isinstance(row, dict) for value in row.values() if display_value(value)).casefold()


def _eoat_condition_from_rows(record: EOATRecord) -> str:
    blob = _rows_blob(getattr(record, "source_rows", ()) or ())
    status = display_value(getattr(record, "status", ""))
    if "cabinet" in blob:
        return "In Cabinet"
    if "storage" in blob or "stored" in blob:
        return "In Storage"
    if "off-machine" in blob or "off machine" in blob or "bench audit" in blob:
        return "Off-Machine"
    if "eoat not installed" in blob or "not installed" in blob:
        return "Not Installed"
    if status and status.casefold() not in {"complete", "installed", "active"}:
        return status
    machines = tuple(getattr(record, "machines", ()) or ())
    if machines:
        return f"On Machine {_sort_machines(machines)[0]}"
    return NOT_INDEXED


def _air_summary(record: EOATRecord) -> str:
    pieces = tuple(value for value in (record.vacuum_info, record.pressure_info, record.gripper_info) if display_value(value))
    return " | ".join(display_value(value) for value in pieces) or NOT_INDEXED


def _external_circuits(record: dict[str, Any]) -> str:
    values = [record.get("external_pressure_circuits"), record.get("external_vacuum_circuits")]
    text = " | ".join(display_value(value) for value in values if display_value(value) and display_value(value) != NOT_INDEXED)
    return text or NOT_INDEXED


def _documentation_record(score: int, missing: Iterable[str], photo_count: int, status_label: str = "") -> dict[str, Any]:
    missing_items = _tuple(missing)
    return {
        "documentation_score": int(score or 0),
        "status_label": display_value(status_label) or "Unknown",
        "cad_status": _doc_status_for(missing_items, "cad"),
        "bom_status": _doc_status_for(missing_items, "bom"),
        "revision_status": _doc_status_for(missing_items, "revision"),
        "process_binder_status": _doc_status_for(missing_items, "process binder"),
        "photo_folder_link_status": "Indexed" if int(photo_count or 0) else NOT_INDEXED,
        "missing_items": list(missing_items),
        "photo_count": int(photo_count or 0),
    }


def _documentation_fields(documentation: dict[str, Any], photo_count: int) -> tuple[RecordField, ...]:
    return _fields(
        ("Documentation Score", f"{int(documentation.get('documentation_score') or 0)}%"),
        ("Photo Folder / Link", documentation.get("photo_folder_link_status") or ("Indexed" if photo_count else NOT_INDEXED)),
        ("CAD Status", documentation.get("cad_status")),
        ("BOM Status", documentation.get("bom_status")),
        ("Revision Status", documentation.get("revision_status")),
        ("Process Binder", documentation.get("process_binder_status")),
        ("Missing Items", documentation.get("missing_items") or ("None indexed",)),
    )


def _doc_status_for(missing: tuple[str, ...], keyword: str) -> str:
    return "Missing" if any(keyword in item.casefold() for item in missing) else "Indexed"


def _documentation_from_cache(data: dict[str, Any]) -> DocumentationStatus:
    return DocumentationStatus(
        score=int(data.get("documentation_score") or 0),
        status_label=_text(data.get("status_label") or "Unknown"),
        missing_fields=tuple(_tuple(data.get("missing_items"))),
    )


def _warning_dict(warning: WarningItem) -> dict[str, Any]:
    return {
        "severity": warning.severity,
        "title": warning.title,
        "message": warning.message,
        "source": warning.source,
        "why_it_matters": warning.why_it_matters,
        "suggested_fix": warning.suggested_fix,
        "related_eoat_id": warning.related_eoat_id,
        "machine": warning.machine,
        "tool": warning.tool,
    }


def _warning_from_cache(data: dict[str, Any]) -> WarningItem:
    return WarningItem(
        severity=_text(data.get("severity")),
        title=_text(data.get("title")),
        message=_text(data.get("message")),
        source=_text(data.get("source")),
        why_it_matters=_text(data.get("why_it_matters")),
        suggested_fix=_text(data.get("suggested_fix")),
        related_eoat_id=_text(data.get("related_eoat_id")),
        machine=_text(data.get("machine")),
        tool=_text(data.get("tool")),
    )


def _photo_record(photo: PhotoItem, *, root: Path | None, owner_eoat: str = "") -> dict[str, Any]:
    candidates = _photo_candidates(photo, root=root)
    filename = _text(photo.photo_filename or photo.stored_filename or photo.filename or (Path(photo.path).name if photo.path else ""))
    return {
        "photo_id": _text(photo.photo_id),
        "photo_type": _text(photo.photo_type or photo.category or photo.area_shown) or "Other",
        "area_shown": _text(photo.area_shown),
        "category": _text(photo.category),
        "date_taken": _text(photo.date_taken),
        "imported_at": _text(photo.imported_at),
        "plant_area": _text(photo.plant_area),
        "machine_number": _text(photo.machine),
        "eoat_id": _text(photo.eoat_id or owner_eoat),
        "tool_number": _text(photo.tool),
        "audit_id": _text(photo.related_audit_id),
        "folder_path": _text(photo.folder_path),
        "stored_relative_path": _text(photo.stored_relative_path),
        "stored_filename": _text(photo.stored_filename),
        "photo_filename": _text(photo.photo_filename or filename),
        "original_filename": _text(photo.original_filename),
        "filename": filename,
        "description": _text(photo.description),
        "source": _text(photo.source),
        "path": _text(photo.path),
        "resolved_path_candidates": list(candidates),
    }


def _photo_item_from_cache(data: dict[str, Any]) -> PhotoItem:
    candidates = _tuple(data.get("resolved_path_candidates"))
    return PhotoItem(
        path=candidates[0] if candidates else _text(data.get("path")),
        filename=_text(data.get("filename") or data.get("photo_filename")),
        photo_id=_text(data.get("photo_id")),
        category=_text(data.get("photo_type")),
        eoat_id=_text(data.get("eoat_id")),
        tool=_text(data.get("tool_number")),
        machine=_text(data.get("machine_number")),
        related_audit_id=_text(data.get("audit_id")),
        date_taken=_text(data.get("date_taken")),
        imported_at=_text(data.get("imported_at")),
        plant_area=_text(data.get("plant_area")),
        description=_text(data.get("description")),
        photo_type=_text(data.get("photo_type")),
        folder_path=_text(data.get("folder_path")),
        stored_relative_path=_text(data.get("stored_relative_path")),
        photo_filename=_text(data.get("photo_filename")),
        original_filename=_text(data.get("original_filename")),
        stored_filename=_text(data.get("stored_filename")),
        source=_text(data.get("source")),
    )


def _photo_candidates(photo: PhotoItem, *, root: Path | None) -> tuple[str, ...]:
    candidates: list[str] = []

    def add(value: str | Path) -> None:
        text = display_value(value)
        if not text:
            return
        if text.casefold().startswith("file://"):
            text = text[7:]
        text = text.strip("\"'")
        path = Path(text)
        if not path.is_absolute() and root is not None:
            path = root / path
        resolved = str(path)
        if resolved not in candidates:
            candidates.append(resolved)

    add(photo.path)
    stored_relative = display_value(photo.stored_relative_path)
    if stored_relative:
        add(stored_relative)
        if root is not None:
            paths = resolve_project_paths(root)
            add(paths.master_workbook.parent / stored_relative)
            add(paths.cell_photos / stored_relative)
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
            add(folder)
        for filename in filenames:
            add(folder / filename)
    for filename in filenames:
        add(filename)
        if root is not None:
            add(resolve_project_paths(root).cell_photos / filename)
    return tuple(candidates)


def _photo_association(photo: dict[str, Any]) -> str:
    for label, key in (("EOAT", "eoat_id"), ("Tool", "tool_number"), ("Machine", "machine_number"), ("Audit", "audit_id")):
        value = _text(photo.get(key))
        if value:
            return f"{label} {value}"
    return ""


def _friendly_photo_group(value: str) -> str:
    normalized = _normalize_photo_label(value)
    if not normalized or normalized == "other":
        return "Other"
    if _photo_preview_kind(normalized) in {"front", "overview"}:
        return "Overall / Front View"
    if "side" in normalized:
        return "Side View"
    if any(token in normalized for token in ("cup", "cups", "gripper", "grippers", "vacuum cup")):
        return "Vacuum Cups / Grippers"
    if "tool number" in normalized or "tool no" in normalized or "serial" in normalized:
        return "Tool Number"
    if "mount" in normalized or "hardware" in normalized or "bracket" in normalized:
        return "Mounting Hardware"
    if any(token in normalized for token in ("tubing", "tube", "hose", "air routing", "pneumatic", "vacuum line", "air line")):
        return "Tubing / Air Routing"
    if "sensor" in normalized or "electrical" in normalized:
        return "Sensors"
    if "quick disconnect" in normalized or "qd" in normalized or "disconnect" in normalized:
        return "Quick Disconnect"
    if "cable" in normalized or "wire" in normalized or "cord" in normalized:
        return "Cable Management"
    if any(token in normalized for token in ("wear", "damage", "damaged", "worn", "crack", "broken")):
        return "Wear / Damage"
    return "Other"


def _normalize_photo_label(value: Any) -> str:
    text = display_value(value).casefold()
    if not text:
        return ""
    text = text.replace("\\", " ").replace("/", " ").replace("_", " ").replace("-", " ")
    pieces = []
    for raw in text.split():
        token = raw.strip(" .,:;()[]{}")
        if not token:
            continue
        if token.isdigit():
            continue
        pieces.append(token)
    return " ".join(pieces)


def _photo_match_text(photo: dict[str, Any], *, include_filename_fallback: bool = True) -> str:
    metadata = " ".join(
        _normalize_photo_label(photo.get(key))
        for key in ("photo_type", "area_shown", "category", "description")
        if _normalize_photo_label(photo.get(key)) not in {"", "other"}
    )
    if metadata or not include_filename_fallback:
        return metadata
    return " ".join(
        _normalize_photo_label(photo.get(key))
        for key in ("stored_relative_path", "folder_path", "stored_filename", "photo_filename", "original_filename", "filename", "path")
        if _normalize_photo_label(photo.get(key))
    )


def _photo_preview_kind(value: Any) -> str:
    text = _normalize_photo_label(value)
    if not text:
        return ""
    front_names = {
        "front",
        "front view",
        "overall front",
        "overall front view",
        "main view",
        "main",
    }
    if text in front_names or ("front" in text and ("view" in text or "overall" in text)):
        return "front"
    if text in {"overview", "overall"} or "overview" in text or text.startswith("overall"):
        return "overview"
    if "side" in text and ("view" in text or text == "side"):
        return "side"
    return ""


def _photo_has_path_candidate(photo: dict[str, Any]) -> bool:
    return bool(_tuple(photo.get("resolved_path_candidates")) or _text(photo.get("path")) or _text(photo.get("stored_filename")) or _text(photo.get("photo_filename")))


def _select_preview_photo(
    photos: Iterable[dict[str, Any]],
    *,
    record_type: str,
    record_id: str,
    related_eoats: Iterable[str] = (),
) -> dict[str, Any] | None:
    ranked: list[tuple[tuple[int, str, int], dict[str, Any]]] = []
    related_eoat_keys = {normalized_eoat_key(value) for value in related_eoats if _text(value)}
    for index, photo in enumerate(photos):
        if not _photo_has_path_candidate(photo):
            continue
        kind = _photo_preview_kind(_photo_match_text(photo)) or _photo_preview_kind(_photo_match_text(photo, include_filename_fallback=True))
        if record_type == ENTITY_EOAT:
            if kind == "front":
                stage = 0
            elif kind == "overview":
                stage = 1
            elif kind == "side":
                stage = 2
            else:
                stage = 3
        elif record_type == ENTITY_TOOL:
            relation = _tool_photo_relation(photo, record_id, related_eoat_keys)
            if kind in {"front", "overview"} and relation == "direct":
                stage = 0 if kind == "front" else 1
            elif kind in {"front", "overview"} and relation == "eoat":
                stage = 2 if kind == "front" else 3
            else:
                stage = 4
        else:
            continue
        ranked.append(((stage, _text(photo.get("date_taken") or photo.get("imported_at")), index), photo))
    if not ranked:
        return None
    return sorted(ranked, key=lambda item: item[0])[0][1]


def _tool_photo_relation(photo: dict[str, Any], tool_id: str, related_eoat_keys: set[str]) -> str:
    tool_key = normalized_tool_key(tool_id)
    if normalized_tool_key(photo.get("tool_number")) == tool_key:
        return "direct"
    if "tool photo index" in _text(photo.get("source")).casefold():
        return "direct"
    eoat_key = normalized_eoat_key(photo.get("eoat_id"))
    if eoat_key and (not related_eoat_keys or eoat_key in related_eoat_keys):
        return "eoat"
    return "related"


def _preview_cache_fields(photo: dict[str, Any] | None) -> dict[str, Any]:
    if not photo:
        return {"preview_photo_id": "", "preview_photo_path_candidates": [], "preview_photo_type": ""}
    candidates = list(dict.fromkeys([*_tuple(photo.get("resolved_path_candidates")), _text(photo.get("path"))]))
    photo_type = _text(photo.get("photo_type") or photo.get("area_shown") or photo.get("category")) or "Other"
    return {
        "preview_photo_id": _text(photo.get("photo_id")),
        "preview_photo_path_candidates": [path for path in candidates if path],
        "preview_photo_type": photo_type,
    }


def _dedupe_photo_records(photos: Iterable[dict[str, Any]], *, record_type: str, record_id: str) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for raw_photo in photos:
        photo = dict(raw_photo)
        key = _photo_dedup_key(photo)
        if not key:
            continue
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = photo
            continue
        LOGGER.debug("Duplicate photo skipped: %s", key)
        deduped[key] = _preferred_photo_record(existing, photo, record_type=record_type, record_id=record_id)
    sort_key = lambda item: (_text(item.get("date_taken") or item.get("imported_at")), _text(item.get("photo_id")), _text(item.get("filename")))
    return sorted(deduped.values(), key=sort_key)


def _photo_dedup_key(photo: dict[str, Any]) -> str:
    photo_id = _text(photo.get("photo_id"))
    if photo_id and photo_id.casefold() not in {"unknown", "other", "n/a", "na"}:
        return f"id:{photo_id.casefold()}"
    for candidate in _tuple(photo.get("resolved_path_candidates")):
        path_key = _absolute_path_key(candidate)
        if path_key:
            return f"path:{path_key}"
    path_key = _absolute_path_key(photo.get("path"))
    if path_key:
        return f"path:{path_key}"
    stored = _compound_key(photo.get("stored_relative_path"), photo.get("stored_filename"))
    if stored:
        return f"stored:{stored}"
    folder = _compound_key(photo.get("folder_path"), photo.get("photo_filename") or photo.get("stored_filename") or photo.get("filename"))
    if folder:
        return f"folder:{folder}"
    original = _compound_key(photo.get("original_filename"), photo.get("audit_id"), photo.get("photo_type"))
    if original:
        return f"original:{original}"
    candidates = "|".join(_tuple(photo.get("resolved_path_candidates")) or _tuple(photo.get("path")))
    if candidates:
        return f"candidate:{sha1(candidates.casefold().encode('utf-8')).hexdigest()}"
    return ""


def _absolute_path_key(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    path = Path(text.strip("\"'"))
    if not path.is_absolute():
        return ""
    return str(path).replace("\\", "/").casefold()


def _compound_key(*values: Any) -> str:
    pieces = [_text(value).casefold() for value in values if _text(value)]
    return "|".join(pieces)


def _preferred_photo_record(existing: dict[str, Any], incoming: dict[str, Any], *, record_type: str, record_id: str) -> dict[str, Any]:
    existing_score = _photo_metadata_score(existing, record_type=record_type, record_id=record_id)
    incoming_score = _photo_metadata_score(incoming, record_type=record_type, record_id=record_id)
    if incoming_score > existing_score:
        merged = dict(existing)
        merged.update({key: value for key, value in incoming.items() if _text(value) or isinstance(value, list)})
        return merged
    merged = dict(existing)
    for key, value in incoming.items():
        if key not in merged or not _text(merged.get(key)):
            merged[key] = value
    return merged


def _photo_metadata_score(photo: dict[str, Any], *, record_type: str, record_id: str) -> tuple[int, int, str]:
    direct = 0
    if record_type == ENTITY_EOAT and normalized_eoat_key(photo.get("eoat_id")) == normalized_eoat_key(record_id):
        direct = 1
    elif record_type == ENTITY_TOOL and normalized_tool_key(photo.get("tool_number")) == normalized_tool_key(record_id):
        direct = 1
    elif record_type == ENTITY_MACHINE and normalized_machine_key(photo.get("machine_number")) == normalized_machine_key(record_id):
        direct = 1
    label = _text(photo.get("photo_type") or photo.get("area_shown") or photo.get("category"))
    specificity = 0 if not label or label.casefold() in {"other", "unknown"} else min(len(_normalize_photo_label(label)), 80)
    recency = _text(photo.get("imported_at") or photo.get("date_taken"))
    return (direct, specificity, recency)


def _one_or_count(values: Any, noun: str) -> str:
    items = _tuple(values)
    if not items:
        return NOT_INDEXED
    if len(items) == 1:
        return items[0]
    return f"{len(items)} {noun}"


def _search_text(record: dict[str, Any]) -> str:
    pieces: list[str] = []
    for value in record.values():
        if isinstance(value, dict):
            pieces.extend(_text(item) for item in value.values())
        elif isinstance(value, list):
            pieces.extend(_text(item) if not isinstance(item, dict) else " ".join(_text(v) for v in item.values()) for item in value)
        else:
            pieces.append(_text(value))
    return " ".join(piece for piece in pieces if piece)


def _sort_machines(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(sorted(_tuple(values), key=_machine_sort_key))


def _machine_sort_key(value: Any) -> tuple[int, int | str]:
    text = display_value(value)
    return (0, int(text)) if text.isdigit() else (1, text.casefold())
