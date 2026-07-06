from __future__ import annotations

import logging
import math
import hashlib
import threading
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from PySide6.QtCore import QEvent, QEasingCurve, QParallelAnimationGroup, QPoint, QPointF, Property, QRect, QRectF, QSize, Qt, QTimer, QPropertyAnimation, Signal, Slot
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QImageReader, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.atlas_record_details import RecordDetailData, RecordField, RecordPhoto, RecordPhotoGroup, RecordSection, build_record_detail_data
from core.atlas_models import AtlasDataBundle, EOATRecord, MachineRecord, ToolRecord
from core.atlas_utils import normalized_eoat_key, normalized_machine_key, normalized_tool_key
from core.library_data_service import LibraryDataService
from core.performance import log_perf_marker, perf_timer
from core.photos.photo_service import PhotoService

from .data import loaded_status_text, machine_label
from .widgets import (
    GlassPanel,
    MinimalistToast,
    SearchMiniIcon,
    StatusDot,
    clear_layout,
    glyph_icon,
    prefers_reduced_motion,
    set_placeholder_color,
)


ENTITY_EOAT = "eoat"
ENTITY_TOOL = "tool"
ENTITY_MACHINE = "machine"

LOGGER = logging.getLogger(__name__)
PHOTO_THUMBNAIL_CACHE: dict[tuple[str, int, int], QPixmap] = {}
PHOTO_PREVIEW_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}

TYPE_LABELS = {
    "all": "All",
    ENTITY_EOAT: "EOATs",
    ENTITY_TOOL: "Tools",
    ENTITY_MACHINE: "Machines",
}

TYPE_FROM_LABEL = {
    "All": "all",
    "EOATs": ENTITY_EOAT,
    "Tools": ENTITY_TOOL,
    "Machines": ENTITY_MACHINE,
}

STATUS_OPTIONS = (
    "All",
    "Active",
    "In Service",
    "In Storage",
    "In Maintenance",
    "Not Indexed",
    "Needs Review",
    "Out of Service",
)

LOCATION_OPTIONS = (
    "All",
    "Plant 4",
    "Plant 3",
    "Cleanroom",
    "Production",
    "In Cabinet",
    "In Storage",
    "On Machine",
)

SORT_OPTIONS = (
    "Alphabetical (A-Z)",
    "Recently Updated",
    "Status",
    "Location",
    "Machine Number",
    "Tool Number",
    "EOAT ID",
    "Missing Docs First",
)

ADVANCED_FILTERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Documentation", ("Docs Good", "Missing Docs", "CAD Missing", "BOM Missing", "Revision Missing")),
    ("Photos", ("Has Photos", "Missing Photos", "Photo Folder Missing")),
    ("Robot Type", ("Engel", "Wittmann", "Sytrama", "Unknown Robot")),
    ("Air Architecture", ("Vacuum", "Pressure", "Mixed Air", "Robot Only", "External Peripheral Only")),
    ("EOAT Type", ("Mechanical / Gripper", "Vacuum", "Hybrid", "Specialty")),
    ("Current Condition", ("On Machine", "In Cabinet", "In Storage", "Off-Machine", "Not Indexed")),
    ("Compatibility", ("High Reuse", "Single Machine", "Missing Compatibility")),
    ("Counts", ("Has Tools", "Has Machines", "No Linked Tools", "No Linked Machines")),
)

ANIMATION_FAST = 150
ANIMATION_MEDIUM = 220
BROWSE_CARD_HEIGHT = 236
BROWSE_CARD_WIDTH = 356
LIST_CARD_HEIGHT = 118
GRID_PAGE_SIZE = 8
SEARCH_DEBOUNCE_MS = 125
INTERACTION_IDLE_MS = 500


def _controller_project_root(controller) -> str:
    config = getattr(controller, "config", None)
    return str(getattr(config, "project_root", "") or "")


def _catalog_project_root(catalog: "LibraryCatalog | None") -> str:
    if catalog is None:
        return ""
    bundle = getattr(catalog, "bundle", None)
    if bundle is not None:
        return str(getattr(bundle, "project_root", "") or "")
    data_service = getattr(catalog, "data_service", None)
    if data_service is not None:
        root = getattr(data_service, "project_root", None)
        if root:
            return str(root)
    return _controller_project_root(getattr(catalog, "controller", None))


def _widget_project_root(widget: QWidget | None) -> str:
    current = widget
    while current is not None:
        catalog = getattr(current, "catalog", None)
        if catalog is not None:
            root = _catalog_project_root(catalog)
            if root:
                return root
        controller = getattr(current, "controller", None)
        if controller is not None:
            root = _controller_project_root(controller)
            if root:
                return root
        current = current.parentWidget()
    return ""


def _maybe_perf_timer(project_root: str, operation: str, *, details: dict[str, Any]):
    if not project_root:
        return nullcontext()
    return perf_timer(
        project_root,
        operation,
        details=details,
        source="minimalist_library",
        page_tool="library_record",
    )


def _log_ui_marker(project_root: str, operation: str, *, details: dict[str, Any] | None = None, page_tool: str = "library") -> None:
    if not project_root:
        return
    log_perf_marker(
        project_root,
        operation,
        details=details or {},
        source="minimalist_library",
        page_tool=page_tool,
    )


def animation_duration(duration: int) -> int:
    return 1 if prefers_reduced_motion() else duration


def clipped_text(value: str, limit: int = 96) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)].rstrip()}..."


def count_label(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def _natural_machine_key(value: str) -> tuple[int, int | str]:
    text = str(value or "").strip()
    return (0, int(text)) if text.isdigit() else (1, text.casefold())


def _truthy_text(value: Any) -> str:
    return str(value or "").strip()


def _photo_item_candidate_path(project_root: str | Path, photo: Any) -> str:
    folder = _truthy_text(getattr(photo, "folder_path", ""))
    filename = _truthy_text(
        getattr(photo, "stored_filename", "")
        or getattr(photo, "photo_filename", "")
        or getattr(photo, "original_filename", "")
        or getattr(photo, "filename", "")
    )
    if not folder or not filename:
        return ""
    path = Path(folder) / filename
    if path.is_absolute():
        return str(path)
    return str(Path(project_root) / path) if str(project_root or "").strip() else str(path)


def _source_text(record: Any) -> str:
    pieces: list[str] = []
    for field in (
        "status",
        "install_notes",
        "known_issues",
        "connection_type",
        "vacuum_info",
        "pressure_info",
        "gripper_info",
        "sensor_info",
        "robot_type",
        "robot_model",
        "controller",
        "source",
    ):
        value = getattr(record, field, "")
        if _truthy_text(value):
            pieces.append(str(value))
    for warning in getattr(record, "warnings", ()) or ():
        pieces.append(str(getattr(warning, "title", "") or ""))
        pieces.append(str(getattr(warning, "message", "") or ""))
    for row in getattr(record, "source_rows", ()) or ():
        if isinstance(row, dict):
            pieces.extend(str(value) for value in row.values() if _truthy_text(value))
    return " ".join(pieces).casefold()


def _status_has_inactive_language(blob: str) -> bool:
    return any(
        phrase in blob
        for phrase in (
            "retired",
            "inactive",
            "out of service",
            "out-of-service",
            "decommissioned",
            "scrapped",
        )
    )


@dataclass(frozen=True)
class LibraryEntity:
    entity_type: str
    key: str
    title: str
    subtitle: str
    meta: str
    record: EOATRecord | ToolRecord | MachineRecord
    badges: tuple[tuple[str, str], ...]
    search_text: str

    @property
    def type_label(self) -> str:
        return {"eoat": "EOAT", "tool": "Tool", "machine": "Machine"}.get(self.entity_type, "Record")


@dataclass(frozen=True)
class AtlasCardMetric:
    icon: str
    value: str
    label: str
    tone: str = "normal"


@dataclass(frozen=True)
class MachineCurrentEoatDisplay:
    value: str
    tone: str
    state: str


def machine_current_eoat_display(record: MachineRecord) -> MachineCurrentEoatDisplay:
    current = _truthy_text(getattr(record, "current_eoat", ""))
    if current:
        return MachineCurrentEoatDisplay(current, "normal", _truthy_text(getattr(record, "current_eoat_status", "")) or "indexed")
    resolver_status = _truthy_text(getattr(record, "current_eoat_status", ""))
    if resolver_status == "explicit_none":
        return MachineCurrentEoatDisplay("No Current EOAT", "warning", "explicit_none")
    blob = _source_text(record)
    explicit_no_current = any(
        phrase in blob
        for phrase in (
            "no current eoat",
            "no eoat installed",
            "eoat not installed",
            "not installed / bench audit",
        )
    )
    if explicit_no_current:
        return MachineCurrentEoatDisplay("No Current EOAT", "warning", "explicit_none")
    return MachineCurrentEoatDisplay("Not Indexed", "muted", "unknown")


def record_status_display(entity: LibraryEntity) -> tuple[str, str]:
    blob = _source_text(entity.record)
    if _status_has_inactive_language(blob):
        return "Inactive", "warning"
    return "Active", "good"


def card_status_display(entity: LibraryEntity, catalog: "LibraryCatalog | None" = None) -> tuple[str, str]:
    blob = _source_text(entity.record)
    if _status_has_inactive_language(blob):
        return "Out of Service", "warning"
    if "maintenance" in blob or "repair" in blob:
        return "In Maintenance", "warning"
    if entity.entity_type == ENTITY_EOAT:
        condition, tone = eoat_condition_display(entity.record, catalog)
        if condition in {"In Storage", "Not Indexed"}:
            return condition, "muted"
        if tone == "warning" and condition == "Not Installed":
            return "Not Indexed", "muted"
    if entity.entity_type == ENTITY_MACHINE:
        current = machine_current_eoat_display(entity.record)
        if current.state == "unknown" and not getattr(entity.record, "compatible_eoats", ()):
            return "Not Indexed", "muted"
    return "In Service", "good"


def eoat_condition_display(record: EOATRecord, catalog: "LibraryCatalog | None" = None) -> tuple[str, str]:
    eoat_id = normalized_eoat_key(getattr(record, "eoat_id", "") or getattr(record, "display_id", ""))
    data_service = getattr(catalog, "data_service", None) if catalog is not None else None
    if data_service is not None and data_service.is_index_ready() and eoat_id:
        relationships = data_service.peek_relationships(ENTITY_EOAT, getattr(record, "eoat_id", "") or getattr(record, "display_id", ""))
        current_machines = tuple(relationships.get("current_machines", ()) or ())
        if current_machines:
            return f"On Machine {sorted(current_machines, key=_natural_machine_key)[0]}", "normal"
        condition = _truthy_text(relationships.get("condition_location", ""))
        if condition and condition != "Not Indexed":
            return condition, "normal" if condition != "In Storage" else "muted"
    if catalog is not None and catalog.bundle is not None and eoat_id:
        current_machines = [
            machine.machine
            for machine in catalog.bundle.machines
            if normalized_eoat_key(getattr(machine, "current_eoat", "")) == eoat_id
        ]
        if current_machines:
            return f"On Machine {sorted(current_machines, key=_natural_machine_key)[0]}", "normal"
    blob = _source_text(record)
    status = _truthy_text(getattr(record, "status", ""))
    if "cabinet" in blob:
        return "In Cabinet", "normal"
    if "storage" in blob or "stored" in blob:
        return "In Storage", "muted"
    if "off-machine" in blob or "off machine" in blob or "bench audit" in blob:
        return "Off-Machine", "warning"
    if "eoat not installed" in blob or "not installed" in blob:
        return "Not Installed", "warning"
    if status and status.casefold() not in {"complete", "installed", "active"}:
        return status, "normal"
    machines = tuple(getattr(record, "machines", ()) or ())
    if machines:
        return f"On Machine {sorted(machines, key=_natural_machine_key)[0]}", "normal"
    return "Not Indexed", "muted"


def entity_condition_line(entity: LibraryEntity, catalog: "LibraryCatalog | None" = None) -> tuple[str, str]:
    record = entity.record
    if entity.entity_type == ENTITY_EOAT:
        return eoat_condition_display(record, catalog)
    if entity.entity_type == ENTITY_MACHINE:
        current = machine_current_eoat_display(record)
        return (f"Current {current.value}", current.tone) if current.state == "indexed" else (current.value, current.tone)
    machines = tuple(getattr(record, "compatible_machines", ()) or ())
    if machines:
        return f"On Machine {sorted(machines, key=_natural_machine_key)[0]}", "normal"
    return "Not Indexed", "muted"


def entity_location_line(entity: LibraryEntity, catalog: "LibraryCatalog | None" = None) -> str:
    record = entity.record
    blob = _source_text(record)
    if "plant 3" in blob:
        return "Plant 3"
    if "cleanroom" in blob:
        return "Cleanroom"
    if entity.entity_type == ENTITY_MACHINE:
        return "Production"
    return "Plant 4"


def atlas_card_metrics(entity: LibraryEntity, catalog: "LibraryCatalog | None", *, variant: str = "compact") -> tuple[AtlasCardMetric, ...]:
    record = entity.record
    compact = variant in {"compact", "related", "search", "relationship", "node", "center_node", "list"}
    if entity.entity_type == ENTITY_MACHINE:
        current = machine_current_eoat_display(record)
        return (
            AtlasCardMetric("grid", str(len(getattr(record, "compatible_tools", ()))), "TOOLS"),
            AtlasCardMetric("eoat", str(len(getattr(record, "compatible_eoats", ()))), "EOATs"),
            AtlasCardMetric("eoat", current.value, "CURRENT EOAT", current.tone),
        )
    if entity.entity_type == ENTITY_EOAT:
        parts = len(getattr(record, "parts", ()) or ())
        condition, condition_tone = eoat_condition_display(record, catalog)
        metrics = (
            AtlasCardMetric("machine", str(len(getattr(record, "machines", ()))), "MACHINES" if compact else "COMPATIBLE MACHINES"),
            AtlasCardMetric("grid", str(len(getattr(record, "tools", ()))), "TOOLS" if compact else "COMPATIBLE TOOLS"),
            AtlasCardMetric("library", str(parts) if parts else "--", "PICKS" if compact else "PARTS PICKED", "muted" if not parts else "normal"),
            AtlasCardMetric("target", condition, "CONDITION", condition_tone),
        )
        return (metrics[0], metrics[1], metrics[3]) if compact else metrics
    parts = len(getattr(record, "parts", ()) or ())
    return (
        AtlasCardMetric("machine", str(len(getattr(record, "compatible_machines", ()))), "MACHINES" if compact else "COMPATIBLE MACHINES"),
        AtlasCardMetric("eoat", str(len(getattr(record, "compatible_eoats", ()))), "EOATs" if compact else "EOAT COMPATIBLE"),
        AtlasCardMetric("library", str(parts) if parts else "--", "PICKS" if compact else "PARTS PICKED", "muted" if not parts else "normal"),
    )


class LibraryCatalog:
    def __init__(
        self,
        bundle: AtlasDataBundle | None,
        controller,
        data_service: LibraryDataService | None = None,
        photo_service: PhotoService | None = None,
    ):
        self.bundle = bundle
        self.controller = controller
        self.data_service = data_service
        self.photo_service = photo_service
        project_root = str(getattr(bundle, "project_root", "") or _controller_project_root(controller))
        if not project_root and data_service is not None and getattr(data_service, "project_root", None):
            project_root = str(data_service.project_root)
        if self.photo_service is not None and project_root:
            self.photo_service.set_project_root(project_root)
        with perf_timer(
            project_root,
            "library.load_cached_records",
            details={
                "bundle_loaded": bundle is not None,
                "eoats": len(data_service.get_eoats()) if data_service is not None and data_service.is_index_ready() else len(getattr(bundle, "eoats", ()) or ()),
                "tools": len(data_service.get_tools()) if data_service is not None and data_service.is_index_ready() else len(getattr(bundle, "tools", ()) or ()),
                "machines": len(data_service.get_machines()) if data_service is not None and data_service.is_index_ready() else len(getattr(bundle, "machines", ()) or ()),
            },
            source="minimalist_library",
            page_tool="library",
        ):
            self.entities = self._build_entities(bundle)
            self.by_key = {(entity.entity_type, self._norm(entity.entity_type, entity.key)): entity for entity in self.entities}

    def entity_for(self, entity_type: str, key: str) -> LibraryEntity | None:
        return self.by_key.get((entity_type, self._norm(entity_type, key)))

    def first_entity(self, entity_type: str) -> LibraryEntity | None:
        return next((entity for entity in self.entities if entity.entity_type == entity_type), None)

    def related_tools(self, entity: LibraryEntity) -> list[LibraryEntity]:
        if self.data_service is not None and self.data_service.is_index_ready():
            relationships = self.data_service.peek_relationships(entity.entity_type, entity.key)
            return self._entities_for(ENTITY_TOOL, relationships.get("tools", ()))
        if entity.entity_type == ENTITY_EOAT:
            return self._entities_for(ENTITY_TOOL, getattr(entity.record, "tools", ()))
        if entity.entity_type == ENTITY_MACHINE:
            return self._entities_for(ENTITY_TOOL, getattr(entity.record, "compatible_tools", ()))
        return []

    def related_machines(self, entity: LibraryEntity) -> list[LibraryEntity]:
        if self.data_service is not None and self.data_service.is_index_ready():
            relationships = self.data_service.peek_relationships(entity.entity_type, entity.key)
            return self._entities_for(ENTITY_MACHINE, relationships.get("machines", ()))
        if entity.entity_type == ENTITY_EOAT:
            return self._entities_for(ENTITY_MACHINE, getattr(entity.record, "machines", ()))
        if entity.entity_type == ENTITY_TOOL:
            return self._entities_for(ENTITY_MACHINE, getattr(entity.record, "compatible_machines", ()))
        return []

    def related_eoats(self, entity: LibraryEntity) -> list[LibraryEntity]:
        if self.data_service is not None and self.data_service.is_index_ready():
            relationships = self.data_service.peek_relationships(entity.entity_type, entity.key)
            eoats = self._entities_for(ENTITY_EOAT, relationships.get("eoats", ()))
            current = _truthy_text(relationships.get("current_eoat", ""))
            if current and current not in {"Not Indexed", "No Current EOAT"}:
                current_entity = self.entity_for(ENTITY_EOAT, current)
                if current_entity is not None:
                    eoats = [current_entity, *[item for item in eoats if item.key.casefold() != current_entity.key.casefold()]]
            return eoats
        if entity.entity_type == ENTITY_TOOL:
            return self._entities_for(ENTITY_EOAT, getattr(entity.record, "compatible_eoats", ()))
        if entity.entity_type == ENTITY_MACHINE:
            eoats = self._entities_for(ENTITY_EOAT, getattr(entity.record, "compatible_eoats", ()))
            current = _truthy_text(getattr(entity.record, "current_eoat", ""))
            if current:
                current_entity = self.entity_for(ENTITY_EOAT, current)
                if current_entity is not None:
                    eoats = [current_entity, *[item for item in eoats if item.key.casefold() != current_entity.key.casefold()]]
            return eoats
        return []

    def filtered(
        self,
        *,
        query: str = "",
        type_filter: str = "all",
        status_filter: str = "All",
        location_filter: str = "All",
        active_filters: set[str] | None = None,
        limit: int = 10000,
    ) -> list[LibraryEntity]:
        active_filters = active_filters or set()
        with perf_timer(
            _catalog_project_root(self),
            "library.search_filter",
            details={
                "query": query,
                "type_filter": type_filter,
                "status_filter": status_filter,
                "location_filter": location_filter,
                "advanced_filter_count": len(active_filters),
                "candidate_count": len(self.entities),
            },
            source="minimalist_library",
            page_tool="library",
        ):
            if self.data_service is not None and self.data_service.is_index_ready():
                search_result = self.data_service.search(query, {"type": type_filter}, "", 1, limit)
                candidates = []
                for record in search_result.get("items", ()):
                    record_type = str(record.get("record_type", ""))
                    key = str(record.get("eoat_id") or record.get("tool_number") or record.get("machine_number") or "")
                    entity = self.entity_for(record_type, key)
                    if entity is not None:
                        candidates.append(entity)
            else:
                candidates = self._query_entities(query, limit=limit) if query.strip() else list(self.entities)
            results: list[LibraryEntity] = []
            for entity in candidates:
                if type_filter != "all" and entity.entity_type != type_filter:
                    continue
                if status_filter != "All" and not self.matches_filter(entity, status_filter):
                    continue
                if location_filter != "All" and not self.matches_filter(entity, location_filter):
                    continue
                if any(not self.matches_filter(entity, filter_name) for filter_name in active_filters):
                    continue
                results.append(entity)
                if len(results) >= limit:
                    break
            return results

    def grouped_results(self, entities: list[LibraryEntity]) -> dict[str, list[LibraryEntity]]:
        grouped = {"EOATs": [], "Tools": [], "Machines": []}
        for entity in entities:
            if entity.entity_type == ENTITY_EOAT:
                grouped["EOATs"].append(entity)
            elif entity.entity_type == ENTITY_TOOL:
                grouped["Tools"].append(entity)
            elif entity.entity_type == ENTITY_MACHINE:
                grouped["Machines"].append(entity)
        return grouped

    def stats(self) -> dict[str, dict[str, Any]]:
        eoats = [entity for entity in self.entities if entity.entity_type == ENTITY_EOAT]
        tools = [entity for entity in self.entities if entity.entity_type == ENTITY_TOOL]
        machines = [entity for entity in self.entities if entity.entity_type == ENTITY_MACHINE]
        return {
            "eoats": {"total": len(eoats)},
            "tools": {"total": len(tools)},
            "machines": {"total": len(machines)},
        }

    def photo_paths(self, entity: LibraryEntity) -> tuple[str, ...]:
        with perf_timer(
            _catalog_project_root(self),
            "library.card.photo_path_resolution",
            details={"ui_sensitive": "photo_path_resolution", "record_type": entity.entity_type, "record_id": entity.key},
            source="minimalist_library",
            page_tool="library",
        ):
            if self.data_service is not None and self.data_service.is_index_ready():
                paths: list[str] = []
                for photo in self.data_service.peek_photos(entity.entity_type, entity.key):
                    paths.extend(str(candidate) for candidate in photo.get("resolved_path_candidates", ()) or () if str(candidate).strip())
                return tuple(dict.fromkeys(paths))
            record = entity.record
            if entity.entity_type == ENTITY_EOAT:
                photos = getattr(getattr(record, "photos", None), "photos", ()) or ()
                indexed = getattr(getattr(record, "photos", None), "indexed_photos", ()) or ()
                paths = [str(getattr(photo, "path", "") or "") for photo in (*photos, *indexed)]
                return tuple(path for path in paths if path)
            if entity.entity_type == ENTITY_TOOL and self.bundle is not None:
                paths = self.bundle.indexes.photos_by_tool.get(normalized_tool_key(entity.key), ())
                return tuple(path for path in paths if path)
            return ()

    def photo_count(self, entity: LibraryEntity) -> int:
        if self.data_service is not None and self.data_service.is_index_ready():
            return len(self.data_service.peek_photos(entity.entity_type, entity.key))
        if entity.entity_type == ENTITY_EOAT:
            return int(getattr(entity.record, "photo_count", 0) or 0)
        if entity.entity_type == ENTITY_TOOL and self.bundle is not None:
            return len(self.bundle.indexes.photos_by_tool.get(normalized_tool_key(entity.key), ()))
        return 0

    def photo_candidates(self, entity: LibraryEntity, *, limit: int = 1) -> list[tuple[str, list[str]]]:
        if entity.entity_type == ENTITY_MACHINE:
            return []
        candidates: list[tuple[str, list[str]]] = []
        if self.data_service is not None and self.data_service.is_index_ready():
            record = self.data_service.peek_record(entity.entity_type, entity.key) or {}
            preview_paths = [
                str(path)
                for path in record.get("preview_photo_path_candidates", ()) or ()
                if str(path or "").strip()
            ]
            if preview_paths:
                photo_id = _truthy_text(record.get("preview_photo_id")) or f"{entity.entity_type}:{entity.key}:card:preview"
                candidates.append((photo_id, list(dict.fromkeys(preview_paths))))
                return candidates[: max(1, limit)]
            for index, photo in enumerate(self.data_service.peek_photos(entity.entity_type, entity.key)[: max(1, limit)]):
                photo_id = _truthy_text(photo.get("photo_id")) or f"{entity.entity_type}:{entity.key}:card:{index}"
                paths = [
                    *[str(path) for path in photo.get("resolved_path_candidates", ()) or () if str(path or "").strip()],
                    _truthy_text(photo.get("path")),
                ]
                paths = list(dict.fromkeys(path for path in paths if path))
                if paths:
                    candidates.append((photo_id, paths))
            return candidates
        if entity.entity_type == ENTITY_EOAT:
            photo_set = getattr(entity.record, "photos", None)
            photos = [*(getattr(photo_set, "indexed_photos", ()) or ()), *(getattr(photo_set, "photos", ()) or ())]
            for index, photo in enumerate(photos[: max(1, limit)]):
                photo_id = _truthy_text(getattr(photo, "photo_id", "")) or f"{entity.entity_type}:{entity.key}:card:{index}"
                paths = [
                    *[str(path) for path in getattr(photo, "path_candidates", ()) or () if str(path or "").strip()],
                    _truthy_text(getattr(photo, "path", "")),
                    _photo_item_candidate_path(_catalog_project_root(self), photo),
                ]
                paths = list(dict.fromkeys(path for path in paths if path))
                if paths:
                    candidates.append((photo_id, paths))
        return candidates

    def documentation_score(self, entity: LibraryEntity) -> int:
        if self.data_service is not None and self.data_service.is_index_ready():
            docs = self.data_service.peek_documentation_status(entity.entity_type, entity.key)
            return int(docs.get("documentation_score", 0) or 0)
        if entity.entity_type == ENTITY_EOAT:
            return int(getattr(getattr(entity.record, "documentation", None), "score", 0) or 0)
        if entity.entity_type == ENTITY_MACHINE:
            return int(getattr(entity.record, "documentation_score", 0) or 0)
        return 100 if not getattr(entity.record, "warnings", ()) else 68

    def matches_filter(self, entity: LibraryEntity, filter_name: str) -> bool:
        name = str(filter_name or "").strip().casefold()
        text = entity.search_text.casefold()
        record = entity.record
        status_label, _status_tone = card_status_display(entity, self)
        condition, _condition_tone = entity_condition_line(entity, self)
        location = entity_location_line(entity, self)
        haystack = " ".join((text, status_label, condition, location)).casefold()
        if name in {"all", ""}:
            return True
        if name in {"eoat", "eoats"}:
            return entity.entity_type == ENTITY_EOAT
        if name in {"tool", "tools"}:
            return entity.entity_type == ENTITY_TOOL
        if name in {"machine", "machines"}:
            return entity.entity_type == ENTITY_MACHINE
        if name in {"active", "in service"}:
            return card_status_display(entity, self)[1] == "good"
        if name in {"out of service", "inactive"}:
            return card_status_display(entity, self)[0] in {"Out of Service", "Inactive"}
        if name == "in maintenance":
            return "maintenance" in haystack or "repair" in haystack
        if name == "in storage":
            return "storage" in haystack or condition == "In Storage"
        if name == "not indexed":
            return "not indexed" in haystack
        if name == "needs review":
            return bool(getattr(record, "warnings", ())) or self.documentation_score(entity) < 75 or "review" in haystack
        if name in {"plant 4", "plant 3", "cleanroom", "production", "in cabinet", "on machine", "off-machine"}:
            return name in haystack
        if name == "docs good":
            return self.documentation_score(entity) >= 75
        if name == "missing docs":
            return self.documentation_score(entity) < 75
        if name in {"cad missing", "bom missing", "revision missing", "photo folder missing"}:
            keyword = name.replace(" missing", "")
            return keyword in haystack and "missing" in haystack
        if name == "has photos":
            return self.photo_count(entity) > 0
        if name == "missing photos":
            return self.photo_count(entity) == 0
        if name in {"vacuum", "pressure", "mixed air", "robot only", "external peripheral only", "engel", "wittmann", "sytrama", "unknown robot"}:
            if name == "mixed air":
                return "mixed" in haystack and ("air" in haystack or "external" in haystack)
            if name == "unknown robot":
                return entity.entity_type == ENTITY_MACHINE and not (_truthy_text(getattr(record, "robot_type", "")) or _truthy_text(getattr(record, "robot_model", "")))
            return name in haystack
        if name in {"mechanical / gripper", "hybrid", "specialty"}:
            return name.replace(" / ", " ") in haystack.replace("/", " ")
        if name == "high reuse":
            return self._relationship_count(entity) >= 4
        if name == "single machine":
            return len(getattr(record, "machines", ()) or getattr(record, "compatible_machines", ())) == 1
        if name == "missing compatibility":
            if entity.entity_type == ENTITY_EOAT:
                return not getattr(record, "tools", ()) or not getattr(record, "machines", ())
            if entity.entity_type == ENTITY_TOOL:
                return not getattr(record, "compatible_eoats", ()) or not getattr(record, "compatible_machines", ())
            if entity.entity_type == ENTITY_MACHINE:
                return not getattr(record, "compatible_eoats", ()) or not getattr(record, "compatible_tools", ())
        if name == "has tools":
            return bool(getattr(record, "tools", ()) or getattr(record, "compatible_tools", ()))
        if name == "has machines":
            return bool(getattr(record, "machines", ()) or getattr(record, "compatible_machines", ()))
        if name == "no linked tools":
            return not (getattr(record, "tools", ()) or getattr(record, "compatible_tools", ()))
        if name == "no linked machines":
            return not (getattr(record, "machines", ()) or getattr(record, "compatible_machines", ()))
        return name in haystack

    def _query_entities(self, query: str, *, limit: int) -> list[LibraryEntity]:
        folded = query.strip().casefold()
        compact = _compact_key(folded)
        if not folded:
            return list(self.entities)
        scored: list[tuple[tuple[int, str], LibraryEntity]] = []
        for entity in self.entities:
            key = entity.key.casefold()
            title = entity.title.casefold()
            text = entity.search_text.casefold()
            normalized = _compact_key(" ".join((key, title, text)))
            if compact == _compact_key(key) or compact == _compact_key(title):
                score = 0
            elif _compact_key(key).startswith(compact) or _compact_key(title).startswith(compact):
                score = 1
            elif folded in key or folded in title:
                score = 2
            elif all(token in text for token in folded.split()):
                score = 3
            elif compact and compact in normalized:
                score = 4
            else:
                continue
            scored.append(((score, entity.title.casefold()), entity))
        scored.sort(key=lambda item: item[0])
        return [entity for _score, entity in scored[:limit]]

    def _entities_for(self, entity_type: str, keys: Iterable[str]) -> list[LibraryEntity]:
        entities: list[LibraryEntity] = []
        for key in keys or ():
            entity = self.entity_for(entity_type, str(key))
            if entity is not None:
                entities.append(entity)
        return entities

    def _relationship_count(self, entity: LibraryEntity) -> int:
        record = entity.record
        if entity.entity_type == ENTITY_EOAT:
            return len(getattr(record, "machines", ())) + len(getattr(record, "tools", ()))
        if entity.entity_type == ENTITY_TOOL:
            return len(getattr(record, "compatible_machines", ())) + len(getattr(record, "compatible_eoats", ()))
        if entity.entity_type == ENTITY_MACHINE:
            return len(getattr(record, "compatible_tools", ())) + len(getattr(record, "compatible_eoats", ()))
        return 0

    def _build_entities(self, bundle: AtlasDataBundle | None) -> list[LibraryEntity]:
        if self.data_service is not None and self.data_service.is_index_ready():
            entities: list[LibraryEntity] = []
            entities.extend(self._eoat_entity(record) for record in self.data_service.get_eoat_records())
            entities.extend(self._tool_entity(record) for record in self.data_service.get_tool_records())
            entities.extend(self._machine_entity(record) for record in self.data_service.get_machine_records())
            return entities
        if bundle is None:
            return []
        entities: list[LibraryEntity] = []
        entities.extend(self._eoat_entity(record) for record in bundle.eoats)
        entities.extend(self._tool_entity(record) for record in bundle.tools)
        entities.extend(self._machine_entity(record) for record in bundle.machines)
        return entities

    def _eoat_entity(self, record: EOATRecord) -> LibraryEntity:
        doc_score = int(getattr(record.documentation, "score", 0) or 0)
        photo_count = int(getattr(record, "photo_count", 0) or 0)
        badges = [
            ("Docs Good" if doc_score >= 75 else "Missing Docs", "good" if doc_score >= 75 else "warn"),
            (f"Photos {photo_count}" if photo_count else "Missing Photos", "good" if photo_count else "warn"),
        ]
        subtitle = record.eoat_type or record.part_description or "EOAT"
        meta = f"{count_label(len(record.tools), 'tool')} | {count_label(len(record.machines), 'machine')}"
        text = _join_record_text(
            record.eoat_id,
            record.display_id,
            record.audit_ids,
            record.tools,
            record.molds,
            record.parts,
            record.machines,
            record.part_family,
            record.part_description,
            record.eoat_type,
            record.status,
            record.robot_types,
            record.robot_models,
            record.connection_type,
            record.vacuum_info,
            record.pressure_info,
            record.gripper_info,
            record.sensor_info,
            record.tubing_notes,
            record.install_notes,
            record.known_issues,
            record.documentation.status_label,
            record.documentation.missing_fields,
            [warning.title for warning in record.warnings],
            [warning.message for warning in record.warnings],
            [row for row in getattr(record, "source_rows", ())],
        )
        return LibraryEntity(ENTITY_EOAT, record.eoat_id, record.eoat_id, subtitle, meta, record, tuple(badges), text)

    def _tool_entity(self, record: ToolRecord) -> LibraryEntity:
        warnings = int(getattr(record, "warning_count", 0) or 0)
        badges = [
            (f"EOATs {len(record.compatible_eoats)}" if record.compatible_eoats else "Missing Compatibility", "good" if record.compatible_eoats else "warn"),
            (f"Machines {len(record.compatible_machines)}", "info"),
        ]
        if warnings:
            badges.append((f"{warnings} Warnings", "warn"))
        subtitle = record.part_description or record.part_family or "Tool / Mold / Part"
        meta = f"{count_label(len(record.compatible_machines), 'machine')} | {count_label(len(record.compatible_eoats), 'EOAT')}"
        text = _join_record_text(
            record.tool,
            record.label,
            record.molds,
            record.parts,
            record.part_family,
            record.part_description,
            record.compatible_eoats,
            record.compatible_machines,
            record.source,
            [warning.title for warning in record.warnings],
            [warning.message for warning in record.warnings],
            [row for row in getattr(record, "source_rows", ())],
        )
        return LibraryEntity(ENTITY_TOOL, record.tool, record.tool, subtitle, meta, record, tuple(badges), text)

    def _machine_entity(self, record: MachineRecord) -> LibraryEntity:
        current = machine_current_eoat_display(record)
        doc_score = int(getattr(record, "documentation_score", 0) or 0)
        badges = [
            (f"EOATs {len(record.compatible_eoats)}" if record.compatible_eoats else "Missing Compatibility", "good" if record.compatible_eoats else "warn"),
            ("Docs Good" if doc_score >= 75 else "Missing Docs", "good" if doc_score >= 75 else "warn"),
        ]
        subtitle = f"{record.robot_type or record.robot_model or 'Robot type unknown'} | {self._area_label(record)}"
        meta = f"Current EOAT: {current.value} | {count_label(len(record.compatible_tools), 'tool')}"
        text = _join_record_text(
            record.machine,
            record.label,
            record.robot_type,
            record.robot_model,
            record.controller,
            record.compatible_eoats,
            record.compatible_tools,
            record.compatible_parts,
            record.current_eoat,
            record.current_eoat_status,
            record.current_eoat_source,
            record.current_eoat_resolution_reason,
            [warning.title for warning in record.warnings],
            [warning.message for warning in record.warnings],
            [row for row in getattr(record, "source_rows", ())],
        )
        return LibraryEntity(ENTITY_MACHINE, record.machine, machine_label(record.machine), subtitle, meta, record, tuple(badges), text)

    def _area_label(self, record: MachineRecord) -> str:
        blob = _join_record_text(record.robot_type, record.robot_model, record.controller, getattr(record, "source_rows", ()))
        return "Cleanroom" if "cleanroom" in blob.casefold() else "Production"

    def _norm(self, entity_type: str, key: str) -> str:
        if entity_type == ENTITY_EOAT:
            return normalized_eoat_key(key)
        if entity_type == ENTITY_MACHINE:
            return normalized_machine_key(key)
        if entity_type == ENTITY_TOOL:
            return normalized_tool_key(key)
        return str(key or "").casefold()


def _compact_key(value: str) -> str:
    return "".join(character for character in str(value or "").casefold() if character.isalnum())


def _join_record_text(*values: Any) -> str:
    pieces: list[str] = []
    for value in values:
        if isinstance(value, dict):
            pieces.extend(str(item) for item in value.values() if _truthy_text(item))
        elif isinstance(value, (tuple, list, set)):
            pieces.append(_join_record_text(*value))
        elif _truthy_text(value):
            pieces.append(str(value))
    return " ".join(piece for piece in pieces if piece)


class LibraryScrim(QWidget):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.hide()

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        event.accept()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 8, 18, 62))


class AnimatedGlassCard(GlassPanel):
    clicked = Signal()
    detail_requested = Signal()

    def __init__(self, parent=None, *, radius: int = 12, compact: bool = False):
        super().__init__(parent, radius=radius)
        self._hover_progress = 0.0
        self._compact = compact
        self._hover_animation = QPropertyAnimation(self, b"hoverProgress", self)
        self._hover_animation.setDuration(animation_duration(160))
        self._hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def get_hover_progress(self) -> float:
        return self._hover_progress

    def set_hover_progress(self, value: float) -> None:
        self._hover_progress = max(0.0, min(1.0, float(value)))
        self.update()

    hoverProgress = Property(float, get_hover_progress, set_hover_progress)

    def enterEvent(self, event) -> None:
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.detail_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _animate_hover(self, target: float) -> None:
        self._hover_animation.stop()
        self._hover_animation.setStartValue(self._hover_progress)
        self._hover_animation.setEndValue(target)
        self._hover_animation.start()


class AnimatedLibraryButton(QPushButton):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _apply_modern_style(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class LibraryStatusLine(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dot = StatusDot(self)
        self.label = QLabel("Data loading...", self)
        self.label.setObjectName("MinimalistStatusText")

    def set_status(self, text: str, *, ready: bool) -> None:
        self.label.setText(text)
        self.dot.set_ready(ready)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.dot.setGeometry(0, 8, 14, 14)
        self.label.setGeometry(24, 1, self.width() - 24, 26)


class AtlasMinimalistLibraryPage(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.bundle = None
        self.setObjectName("AtlasMinimalistLibraryPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.library_content = MinimalistLibraryContent(controller)
        from .shell import AtlasMinimalistShell

        self.shell = AtlasMinimalistShell(controller, self.library_content)
        self.shell.top_bar.back_requested.connect(self.library_content.go_back_to_library)
        self.library_content.state_changed.connect(self._sync_topbar_back)
        self._sync_topbar_back(self.library_content.state)
        layout.addWidget(self.shell)

    def set_bundle(self, bundle) -> None:
        with perf_timer(
            str(getattr(bundle, "project_root", "") or _controller_project_root(self.controller)),
            "library.page.set_bundle",
            details={"bundle_loaded": bundle is not None},
            source="minimalist_library",
            page_tool="library",
        ):
            self.bundle = bundle
            self.library_content.set_bundle(bundle)
            self.shell.set_bundle(bundle)

    def refresh(self) -> None:
        self.library_content.set_bundle(self.bundle)

    def page_shown(self) -> None:
        with perf_timer(
            str(getattr(self.bundle, "project_root", "") or _controller_project_root(self.controller)),
            "library.open",
            details={"state": self.library_content.state, "bundle_loaded": self.bundle is not None},
            source="minimalist_library",
            page_tool="library",
        ):
            self.shell.close_overlays()
            self.shell.set_active_nav("library")
            self.library_content.set_bundle(self.bundle)
            self.shell.setFocus(Qt.FocusReason.OtherFocusReason)

    def open_search_overlay(self) -> None:
        self.shell.open_search()

    def focus_library_search(self) -> None:
        self.library_content.focus_search()

    def select_entity(self, entity_type: str, key: str) -> bool:
        return self.library_content.select_entity(entity_type, key)

    def show_toast(self, message: str) -> None:
        self.library_content.show_toast(message)

    def _shutdown_page_services(self) -> None:
        try:
            close_overlays = getattr(self.shell, "close_overlays", None)
            if callable(close_overlays):
                close_overlays()
        except RuntimeError:
            pass
        try:
            remove_filter = getattr(self.shell, "remove_app_event_filter", None)
            if callable(remove_filter):
                remove_filter()
        except RuntimeError:
            pass
        try:
            self.library_content.shutdown_photo_service()
        except RuntimeError:
            pass

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.Destroy:
            self._shutdown_page_services()
        return super().event(event)

    def closeEvent(self, event) -> None:
        self._shutdown_page_services()
        super().closeEvent(event)

    def _sync_topbar_back(self, state: str) -> None:
        self.shell.top_bar.set_back_visible(state == "record")


class LibraryControlsShim:
    def __init__(self, content: "MinimalistLibraryContent"):
        self.content = content

    @property
    def search_bar(self) -> "LibrarySearchBar | None":
        return self.content._active_search_bar()


class MinimalistLibraryContent(QWidget):
    state_changed = Signal(str)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.bundle: AtlasDataBundle | None = None
        self.data_service = LibraryDataService(_controller_project_root(controller))
        self.data_service.load_cached_index()
        self._service_generation = self.data_service.generation
        self.photo_service = PhotoService(_controller_project_root(controller), self)
        self.catalog = LibraryCatalog(None, controller, self.data_service, self.photo_service)
        self.state = "hub"
        self.scope_type = ENTITY_EOAT
        self.browse_query = ""
        self.selected_entity: LibraryEntity | None = None
        self.active_lenses: set[str] = set()
        self.active_lens_tokens: dict[str, str] = {}
        self._record_back_stack: list[dict[str, Any]] = []
        self.current_view: QWidget | None = None
        self._record_view: LibraryRecordStateView | None = None
        self._active_photo_contexts: set[str] = set()
        self._loading_skeleton_visible = False
        self._cache_refresh_pending = bool(self.data_service.stale or (not self.data_service.is_index_ready() and _controller_project_root(controller)))
        self.controls = LibraryControlsShim(self)
        self.setObjectName("MinimalistLibraryContent")
        self.setMouseTracking(True)
        self.setStyleSheet(LIBRARY_WIDGET_STYLES)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(38, 26, 38, 32)
        layout.setSpacing(0)

        self.body_scroll = QScrollArea(self)
        self.body_scroll.setObjectName("LibraryBodyScroll")
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body_widget = QWidget()
        self.body_widget.setObjectName("LibraryBodyWidget")
        self.body_layout = QVBoxLayout(self.body_widget)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(0)
        self.body_scroll.setWidget(self.body_widget)
        layout.addWidget(self.body_scroll)

        self._body_opacity = QGraphicsOpacityEffect(self.body_widget)
        self._body_opacity.setOpacity(1.0)
        self.body_widget.setGraphicsEffect(self._body_opacity)
        self._body_fade = QPropertyAnimation(self._body_opacity, b"opacity", self)
        self._body_fade.setDuration(animation_duration(190))
        self._body_fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.status = LibraryStatusLine(self)
        self.toast = MinimalistToast(self)
        self.toast.hide()
        self._index_poll = QTimer(self)
        self._index_poll.setInterval(750)
        self._index_poll.timeout.connect(self._refresh_from_cache_if_ready)
        if not self.data_service.is_index_ready() and _controller_project_root(controller):
            self._index_poll.start()
        elif self.data_service.is_index_ready():
            if self.data_service.stale:
                self._set_status("Refreshing Library Index...", ready=True, indicator="refreshing")
                self._index_poll.start()
            else:
                self._set_status("Library index loaded from cache.", ready=True, indicator="idle")
        self.render_body()

    def set_bundle(self, bundle) -> None:
        with perf_timer(
            str(getattr(bundle, "project_root", "") or _controller_project_root(self.controller)),
            "library.content.set_bundle",
            details={"bundle_loaded": bundle is not None, "state": self.state},
            source="minimalist_library",
            page_tool="library",
        ):
            self.bundle = bundle
            if bundle is not None:
                self.data_service.rebuild_index_from_bundle(bundle)
                self._service_generation = self.data_service.generation
                self.photo_service.set_project_root(getattr(bundle, "project_root", "") or _controller_project_root(self.controller))
            self.catalog = LibraryCatalog(bundle, self.controller, self.data_service, self.photo_service)
            if self.selected_entity is not None:
                self.selected_entity = self.catalog.entity_for(self.selected_entity.entity_type, self.selected_entity.key)
                if self.selected_entity is None and self.state == "record":
                    self.state = "hub"
            if bundle is not None:
                self._set_status(loaded_status_text(bundle), ready=True, indicator="idle")
            elif self.data_service.is_index_ready():
                if self.data_service.stale:
                    self._cache_refresh_pending = True
                    self._set_status("Refreshing Library Index...", ready=True, indicator="refreshing")
                    self._index_poll.start()
                else:
                    self._set_status("Library index loaded from cache.", ready=True, indicator="idle")
            else:
                self._cache_refresh_pending = True
                self._set_status("Building Library Index...", ready=False, indicator="indexing")
                if _controller_project_root(self.controller):
                    self._index_poll.start()
            self.render_body()

    def _refresh_from_cache_if_ready(self) -> None:
        if not self.data_service.is_index_ready():
            return
        if self.data_service.generation == self._service_generation and self.catalog.entities:
            if self.data_service.stale:
                self._cache_refresh_pending = True
                self._set_status("Refreshing Library Index...", ready=True, indicator="refreshing")
            else:
                self._index_poll.stop()
            return
        self._service_generation = self.data_service.generation
        self.catalog = LibraryCatalog(self.bundle, self.controller, self.data_service, self.photo_service)
        if self.selected_entity is not None:
            self.selected_entity = self.catalog.entity_for(self.selected_entity.entity_type, self.selected_entity.key)
            if self.selected_entity is None and self.state == "record":
                self.state = "hub"
        refresh_was_pending = self._cache_refresh_pending
        self._set_status("Library index loaded from cache.", ready=True, indicator="complete")
        self.render_body()
        if not self.data_service.stale:
            self._index_poll.stop()
            self._cache_refresh_pending = False
            if refresh_was_pending:
                self.show_toast("Library index refreshed.")

    def show_toast(self, message: str) -> None:
        if not str(message or "").strip():
            return
        _log_ui_marker(
            str(getattr(self.bundle, "project_root", "") or _controller_project_root(self.controller)),
            "ui.toast.show",
            details={"message": str(message or "")[:160]},
            page_tool="library",
        )
        self.toast.show_message(message)

    def _set_status(self, text: str, *, ready: bool, indicator: str = "") -> None:
        self.status.set_status(text, ready=ready)
        root = str(getattr(self.bundle, "project_root", "") or _controller_project_root(self.controller))
        if indicator in {"refreshing", "indexing"}:
            _log_ui_marker(
                root,
                "ui.cache_refresh_indicator.show",
                details={"text": text, "indicator": indicator, "ready": ready},
                page_tool="library",
            )
        elif indicator in {"idle", "complete", "failed"}:
            _log_ui_marker(
                root,
                "ui.cache_refresh_indicator.hide",
                details={"text": text, "indicator": indicator, "ready": ready},
                page_tool="library",
            )

    def _show_skeleton_state(self, message: str) -> None:
        if self._loading_skeleton_visible:
            return
        self._loading_skeleton_visible = True
        _log_ui_marker(
            str(getattr(self.bundle, "project_root", "") or _controller_project_root(self.controller)),
            "ui.skeleton.show",
            details={"state": self.state, "message": message, "surface": "library"},
            page_tool="library",
        )

    def _hide_skeleton_state(self) -> None:
        if not self._loading_skeleton_visible:
            return
        self._loading_skeleton_visible = False
        _log_ui_marker(
            str(getattr(self.bundle, "project_root", "") or _controller_project_root(self.controller)),
            "ui.skeleton.hide",
            details={"state": self.state, "surface": "library"},
            page_tool="library",
        )

    def focus_search(self) -> None:
        search_bar = self._active_search_bar()
        if search_bar is None:
            self.state = "browse"
            self.render_body()
            search_bar = self._active_search_bar()
        if search_bar is not None:
            search_bar.input.setFocus(Qt.FocusReason.ShortcutFocusReason)
            search_bar.input.selectAll()

    def focus_search_text(self, text: str) -> None:
        if self.state == "record":
            self.state = "browse"
        self.browse_query = text
        self.render_body()
        search_bar = self._active_search_bar()
        if search_bar is not None:
            search_bar.input.setFocus(Qt.FocusReason.ShortcutFocusReason)
            search_bar.set_query_text(text)
        self._refresh_current_view()

    def handle_escape(self) -> bool:
        view = self.current_view
        if isinstance(view, LibraryBrowseStateView) and view.lenses_open:
            view.set_lenses_open(False)
            return True
        search_bar = self._active_search_bar()
        if search_bar is not None:
            if search_bar.input.text():
                search_bar.input.clear()
                return True
            if search_bar.input.hasFocus():
                search_bar.input.clearFocus()
                return True
        if self.state == "record":
            self._go_back()
            return True
        return False

    def select_entity(self, entity_type: str, key: str) -> bool:
        entity = self.catalog.entity_for(entity_type, key)
        if entity is None:
            return False
        self._show_record(entity)
        return True

    def render_body(self) -> None:
        with perf_timer(
            str(getattr(self.bundle, "project_root", "") or _controller_project_root(self.controller)),
            "library.render_body",
            details={"state": self.state, "scope_type": self.scope_type, "bundle_loaded": self.bundle is not None},
            source="minimalist_library",
            page_tool="library",
        ):
            self._body_fade.stop()
            self._body_opacity.setOpacity(0.0 if not prefers_reduced_motion() else 1.0)
            self._clear_body_layout(preserve=self._record_view)
            if not self.catalog.entities and not self.data_service.is_index_ready():
                loading_message = "Building Library Index..." if _controller_project_root(self.controller) else "Loading cached records..."
                self._show_skeleton_state(loading_message)
                self.current_view = LibraryBrowseStateView(
                    self.catalog,
                    self.scope_type,
                    self.browse_query,
                    self.active_lenses,
                    self._show_hub,
                    self._show_record,
                    self._lens_toggled,
                    self.clear_lenses,
                    self.register_photo_context,
                    loading_message=loading_message,
                )
            elif self.state == "record" and self.selected_entity is not None:
                self._hide_skeleton_state()
                try:
                    if self._record_view is None:
                        self._record_view = LibraryRecordStateView(self.catalog, self.selected_entity, self._go_back, self._show_record)
                    else:
                        self._record_view.bind_record(self.catalog, self.selected_entity)
                    self.current_view = self._record_view
                except Exception as exc:
                    LOGGER.exception("Failed to open record page: %s %s", self.selected_entity.entity_type, self.selected_entity.key)
                    log_perf_marker(
                        str(getattr(self.bundle, "project_root", "") or _controller_project_root(self.controller)),
                        "record.open.failed",
                        details={
                            "record_type": self.selected_entity.entity_type,
                            "record_id": self.selected_entity.key,
                            "error": f"{type(exc).__name__}: {exc}",
                        },
                        source="minimalist_library",
                        page_tool="library_record",
                    )
                    _log_ui_marker(
                        str(getattr(self.bundle, "project_root", "") or _controller_project_root(self.controller)),
                        "ui.error_state.show",
                        details={
                            "record_type": self.selected_entity.entity_type,
                            "record_id": self.selected_entity.key,
                            "error": f"{type(exc).__name__}: {exc}",
                        },
                        page_tool="library_record",
                    )
                    if self._record_view is not None:
                        self._record_view.setParent(None)
                        self._record_view.deleteLater()
                    self._record_view = None
                    self.current_view = LibraryRecordErrorPanel(self.selected_entity.entity_type, self.selected_entity.key)
            else:
                self._hide_skeleton_state()
                self.current_view = LibraryBrowseStateView(
                    self.catalog,
                    self.scope_type,
                    self.browse_query,
                    self.active_lenses,
                    self._show_hub,
                    self._show_record,
                    self._lens_toggled,
                    self.clear_lenses,
                    self.register_photo_context,
                )
            if isinstance(self.current_view, LibraryRecordStateView):
                self.body_layout.addWidget(self.current_view, 1)
            else:
                self.body_layout.addWidget(self.current_view)
                self.body_layout.addStretch(1)
            self.current_view.show()
            if self.state == "record":
                QTimer.singleShot(0, self._log_record_navigation_state)
            self.state_changed.emit(self.state)
            self._fade_body_in()

    def _clear_body_layout(self, *, preserve: QWidget | None = None) -> None:
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            if preserve is not None and widget is preserve:
                widget.hide()
                continue
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        status_width = min(340, max(220, self.width() - 80))
        self.status.setGeometry(self.width() - status_width - 20, self.height() - 42, status_width, 30)
        toast_width = min(720, max(260, self.width() - 90))
        self.toast.setGeometry((self.width() - toast_width) // 2, self.height() - 116, toast_width, 72)

    def clear_lenses(self) -> None:
        self.active_lenses.clear()
        self.active_lens_tokens.clear()
        self._refresh_current_view()

    def _lens_toggled(self, filter_name: str, checked: bool) -> None:
        if checked:
            self.active_lenses.add(filter_name)
            self.active_lens_tokens[filter_name] = filter_name.casefold().replace(" ", "-")
        else:
            self.active_lenses.discard(filter_name)
            self.active_lens_tokens.pop(filter_name, None)
        self._refresh_current_view()

    def _show_hub(self) -> None:
        self._cancel_photo_contexts()
        self._record_back_stack.clear()
        self.state = "hub"
        self.scope_type = ENTITY_EOAT
        self.selected_entity = None
        self.render_body()

    def _show_browse(self, entity_type: str = ENTITY_EOAT, *, preserve_lenses: bool = False) -> None:
        self._cancel_photo_contexts(prefixes=("library:", "record:", "photos:", "lightbox:"))
        self._record_back_stack.clear()
        self.state = "browse"
        self.scope_type = entity_type if entity_type in {ENTITY_EOAT, ENTITY_TOOL, ENTITY_MACHINE} else ENTITY_EOAT
        if not preserve_lenses:
            self.active_lenses.clear()
            self.active_lens_tokens.clear()
        self.selected_entity = None
        self.render_body()

    def _show_record(self, entity: LibraryEntity, *, push_context: bool = True) -> None:
        with perf_timer(
            _catalog_project_root(self.catalog),
            f"record.open.{entity.entity_type}",
            details={"record_type": entity.entity_type, "record_id": entity.key, "push_context": push_context},
            source="minimalist_library",
            page_tool="library_record",
        ):
            if push_context:
                self._record_back_stack.append(self._snapshot_context())
            self._cancel_photo_contexts(prefixes=("library:", "record:", "photos:", "lightbox:"))
            self.state = "record"
            self.scope_type = entity.entity_type
            self.selected_entity = entity
            recorder = getattr(self.controller, "record_recent", None)
            if callable(recorder):
                recorder(entity.entity_type, entity.key)
            self.render_body()
            _log_ui_marker(
                _catalog_project_root(self.catalog),
                "ui.page_transition.library_to_record",
                details={"record_type": entity.entity_type, "record_id": entity.key, "push_context": push_context},
                page_tool="library_record",
            )

    def go_back_to_library(self) -> None:
        LOGGER.debug("Back to Library clicked")
        try:
            self._go_back()
        except Exception:
            LOGGER.exception("Back to Library navigation failed")

    def _snapshot_context(self) -> dict[str, Any]:
        view = self.current_view
        query = self.browse_query
        browse_view_state: dict[str, Any] = {}
        if isinstance(view, LibraryBrowseStateView):
            query = view.query_text()
            browse_view_state = view.snapshot_state()
        state = "browse" if self.state == "hub" else self.state
        return {
            "state": state,
            "scope_type": self.scope_type,
            "browse_query": query,
            "active_lenses": set(self.active_lenses),
            "active_lens_tokens": dict(self.active_lens_tokens),
            "browse_view_state": browse_view_state,
        }

    def _restore_context(self, context: dict[str, Any]) -> None:
        self.state = str(context.get("state") or "hub")
        self.scope_type = str(context.get("scope_type") or ENTITY_EOAT)
        self.browse_query = str(context.get("browse_query") or "")
        self.active_lenses = set(context.get("active_lenses") or ())
        self.active_lens_tokens = dict(context.get("active_lens_tokens") or {})
        self.selected_entity = None
        self.render_body()
        view = self.current_view
        if isinstance(view, LibraryBrowseStateView):
            view.restore_view_state(dict(context.get("browse_view_state") or {}))

    def _go_back(self) -> None:
        root = str(getattr(self.bundle, "project_root", "") or _controller_project_root(self.controller))
        previous_record = {
            "record_type": getattr(self.selected_entity, "entity_type", ""),
            "record_id": getattr(self.selected_entity, "key", ""),
        }
        self._cancel_photo_contexts(prefixes=("record:", "photos:", "lightbox:"))
        while self._record_back_stack:
            context = self._record_back_stack.pop()
            LOGGER.debug("Previous library state: %s", self._loggable_context(context))
            LOGGER.debug("Navigating to Library page")
            self._restore_context(context)
            _log_ui_marker(
                root,
                "ui.page_transition.record_to_library",
                details={**previous_record, "restored_state": self._loggable_context(context)},
                page_tool="library",
            )
            return
        fallback = {
            "state": "browse",
            "scope_type": self.scope_type if self.scope_type in {ENTITY_EOAT, ENTITY_TOOL, ENTITY_MACHINE} else ENTITY_EOAT,
            "browse_query": self.browse_query,
            "active_lenses": set(self.active_lenses),
            "active_lens_tokens": dict(self.active_lens_tokens),
            "browse_view_state": {},
        }
        LOGGER.debug("Previous library state unavailable; using fallback: %s", self._loggable_context(fallback))
        LOGGER.debug("Navigating to Library page")
        self._restore_context(fallback)
        _log_ui_marker(
            root,
            "ui.page_transition.record_to_library",
            details={**previous_record, "restored_state": self._loggable_context(fallback), "fallback": True},
            page_tool="library",
        )

    def _loggable_context(self, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "state": context.get("state"),
            "scope_type": context.get("scope_type"),
            "browse_query": context.get("browse_query"),
            "active_lenses": sorted(context.get("active_lenses") or ()),
            "active_lens_tokens": dict(context.get("active_lens_tokens") or {}),
            "browse_view_state": dict(context.get("browse_view_state") or {}),
        }

    def register_photo_context(self, context_id: str) -> None:
        context = str(context_id or "").strip()
        if context:
            self._active_photo_contexts.add(context)

    def _cancel_photo_contexts(self, prefixes: tuple[str, ...] = ()) -> None:
        service = getattr(self, "photo_service", None)
        if service is None:
            return
        cancel_context = getattr(service, "cancel_context", None)
        contexts = list(self._active_photo_contexts)
        for context in contexts:
            if not prefixes or any(context.startswith(prefix) for prefix in prefixes):
                if callable(cancel_context):
                    cancel_context(context)
                self._active_photo_contexts.discard(context)

    def shutdown_photo_service(self) -> None:
        self._index_poll.stop()
        service = getattr(self, "photo_service", None)
        if service is None:
            return
        shutdown = getattr(service, "shutdown", None)
        if callable(shutdown):
            shutdown()

    def closeEvent(self, event) -> None:
        self.shutdown_photo_service()
        super().closeEvent(event)

    def _active_search_bar(self) -> "LibrarySearchBar | None":
        view = self.current_view
        search_bar = getattr(view, "search_bar", None)
        return search_bar if isinstance(search_bar, LibrarySearchBar) else None

    def _refresh_current_view(self) -> None:
        view = self.current_view
        if isinstance(view, LibraryBrowseStateView):
            self.browse_query = view.query_text()
            view.set_lenses(self.active_lenses)
            view._search_debounce.stop()
            view.refresh(interaction="external")

    def _fade_body_in(self) -> None:
        if prefers_reduced_motion():
            self._body_opacity.setOpacity(1.0)
            return
        self._body_fade.stop()
        self._body_fade.setStartValue(self._body_opacity.opacity())
        self._body_fade.setEndValue(1.0)
        self._body_fade.start()

    def _log_record_navigation_state(self) -> None:
        view = self.current_view
        root = str(getattr(self.bundle, "project_root", "") or _controller_project_root(self.controller))
        if not root:
            return
        hero = view.findChild(RecordHeroPanel) if view is not None else None
        tabs = view.findChild(RecordTabBar) if view is not None else None
        overview = view.findChild(RecordOverviewTab) if view is not None else None
        relationship = view.findChild(RelationshipOverviewPanel) if view is not None else None
        log_perf_marker(
            root,
            "record.navigation.debug_state",
            details={
                "state": self.state,
                "record_type": getattr(self.selected_entity, "entity_type", ""),
                "record_id": getattr(self.selected_entity, "key", ""),
                "view_type": type(view).__name__ if view is not None else "",
                "record_page_visible": bool(view is not None and view.isVisible()),
                "record_page_size": [view.width(), view.height()] if view is not None else [0, 0],
                "content_widget_size": [self.body_widget.width(), self.body_widget.height()],
                "body_opacity": round(float(self._body_opacity.opacity()), 3),
                "hero_visible": bool(hero is not None and hero.isVisible()),
                "tabs_visible": bool(tabs is not None and tabs.isVisible()),
                "overview_visible": bool(overview is not None and overview.isVisible()),
                "relationship_canvas_visible": bool(relationship is not None and relationship.isVisible()),
                "child_widget_count": len(view.findChildren(QWidget)) if view is not None else 0,
            },
            source="minimalist_library",
            page_tool="library_record",
        )


class LibraryLoadingPanel(GlassPanel):
    def __init__(self, parent=None):
        super().__init__(parent, radius=18, streaks=True)
        self.setObjectName("LibraryLoadingPanel")
        self.set_glass(alpha=104, border_alpha=70, border_color=QColor("#7fb1ff"))
        self.setMinimumHeight(540)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 150, 36, 36)
        layout.setSpacing(12)
        title = QLabel("Loading library records")
        title.setObjectName("LibraryPanelHeading")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel("EOATs, tools, and machines will appear here as soon as Atlas data is ready.")
        subtitle.setObjectName("LibraryMutedText")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(1)


class LibrarySkeletonCard(QWidget):
    def __init__(self, *, variant: str = "grid", parent=None):
        super().__init__(parent)
        self.variant = "list" if variant == "list" else "grid"
        self._pulse = 0.34
        self.setObjectName("LibrarySkeletonCard")
        if self.variant == "list":
            self.setMinimumHeight(LIST_CARD_HEIGHT)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            self.setFixedSize(BROWSE_CARD_WIDTH, BROWSE_CARD_HEIGHT)
        self._animation = QPropertyAnimation(self, b"skeletonPulse", self)
        self._animation.setDuration(animation_duration(1180))
        self._animation.setStartValue(0.28)
        self._animation.setEndValue(0.62)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._animation.setLoopCount(-1)
        if not prefers_reduced_motion():
            self._animation.start()

    def get_skeleton_pulse(self) -> float:
        return self._pulse

    def set_skeleton_pulse(self, value: float) -> None:
        self._pulse = max(0.0, min(1.0, float(value)))
        self.update()

    skeletonPulse = Property(float, get_skeleton_pulse, set_skeleton_pulse)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        painter.fillPath(path, QColor(6, 20, 43, 172))
        painter.setPen(QPen(QColor(66, 142, 255, 52 + round(42 * self._pulse)), 1.1))
        painter.drawPath(path)

        def bar(x: float, y: float, w: float, h: float, alpha: int = 80) -> None:
            bar_path = QPainterPath()
            bar_path.addRoundedRect(QRectF(x, y, w, h), min(6, h / 2), min(6, h / 2))
            painter.fillPath(bar_path, QColor(93, 150, 214, round(alpha * self._pulse)))

        if self.variant == "list":
            thumb = QRectF(rect.left() + 18, rect.top() + 18, 120, rect.height() - 36)
            thumb_path = QPainterPath()
            thumb_path.addRoundedRect(thumb, 7, 7)
            painter.fillPath(thumb_path, QColor(5, 14, 29, 190))
            left = thumb.right() + 22
            bar(left, rect.top() + 26, min(260, rect.width() - left - 36), 16, 92)
            bar(left, rect.top() + 54, min(360, rect.width() - left - 36), 11, 66)
            bar(left, rect.top() + 82, min(220, rect.width() - left - 36), 10, 54)
            return

        thumb = QRectF(rect.left() + 16, rect.top() + 16, rect.width() - 32, 92)
        thumb_path = QPainterPath()
        thumb_path.addRoundedRect(thumb, 7, 7)
        painter.fillPath(thumb_path, QColor(5, 14, 29, 192))
        bar(rect.left() + 18, rect.top() + 124, rect.width() * 0.62, 15, 92)
        bar(rect.left() + 18, rect.top() + 151, rect.width() * 0.78, 10, 64)
        bar(rect.left() + 18, rect.top() + 184, rect.width() * 0.38, 11, 54)
        bar(rect.right() - 104, rect.bottom() - 34, 82, 20, 58)


class LibraryRecordErrorPanel(GlassPanel):
    def __init__(self, record_type: str, record_id: str, parent=None):
        super().__init__(parent, radius=18, streaks=True)
        self.setObjectName("LibraryRecordErrorPanel")
        self.set_glass(alpha=104, border_alpha=78, border_color=QColor("#ffb145"), fill_color=QColor("#061226"))
        self.setMinimumHeight(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 120, 36, 36)
        layout.setSpacing(12)
        title = QLabel("Unable to load record")
        title.setObjectName("LibraryPanelHeading")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel(f"{TYPE_LABELS.get(record_type, record_type).rstrip('s')} {record_id}")
        subtitle.setObjectName("LibraryMutedText")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(1)


class LibraryBrowseStateView(QWidget):
    def __init__(
        self,
        catalog: LibraryCatalog,
        scope_type: str,
        query: str,
        active_lenses: set[str],
        back_callback,
        record_callback,
        lens_callback,
        clear_callback,
        photo_context_callback=None,
        loading_message: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.catalog = catalog
        self.scope_type = scope_type if scope_type in {ENTITY_EOAT, ENTITY_TOOL, ENTITY_MACHINE} else ENTITY_EOAT
        self.record_callback = record_callback
        self.lens_callback = lens_callback
        self.clear_callback = clear_callback
        self.photo_context_callback = photo_context_callback
        self.loading_message = str(loading_message or "")
        self.active_lenses = set(active_lenses)
        self.page_index = 0
        self.view_mode = "grid"
        self.lenses_open = False
        self._rendered_columns = 0
        self._rendered_card_width = 0
        self._last_grid_width = 0
        self._last_rendered_keys: tuple[tuple[str, str], ...] = ()
        self._last_page_count = 1
        self._last_filtered_count = 0
        self._last_page_size = GRID_PAGE_SIZE
        self._thumbnail_context_id = ""
        self._restoring_state = False
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(SEARCH_DEBOUNCE_MS)
        self._search_debounce.timeout.connect(self._execute_debounced_search)
        self._photo_resume_timer = QTimer(self)
        self._photo_resume_timer.setSingleShot(True)
        self._photo_resume_timer.setInterval(INTERACTION_IDLE_MS)
        self._photo_resume_timer.timeout.connect(self._resume_photo_prefetch)
        self.setObjectName("LibraryBrowseStateView")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 64, 4, 28)
        layout.setSpacing(18)

        title = QLabel("Library")
        title.setObjectName("LibraryMainTitle")
        subtitle = QLabel("Browse and manage all EOATs, Tools, and Machines in one place.")
        subtitle.setObjectName("LibraryMainSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.filter_bar = CatalogFilterBar(self)
        self.search_bar = self.filter_bar.search_bar
        self.search_bar.input.setText(query)
        self.filter_bar.search_changed.connect(self._query_changed)
        self.filter_bar.filters_changed.connect(self._filters_changed)
        self.filter_bar.advanced_requested.connect(lambda: self.set_lenses_open(not self.lenses_open))
        self.filter_bar.clear_requested.connect(self._clear_all)
        layout.addWidget(self.filter_bar)

        self.active_chip_host = QWidget()
        self.active_chip_host.setObjectName("LibraryActivePillHost")
        self.active_chip_layout = QHBoxLayout(self.active_chip_host)
        self.active_chip_layout.setContentsMargins(0, 0, 0, 0)
        self.active_chip_layout.setSpacing(8)
        layout.addWidget(self.active_chip_host)

        selector_row = QHBoxLayout()
        selector_row.setContentsMargins(0, 0, 0, 0)
        selector_row.setSpacing(14)
        self.category_cards: dict[str, CategorySelectorCard] = {}
        stats = self.catalog.stats()
        for entity_type, glyph, count in (
            (ENTITY_EOAT, "eoat", stats["eoats"]["total"]),
            (ENTITY_TOOL, "grid", stats["tools"]["total"]),
            (ENTITY_MACHINE, "machine", stats["machines"]["total"]),
        ):
            card = CategorySelectorCard(TYPE_LABELS[entity_type], glyph, count)
            card.clicked.connect(lambda entity_type=entity_type: self._select_category(entity_type))
            self.category_cards[entity_type] = card
            selector_row.addWidget(card, 1)
        selector_row.addStretch(1)

        self.sort_dropdown = FilterDropdown("Sort by", SORT_OPTIONS, compact=True)
        self.sort_dropdown.combo.currentTextChanged.connect(self._sort_changed)
        self.sort_dropdown.setFixedWidth(250)
        selector_row.addWidget(self.sort_dropdown)
        self.grid_button = IconToggleButton("grid", "Grid view")
        self.grid_button.setChecked(True)
        self.grid_button.clicked.connect(lambda: self._set_view_mode("grid"))
        self.list_button = IconToggleButton("list", "List view")
        self.list_button.clicked.connect(lambda: self._set_view_mode("list"))
        toggle_host = GlassPanel(radius=8)
        toggle_host.setObjectName("LibraryViewSelector")
        toggle_host.set_glass(alpha=80, border_alpha=70, border_color=QColor("#426c9d"), fill_color=QColor("#07152b"))
        toggle_layout = QHBoxLayout(toggle_host)
        toggle_layout.setContentsMargins(8, 8, 8, 8)
        toggle_layout.setSpacing(8)
        toggle_layout.addWidget(self.grid_button)
        toggle_layout.addWidget(self.list_button)
        selector_row.addWidget(toggle_host)
        layout.addLayout(selector_row)

        self.grid_host = QWidget()
        self.grid_host.setObjectName("LibraryCardGridHost")
        self.grid_layout = QGridLayout(self.grid_host)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setHorizontalSpacing(14)
        self.grid_layout.setVerticalSpacing(14)
        layout.addWidget(self.grid_host)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 10, 0, 0)
        footer.setSpacing(10)
        footer.addStretch(1)
        self.page_label = QLabel("")
        self.page_label.setObjectName("LibraryPaginationText")
        footer.addWidget(self.page_label)
        self.prev_button = PaginationButton("<")
        self.prev_button.clicked.connect(lambda: self._change_page(-1))
        footer.addWidget(self.prev_button)
        self.page_buttons: list[PaginationButton] = []
        for index in range(5):
            button = PaginationButton("")
            button.clicked.connect(lambda _checked=False, index=index: self._page_button_clicked(index))
            self.page_buttons.append(button)
            footer.addWidget(button)
        self.next_button = PaginationButton(">")
        self.next_button.clicked.connect(lambda: self._change_page(1))
        footer.addWidget(self.next_button)
        footer.addStretch(1)
        layout.addLayout(footer)

        self.advanced_popover = AdvancedFilterPopover(self.active_lenses, self)
        self.advanced_popover.filter_toggled.connect(self._advanced_filter_toggled)
        self.advanced_popover.hide()
        self._sync_category_cards()
        self._render_active_chips()
        QTimer.singleShot(0, self._deferred_refresh)

    def query_text(self) -> str:
        return self.search_bar.input.text().strip()

    def snapshot_state(self) -> dict[str, Any]:
        return {
            "page_index": self.page_index,
            "view_mode": self.view_mode,
            "type_filter": self.filter_bar.type_dropdown.combo.currentText(),
            "status_filter": self.filter_bar.status_dropdown.combo.currentText(),
            "location_filter": self.filter_bar.location_dropdown.combo.currentText(),
            "sort": self.sort_dropdown.combo.currentText(),
        }

    def restore_view_state(self, state: dict[str, Any]) -> None:
        if not state:
            return
        self._restoring_state = True
        try:
            self.view_mode = "list" if state.get("view_mode") == "list" else "grid"
            self.grid_button.setChecked(self.view_mode == "grid")
            self.list_button.setChecked(self.view_mode == "list")
            self._set_combo_text(self.filter_bar.type_dropdown.combo, state.get("type_filter"))
            self._set_combo_text(self.filter_bar.status_dropdown.combo, state.get("status_filter"))
            self._set_combo_text(self.filter_bar.location_dropdown.combo, state.get("location_filter"))
            self._set_combo_text(self.sort_dropdown.combo, state.get("sort"))
            try:
                self.page_index = max(0, int(state.get("page_index", 0)))
            except (TypeError, ValueError):
                self.page_index = 0
        finally:
            self._restoring_state = False
        self.refresh(interaction="restore")

    def _set_combo_text(self, combo: QComboBox, value: Any) -> None:
        text = str(value or "")
        if text and combo.findText(text) >= 0:
            combo.setCurrentText(text)

    def set_lenses(self, lenses: set[str]) -> None:
        self.active_lenses = set(lenses)
        self.advanced_popover.set_filters(self.active_lenses)
        self._render_active_chips()

    def set_lenses_open(self, open_: bool) -> None:
        self.lenses_open = bool(open_)
        self.filter_bar.advanced_button.setProperty("active", self.lenses_open)
        self.filter_bar.advanced_button._apply_modern_style()
        if self.lenses_open:
            self._position_popover()
            self.advanced_popover.show()
            self.advanced_popover.raise_()
        else:
            self.advanced_popover.hide()

    def refresh(self, *, reset_page: bool = False, interaction: str = "refresh") -> None:
        root = _catalog_project_root(self.catalog)
        with perf_timer(
            root,
            "library.refresh",
            details={"reset_page": reset_page, "scope_type": self.scope_type, "view_mode": self.view_mode, "interaction": interaction},
            source="minimalist_library",
            page_tool="library",
        ):
            if reset_page:
                self.page_index = 0
            if self.loading_message:
                self._render_loading_grid(root)
                self._sync_category_cards()
                self._render_active_chips()
                self._position_popover()
                return
            type_filter = TYPE_FROM_LABEL.get(self.filter_bar.type_dropdown.combo.currentText(), "all")
            if type_filter == "all":
                type_filter = self.scope_type
            status_filter = self.filter_bar.status_dropdown.combo.currentText()
            location_filter = self.filter_bar.location_dropdown.combo.currentText()
            query = self.query_text()
            sort_name = self.sort_dropdown.combo.currentText()
            category_total = sum(1 for entity in self.catalog.entities if entity.entity_type == type_filter)
            with perf_timer(
                root,
                "library.data_service.search_page",
                details={
                    "selected_category": type_filter,
                    "total_records_in_category": category_total,
                    "query": query,
                    "status_filter": status_filter,
                    "location_filter": location_filter,
                    "advanced_filter_count": len(self.active_lenses),
                },
                source="minimalist_library",
                page_tool="library",
            ):
                results = self.catalog.filtered(
                    query=query,
                    type_filter=type_filter,
                    status_filter=status_filter,
                    location_filter=location_filter,
                    active_filters=self.active_lenses,
                )
            with perf_timer(
                root,
                "library.data_service.filter_sort_page",
                details={
                    "selected_category": type_filter,
                    "total_records_in_category": category_total,
                    "filtered_record_count": len(results),
                    "sort": sort_name,
                    "current_page": self.page_index + 1,
                    "view_mode": self.view_mode,
                },
                source="minimalist_library",
                page_tool="library",
            ):
                with perf_timer(
                    root,
                    "library.sort_results",
                    details={"result_count": len(results), "sort": sort_name},
                    source="minimalist_library",
                    page_tool="library",
                ):
                    results = self._sort_results(results)
                columns = self._column_count()
                if self.view_mode == "grid":
                    page_size = (GRID_PAGE_SIZE if columns >= 4 else columns * 4)
                    if len(results) <= max(page_size, columns * 3):
                        page_size = max(1, len(results))
                else:
                    page_size = 6
                page_count = max(1, math.ceil(len(results) / page_size))
                self.page_index = max(0, min(self.page_index, page_count - 1))
                start = self.page_index * page_size
                visible = results[start : start + page_size]
            self._last_page_count = page_count
            self._last_filtered_count = len(results)
            self._last_page_size = page_size
            context_id = self._thumbnail_context_for(
                selected_category=type_filter,
                query=query,
                status_filter=status_filter,
                location_filter=location_filter,
                sort_name=sort_name,
            )
            log_perf_marker(
                root,
                "library.query_page",
                details={
                    "selected_category": type_filter,
                    "total_records_in_category": category_total,
                    "filtered_record_count": len(results),
                    "visible_card_count": len(visible),
                    "page_index": self.page_index,
                    "current_page": self.page_index + 1,
                    "page_size": page_size,
                    "columns": columns,
                    "view_mode": self.view_mode,
                },
                source="minimalist_library",
                page_tool="library",
            )
            self._render_grid(
                visible,
                context_id=context_id,
                total_records=category_total,
                filtered_count=len(results),
                page_size=page_size,
                current_page=self.page_index + 1,
            )
            self._render_pagination(len(results), page_size, page_count, start, len(visible))
            self._sync_category_cards()
            self._render_active_chips()
            self._position_popover()

    def _deferred_refresh(self) -> None:
        try:
            self.refresh(interaction="deferred")
        except RuntimeError:
            return

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_popover()
        columns = 1 if self.view_mode == "list" else self._column_count()
        if columns != self._rendered_columns and self.view_mode == "grid":
            QTimer.singleShot(0, self._deferred_refresh)

    def mousePressEvent(self, event) -> None:
        if self.lenses_open and not self.advanced_popover.geometry().contains(event.position().toPoint()):
            self.set_lenses_open(False)
        super().mousePressEvent(event)

    def _thumbnail_context_for(
        self,
        *,
        selected_category: str,
        query: str,
        status_filter: str,
        location_filter: str,
        sort_name: str,
    ) -> str:
        state = "|".join(
            (
                selected_category,
                self.view_mode,
                str(self.page_index + 1),
                query.strip().casefold(),
                status_filter,
                location_filter,
                sort_name,
                ",".join(sorted(self.active_lenses)),
            )
        )
        digest = hashlib.sha1(state.encode("utf-8")).hexdigest()[:12]
        return f"library:{selected_category}:page={self.page_index + 1}:state={digest}"

    def _render_loading_grid(self, root: str) -> None:
        columns = self._column_count()
        visible_count = GRID_PAGE_SIZE if self.view_mode == "grid" else 6
        self.page_index = 0
        self._last_page_count = 1
        self._last_filtered_count = 0
        self._last_page_size = visible_count
        self._last_rendered_keys = ()
        self.page_label.setText(self.loading_message or "Loading cached records...")
        self.prev_button.setEnabled(False)
        self.next_button.setEnabled(False)
        for button in self.page_buttons:
            button.hide()
        with perf_timer(
            root,
            "library.render.visible_cards",
            details={
                "selected_category": self.scope_type,
                "total_records_in_category": 0,
                "filtered_record_count": 0,
                "page_size": visible_count,
                "current_page": 1,
                "visible_card_count": visible_count,
                "widgets_created": visible_count,
                "loading_skeleton": True,
            },
            source="minimalist_library",
            page_tool="library",
        ):
            with perf_timer(
                root,
                "library.render.clear_old_cards",
                details={"previous_widget_count": self.grid_layout.count(), "selected_category": self.scope_type},
                source="minimalist_library",
                page_tool="library",
            ):
                clear_layout(self.grid_layout)
            _log_ui_marker(
                root,
                "ui.skeleton.show",
                details={"surface": "library_grid", "visible_card_count": visible_count, "message": self.loading_message},
                page_tool="library",
            )
            for index in range(visible_count):
                card = LibrarySkeletonCard(variant="list" if self.view_mode == "list" else "grid")
                row = index // columns
                column = index % columns
                self.grid_layout.addWidget(card, row, column)
            for column in range(columns):
                self.grid_layout.setColumnStretch(column, 1)
            rows = math.ceil(visible_count / max(1, columns))
            card_height = LIST_CARD_HEIGHT if self.view_mode == "list" else BROWSE_CARD_HEIGHT
            self.grid_host.setMinimumHeight(rows * card_height + max(0, rows - 1) * self.grid_layout.verticalSpacing())
            self.grid_layout.activate()

    def _pause_photo_prefetch(self) -> None:
        service = getattr(self.catalog, "photo_service", None)
        if service is not None:
            service.pause_prefetch()
            self._photo_resume_timer.start()

    def _resume_photo_prefetch(self) -> None:
        service = getattr(self.catalog, "photo_service", None)
        if service is not None:
            service.resume_prefetch()

    def _execute_debounced_search(self) -> None:
        if self._restoring_state:
            return
        root = _catalog_project_root(self.catalog)
        with perf_timer(
            root,
            "library.interaction.search_execute",
            details={"selected_category": self.scope_type, "query": self.query_text(), "debounce_ms": SEARCH_DEBOUNCE_MS},
            source="minimalist_library",
            page_tool="library",
        ):
            self.refresh(reset_page=True, interaction="search")

    def _query_changed(self) -> None:
        if self._restoring_state:
            return
        self._pause_photo_prefetch()
        _log_ui_marker(
            _catalog_project_root(self.catalog),
            "ui.search.visual_feedback",
            details={"selected_category": self.scope_type, "query": self.query_text(), "debounce_ms": SEARCH_DEBOUNCE_MS},
            page_tool="library",
        )
        log_perf_marker(
            _catalog_project_root(self.catalog),
            "library.interaction.search_debounce_start",
            details={"selected_category": self.scope_type, "query": self.query_text(), "debounce_ms": SEARCH_DEBOUNCE_MS},
            source="minimalist_library",
            page_tool="library",
        )
        self._search_debounce.start()

    def _filters_changed(self) -> None:
        if self._restoring_state:
            return
        self._pause_photo_prefetch()
        with perf_timer(
            _catalog_project_root(self.catalog),
            "library.interaction.filter_execute",
            details={
                "selected_category": self.scope_type,
                "type_filter": self.filter_bar.type_dropdown.combo.currentText(),
                "status_filter": self.filter_bar.status_dropdown.combo.currentText(),
                "location_filter": self.filter_bar.location_dropdown.combo.currentText(),
                "advanced_filter_count": len(self.active_lenses),
            },
            source="minimalist_library",
            page_tool="library",
        ):
            self.refresh(reset_page=True, interaction="filter")

    def _advanced_filter_toggled(self, label: str, checked: bool) -> None:
        self.lens_callback(label, checked)
        if checked:
            self.active_lenses.add(label)
        else:
            self.active_lenses.discard(label)
        self._render_active_chips()
        self._filters_changed()

    def _clear_all(self) -> None:
        self._search_debounce.stop()
        self._pause_photo_prefetch()
        self._restoring_state = True
        try:
            self.search_bar.input.clear()
            self.filter_bar.reset()
            self.active_lenses.clear()
            self.scope_type = ENTITY_EOAT
            self.page_index = 0
            self.set_lenses_open(False)
            self.clear_callback()
        finally:
            self._restoring_state = False
        with perf_timer(
            _catalog_project_root(self.catalog),
            "library.interaction.filter_execute",
            details={"selected_category": self.scope_type, "clear_all": True},
            source="minimalist_library",
            page_tool="library",
        ):
            self.refresh(reset_page=True, interaction="clear")

    def _select_category(self, entity_type: str) -> None:
        if entity_type not in {ENTITY_EOAT, ENTITY_TOOL, ENTITY_MACHINE}:
            return
        self._search_debounce.stop()
        self._pause_photo_prefetch()
        previous = self.scope_type
        with perf_timer(
            _catalog_project_root(self.catalog),
            "library.interaction.category_switch",
            details={"from_category": previous, "selected_category": entity_type, "query": self.query_text()},
            source="minimalist_library",
            page_tool="library",
        ):
            self.scope_type = entity_type
            self.page_index = 0
            self._sync_category_cards()
            self.refresh(reset_page=True, interaction="category_switch")

    def _set_view_mode(self, mode: str) -> None:
        self.view_mode = "list" if mode == "list" else "grid"
        self.grid_button.setChecked(self.view_mode == "grid")
        self.list_button.setChecked(self.view_mode == "list")
        self._pause_photo_prefetch()
        self.refresh(reset_page=True, interaction="view_mode")

    def _sort_changed(self, _text: str) -> None:
        if self._restoring_state:
            return
        self._pause_photo_prefetch()
        with perf_timer(
            _catalog_project_root(self.catalog),
            "library.interaction.sort_execute",
            details={"selected_category": self.scope_type, "sort": self.sort_dropdown.combo.currentText()},
            source="minimalist_library",
            page_tool="library",
        ):
            self.refresh(reset_page=True, interaction="sort")

    def _sort_results(self, results: list[LibraryEntity]) -> list[LibraryEntity]:
        selected = self.sort_dropdown.combo.currentText()
        if selected == "Missing Docs First":
            return sorted(results, key=lambda entity: (self.catalog.documentation_score(entity) >= 75, entity.title.casefold()))
        if selected == "Status":
            return sorted(results, key=lambda entity: (card_status_display(entity, self.catalog)[0], entity.title.casefold()))
        if selected == "Location":
            return sorted(results, key=lambda entity: (entity_location_line(entity, self.catalog), entity.title.casefold()))
        if selected == "Machine Number":
            return sorted(results, key=lambda entity: _natural_machine_key(entity.key if entity.entity_type == ENTITY_MACHINE else entity.meta))
        if selected == "Tool Number":
            return sorted(results, key=lambda entity: (0 if entity.entity_type == ENTITY_TOOL else 1, entity.key.casefold()))
        if selected == "EOAT ID":
            return sorted(results, key=lambda entity: (0 if entity.entity_type == ENTITY_EOAT else 1, entity.key.casefold()))
        return sorted(results, key=lambda entity: entity.title.casefold())

    def _has_active_filters(self) -> bool:
        return bool(
            self.query_text()
            or self.active_lenses
            or self.filter_bar.type_dropdown.combo.currentText() != "All"
            or self.filter_bar.status_dropdown.combo.currentText() != "All"
            or self.filter_bar.location_dropdown.combo.currentText() != "All"
        )

    def _render_grid(
        self,
        entities: list[LibraryEntity],
        *,
        context_id: str,
        total_records: int,
        filtered_count: int,
        page_size: int,
        current_page: int,
    ) -> None:
        root = _catalog_project_root(self.catalog)
        queued_thumbnails = self._visible_thumbnail_request_count(entities)
        hidden_skipped = max(0, filtered_count - len(entities))
        details = {
            "selected_category": self.scope_type,
            "total_records_in_category": total_records,
            "filtered_record_count": filtered_count,
            "page_size": page_size,
            "current_page": current_page,
            "visible_card_count": len(entities),
            "hidden_card_count": hidden_skipped,
            "visible_thumbnail_requests": queued_thumbnails,
            "view_mode": self.view_mode,
            "scope_type": self.scope_type,
            "sync_thumbnail_decode": False,
        }
        with perf_timer(
            root,
            "library.render.visible_cards",
            details=details,
            source="minimalist_library",
            page_tool="library",
        ):
            with perf_timer(
                root,
                "library.render_cards",
                details=details,
                source="minimalist_library",
                page_tool="library",
            ):
                service = getattr(self.catalog, "photo_service", None)
                cancelled_contexts = 0
                if service is not None and self._thumbnail_context_id:
                    service.cancel_context(self._thumbnail_context_id)
                    cancelled_contexts = 1
                self._thumbnail_context_id = context_id
                if callable(self.photo_context_callback):
                    self.photo_context_callback(context_id)
                log_perf_marker(
                    root,
                    "library.thumbnail_requests.cancel_old_context",
                    details={
                        "selected_category": self.scope_type,
                        "context_id": context_id,
                        "stale_thumbnail_requests_cancelled": cancelled_contexts,
                    },
                    source="minimalist_library",
                    page_tool="library",
                )
                previous_widgets = self.grid_layout.count()
                with perf_timer(
                    root,
                    "library.render.clear_old_cards",
                    details={"previous_widget_count": previous_widgets, "selected_category": self.scope_type},
                    source="minimalist_library",
                    page_tool="library",
                ):
                    clear_layout(self.grid_layout)
                self._last_rendered_keys = tuple((entity.entity_type, entity.key) for entity in entities)
                created_widgets = 0
                if not entities:
                    active_filters = self._has_active_filters()
                    _log_ui_marker(
                        root,
                        "ui.empty_state.show",
                        details={
                            "title": "No records found",
                            "selected_category": self.scope_type,
                            "query": self.query_text(),
                            "active_filter_count": len(self.active_lenses),
                            "filtered_record_count": filtered_count,
                            "clear_filters_available": active_filters,
                        },
                        page_tool="library",
                    )
                    empty = LibraryEmptyState(
                        "No records found",
                        "Try clearing filters or searching by ID, machine, tool, or status.",
                        action_text="Clear filters" if active_filters else "",
                        action_callback=self._clear_all if active_filters else None,
                    )
                    self.grid_layout.addWidget(empty, 0, 0, 1, max(1, self._column_count()))
                    created_widgets = 1
                    self._rendered_columns = self._column_count()
                    self.grid_host.setMinimumHeight(220)
                    self.grid_layout.activate()
                    self._log_card_widget_count(created_widgets, details)
                    self._log_thumbnail_request_counts(queued_thumbnails, hidden_skipped, context_id)
                    return
                columns = 1 if self.view_mode == "list" else self._column_count()
                if self.view_mode == "grid" and len(entities) == 12 and columns >= 4:
                    columns = 3
                self._rendered_columns = columns
                self._rendered_card_width = BROWSE_CARD_WIDTH if self.view_mode == "grid" else max(560, self.width() - 80)
                rows = math.ceil(len(entities) / max(1, columns))
                card_height = LIST_CARD_HEIGHT if self.view_mode == "list" else BROWSE_CARD_HEIGHT
                self.grid_host.setMinimumHeight(rows * card_height + max(0, rows - 1) * self.grid_layout.verticalSpacing())
                for index, entity in enumerate(entities):
                    variant = "list" if self.view_mode == "list" else "compact"
                    card = AtlasRecordCard(entity, self.catalog, variant=variant, navigable=True, thumbnail_context=context_id)
                    card.clicked.connect(lambda entity=entity: self._record_selected(entity))
                    card.detail_requested.connect(lambda entity=entity: self._record_selected(entity))
                    row = index // columns
                    column = index % columns
                    self.grid_layout.addWidget(card, row, column)
                    card.show()
                    created_widgets += 1
                for column in range(columns):
                    self.grid_layout.setColumnStretch(column, 1)
                self.grid_host.updateGeometry()
                self.grid_layout.activate()
                self._log_card_widget_count(created_widgets, details)
                self._log_thumbnail_request_counts(queued_thumbnails, hidden_skipped, context_id)

    def _visible_thumbnail_request_count(self, entities: list[LibraryEntity]) -> int:
        if getattr(self.catalog, "photo_service", None) is None:
            return 0
        count = 0
        for entity in entities:
            if entity.entity_type == ENTITY_MACHINE:
                continue
            if self.catalog.photo_count(entity) <= 0:
                continue
            if self.catalog.photo_candidates(entity, limit=1):
                count += 1
        return count

    def _log_card_widget_count(self, created_widgets: int, details: dict[str, object]) -> None:
        payload = dict(details)
        payload["widgets_created"] = created_widgets
        log_perf_marker(
            _catalog_project_root(self.catalog),
            "library.render.card_widget_count",
            details=payload,
            source="minimalist_library",
            page_tool="library",
        )

    def _log_thumbnail_request_counts(self, visible_requested: int, hidden_skipped: int, context_id: str) -> None:
        root = _catalog_project_root(self.catalog)
        common = {
            "selected_category": self.scope_type,
            "context_id": context_id,
            "page_size": self._last_page_size,
            "current_page": self.page_index + 1,
        }
        log_perf_marker(
            root,
            "library.thumbnail_requests.visible_cards_requested",
            details={**common, "new_thumbnail_requests_queued": visible_requested},
            source="minimalist_library",
            page_tool="library",
        )
        log_perf_marker(
            root,
            "library.thumbnail_requests.hidden_cards_skipped",
            details={**common, "hidden_thumbnail_requests_skipped": hidden_skipped},
            source="minimalist_library",
            page_tool="library",
        )

    def _record_selected(self, entity: LibraryEntity) -> None:
        self._search_debounce.stop()
        self._pause_photo_prefetch()
        service = getattr(self.catalog, "photo_service", None)
        if service is not None and self._thumbnail_context_id:
            service.cancel_context(self._thumbnail_context_id)
            log_perf_marker(
                _catalog_project_root(self.catalog),
                "library.thumbnail_requests.cancel_old_context",
                details={
                    "selected_category": self.scope_type,
                    "context_id": self._thumbnail_context_id,
                    "stale_thumbnail_requests_cancelled": 1,
                    "reason": "record_navigation",
                },
                source="minimalist_library",
                page_tool="library",
            )
        self.record_callback(entity)

    def _render_pagination(self, total: int, page_size: int, page_count: int, start: int, visible_count: int) -> None:
        label = TYPE_LABELS.get(self.scope_type, "records")
        if total:
            self.page_label.setText(f"Showing {start + 1}-{start + visible_count} of {total} {label}")
        else:
            self.page_label.setText(f"Showing 0 of 0 {label}")
        self.prev_button.setEnabled(self.page_index > 0)
        self.next_button.setEnabled(self.page_index < page_count - 1)
        pages = self._visible_page_numbers(page_count)
        for index, button in enumerate(self.page_buttons):
            if index >= len(pages):
                button.hide()
                continue
            number = pages[index]
            button.show()
            button.setText("..." if number < 0 else str(number + 1))
            button.setEnabled(number >= 0)
            button.setProperty("active", number == self.page_index)
            button._apply_modern_style()

    def _visible_page_numbers(self, page_count: int) -> list[int]:
        if page_count <= 5:
            return list(range(page_count))
        pages = [0, 1, 2, -1, page_count - 1]
        if self.page_index > 2 and self.page_index < page_count - 2:
            pages = [0, -1, self.page_index, -1, page_count - 1]
        return pages

    def _page_button_clicked(self, button_index: int) -> None:
        visible = self._visible_page_numbers(self._last_page_count)
        if button_index >= len(visible):
            return
        page = visible[button_index]
        if page < 0:
            return
        self._go_to_page(page)

    def _change_page(self, delta: int) -> None:
        self._go_to_page(self.page_index + delta)

    def _go_to_page(self, page: int) -> None:
        target = max(0, min(int(page), max(0, self._last_page_count - 1)))
        if target == self.page_index:
            return
        self._search_debounce.stop()
        self._pause_photo_prefetch()
        with perf_timer(
            _catalog_project_root(self.catalog),
            "library.interaction.pagination_execute",
            details={
                "selected_category": self.scope_type,
                "from_page": self.page_index + 1,
                "to_page": target + 1,
                "page_size": self._last_page_size,
                "filtered_record_count": self._last_filtered_count,
            },
            source="minimalist_library",
            page_tool="library",
        ):
            self.page_index = target
            self.refresh(interaction="pagination")

    def _column_count(self) -> int:
        widths = [value for value in (self.grid_host.width(), self.width()) if value > 0]
        width = min(widths) if widths else 1280
        if self.view_mode == "list":
            return 1
        if width > 1340:
            return 4
        if width >= 970:
            return 3
        if width >= 650:
            return 2
        return 1

    def _sync_category_cards(self) -> None:
        for entity_type, card in self.category_cards.items():
            card.set_selected(entity_type == self.scope_type)

    def _render_active_chips(self) -> None:
        clear_layout(self.active_chip_layout)
        if not self.active_lenses:
            self.active_chip_host.hide()
            return
        self.active_chip_host.show()
        for label in sorted(self.active_lenses):
            chip = AnimatedLibraryButton(f"{label}  x")
            chip.setObjectName("LibraryActiveFilterPill")
            chip.clicked.connect(lambda _checked=False, label=label: self._advanced_filter_toggled(label, False))
            self.active_chip_layout.addWidget(chip)
        self.active_chip_layout.addStretch(1)

    def _position_popover(self) -> None:
        if not hasattr(self, "advanced_popover"):
            return
        button = self.filter_bar.advanced_button
        pos = button.mapTo(self, QPoint(0, button.height() + 8))
        width = min(640, max(520, self.width() - 56))
        x = min(max(0, pos.x() - width + button.width()), max(0, self.width() - width - 8))
        self.advanced_popover.setGeometry(x, pos.y(), width, 278)


class CatalogFilterBar(GlassPanel):
    search_changed = Signal()
    filters_changed = Signal()
    advanced_requested = Signal()
    clear_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, radius=12, streaks=False)
        self.setObjectName("CatalogFilterBar")
        self.set_glass(alpha=82, border_alpha=74, border_color=QColor("#456f9f"), fill_color=QColor("#07152b"))
        self.setMinimumHeight(76)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        self.search_bar = LibrarySearchBar(self)
        self.search_bar.input.setPlaceholderText("Search EOATs, Tools, Machines...")
        self.search_bar.input.textChanged.connect(lambda _text: self.search_changed.emit())
        layout.addWidget(self.search_bar, 4)

        self.type_dropdown = FilterDropdown("Type", ("All", "EOATs", "Tools", "Machines"))
        self.type_dropdown.combo.currentTextChanged.connect(lambda _text: self.filters_changed.emit())
        layout.addWidget(self.type_dropdown, 1)

        self.status_dropdown = FilterDropdown("Status", STATUS_OPTIONS)
        self.status_dropdown.combo.currentTextChanged.connect(lambda _text: self.filters_changed.emit())
        layout.addWidget(self.status_dropdown, 1)

        self.location_dropdown = FilterDropdown("Location / Machine", LOCATION_OPTIONS)
        self.location_dropdown.combo.currentTextChanged.connect(lambda _text: self.filters_changed.emit())
        layout.addWidget(self.location_dropdown, 1)

        self.advanced_button = AnimatedLibraryButton("Advanced Filters")
        self.advanced_button.setObjectName("LibrarySecondaryButton")
        self.advanced_button.setIcon(glyph_icon("target", QColor("#dcecff"), 20))
        self.advanced_button.clicked.connect(self.advanced_requested.emit)
        layout.addWidget(self.advanced_button)

        self.clear_button = AnimatedLibraryButton("Clear")
        self.clear_button.setObjectName("LibrarySecondaryButton")
        self.clear_button.clicked.connect(self.clear_requested.emit)
        layout.addWidget(self.clear_button)

    def reset(self) -> None:
        for combo in (self.type_dropdown.combo, self.status_dropdown.combo, self.location_dropdown.combo):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)


class LibrarySearchBar(GlassPanel):
    def __init__(self, parent=None):
        super().__init__(parent, radius=8)
        self.setObjectName("LibrarySearchBar")
        self._focus_progress = 0.0
        self._focus_animation = QPropertyAnimation(self, b"focusProgress", self)
        self._focus_animation.setDuration(animation_duration(150))
        self._focus_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.set_glass(alpha=70, border_alpha=68, border_color=QColor("#496f9d"), fill_color=QColor("#08172b"))
        self.setMinimumHeight(52)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 14, 0)
        layout.setSpacing(12)
        layout.addWidget(SearchMiniIcon())
        self.input = QLineEdit()
        self.input.setObjectName("LibrarySearchInput")
        self.input.setFrame(False)
        set_placeholder_color(self.input, QColor("#9fb0c7"))
        self.input.installEventFilter(self)
        layout.addWidget(self.input, 1)

    def set_query_text(self, text: str) -> None:
        self.input.setText(text)
        self.input.selectAll()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.input and event.type() in {event.Type.FocusIn, event.Type.FocusOut}:
            self._animate_focus(event.type() == event.Type.FocusIn)
        return super().eventFilter(watched, event)

    def get_focus_progress(self) -> float:
        return self._focus_progress

    def set_focus_progress(self, value: float) -> None:
        self._focus_progress = max(0.0, min(1.0, float(value)))
        border = QColor("#1f87ff") if self._focus_progress else QColor("#496f9d")
        self.set_glass(alpha=74 + round(self._focus_progress * 16), border_alpha=70 + round(self._focus_progress * 80), border_color=border, fill_color=QColor("#08172b"), outer_glow_alpha=round(26 * self._focus_progress))
        self.update()

    focusProgress = Property(float, get_focus_progress, set_focus_progress)

    def _animate_focus(self, focused: bool) -> None:
        self._focus_animation.stop()
        self._focus_animation.setStartValue(self._focus_progress)
        self._focus_animation.setEndValue(1.0 if focused else 0.0)
        self._focus_animation.start()


class FilterDropdown(GlassPanel):
    def __init__(self, label: str, options: Iterable[str], *, compact: bool = False, parent=None):
        super().__init__(parent, radius=8)
        self.setObjectName("LibraryDropdown")
        self.set_glass(alpha=78, border_alpha=68, border_color=QColor("#496f9d"), fill_color=QColor("#08172b"))
        self.setMinimumHeight(52)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 7, 12, 6)
        layout.setSpacing(0)
        self.label = QLabel(label)
        self.label.setObjectName("LibraryDropdownLabel")
        self.combo = QComboBox()
        self.combo.setObjectName("LibraryDropdownCombo")
        self.combo.addItems(tuple(options))
        self.combo.setFrame(False)
        layout.addWidget(self.label)
        layout.addWidget(self.combo)
        self.setMinimumWidth(145 if not compact else 230)


class AdvancedFilterPopover(GlassPanel):
    filter_toggled = Signal(str, bool)

    def __init__(self, active_filters: set[str], parent=None):
        super().__init__(parent, radius=14, streaks=False)
        self.active_filters = set(active_filters)
        self.current_category = ADVANCED_FILTERS[0][0]
        self.category_buttons: dict[str, AnimatedLibraryButton] = {}
        self.value_buttons: dict[str, AnimatedLibraryButton] = {}
        self.setObjectName("AdvancedFilterPopover")
        self.set_glass(alpha=220, border_alpha=112, border_color=QColor("#4b91dd"), fill_color=QColor("#061226"), outer_glow_alpha=40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(6)
        for category, _values in ADVANCED_FILTERS:
            button = AnimatedLibraryButton(category)
            button.setObjectName("LibraryFilterCategory")
            button.clicked.connect(lambda _checked=False, category=category: self.select_category(category))
            self.category_buttons[category] = button
            left.addWidget(button)
        left.addStretch(1)
        layout.addLayout(left, 0)
        self.value_host = QWidget()
        self.value_host.setObjectName("LibraryComposerValueArea")
        self.value_layout = QGridLayout(self.value_host)
        self.value_layout.setContentsMargins(0, 0, 0, 0)
        self.value_layout.setHorizontalSpacing(8)
        self.value_layout.setVerticalSpacing(8)
        layout.addWidget(self.value_host, 1)
        self.select_category(self.current_category)

    def set_filters(self, filters: set[str]) -> None:
        self.active_filters = set(filters)
        self._sync_value_buttons()

    def select_category(self, category: str) -> None:
        self.current_category = category
        for label, button in self.category_buttons.items():
            button.setProperty("active", label == category)
            button._apply_modern_style()
        clear_layout(self.value_layout)
        self.value_buttons.clear()
        title = QLabel(category)
        title.setObjectName("LibraryPopoverTitle")
        self.value_layout.addWidget(title, 0, 0, 1, 2)
        values = dict(ADVANCED_FILTERS).get(category, ())
        for index, value in enumerate(values):
            button = AnimatedLibraryButton(value)
            button.setObjectName("LibraryFilterValue")
            button.clicked.connect(lambda _checked=False, value=value: self.toggle_value(value))
            self.value_buttons[value] = button
            self.value_layout.addWidget(button, 1 + index // 2, index % 2)
        self.value_layout.setRowStretch(8, 1)
        self._sync_value_buttons()

    def toggle_value(self, value: str) -> None:
        checked = value not in self.active_filters
        if checked:
            self.active_filters.add(value)
        else:
            self.active_filters.discard(value)
        self._sync_value_buttons()
        self.filter_toggled.emit(value, checked)

    def _sync_value_buttons(self) -> None:
        for label, button in self.value_buttons.items():
            button.setProperty("active", label in self.active_filters)
            button._apply_modern_style()


class CategorySelectorCard(AnimatedGlassCard):
    def __init__(self, title: str, glyph: str, count: int, parent=None):
        super().__init__(parent, radius=8)
        self.title = title
        self.glyph = glyph
        self.count = count
        self.selected = False
        self.setObjectName("LibraryCategorySelector")
        self.setMinimumHeight(70)
        self.setMaximumHeight(70)
        self.setMinimumWidth(250)

    def set_selected(self, selected: bool) -> None:
        self.selected = bool(selected)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.8, 0.8, -0.8, -0.8)
        hover = self._hover_progress
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if self.selected:
            fill.setColorAt(0.0, QColor(7, 34, 72, 222))
            fill.setColorAt(1.0, QColor(5, 18, 39, 226))
        else:
            fill.setColorAt(0.0, QColor(7, 20, 42, 190))
            fill.setColorAt(1.0, QColor(3, 13, 30, 202))
        painter.fillPath(path, fill)
        if self.selected or hover:
            glow = QColor("#168dff")
            glow.setAlpha(60 if self.selected else round(45 * hover))
            painter.setPen(QPen(glow, 4.0))
            painter.drawPath(path)
        border = QColor("#168dff" if self.selected else "#476f9e")
        border.setAlpha(210 if self.selected else 112 + round(60 * hover))
        painter.setPen(QPen(border, 1.2))
        painter.drawPath(path)
        icon = glyph_icon(self.glyph, QColor("#1496ff" if self.selected else "#f0f5ff"), 34).pixmap(34, 34)
        painter.drawPixmap(32, 18, icon)
        self._draw_text(painter, self.title, QRectF(82, 14, 120, 42), QColor("#1496ff" if self.selected else "#ffffff"), 16, 760)
        badge_width = max(46, 24 + QFontMetrics(_font(12, 760)).horizontalAdvance(str(self.count)))
        badge_rect = QRectF(rect.right() - badge_width - 24, 20, badge_width, 32)
        badge_path = QPainterPath()
        badge_path.addRoundedRect(badge_rect, 8, 8)
        painter.fillPath(badge_path, QColor(21, 111, 255, 212 if self.selected else 82))
        painter.setPen(QPen(QColor(97, 178, 255, 170), 1))
        painter.drawPath(badge_path)
        self._draw_text(painter, str(self.count), badge_rect, QColor("#ffffff"), 13, 760, align=Qt.AlignmentFlag.AlignCenter)

    def _draw_text(self, painter: QPainter, text: str, rect: QRectF, color: QColor, point_size: float, weight: int, *, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter) -> None:
        painter.setFont(_font(point_size, weight))
        painter.setPen(color)
        painter.drawText(rect, align, text)


class IconToggleButton(QPushButton):
    def __init__(self, glyph: str, tooltip: str, parent=None):
        super().__init__(parent)
        self.glyph = glyph
        self.setToolTip(tooltip)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(54, 54)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        painter.fillPath(path, QColor(9, 39, 89, 230) if self.isChecked() else QColor(7, 20, 42, 150))
        painter.setPen(QPen(QColor("#168dff" if self.isChecked() else "#456f9f"), 1.1))
        painter.drawPath(path)
        color = QColor("#2d97ff" if self.isChecked() else "#c7d4e7")
        if self.glyph == "list":
            painter.setPen(QPen(color, 2.2))
            for y in (18, 27, 36):
                painter.drawLine(20, y, 38, y)
                painter.drawPoint(15, y)
        else:
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            for row in range(2):
                for column in range(2):
                    painter.drawRoundedRect(QRectF(15 + column * 15, 16 + row * 15, 10, 10), 2, 2)


class PaginationButton(AnimatedLibraryButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("LibraryPaginationButton")
        self.setFixedSize(44, 44)


class LibraryEmptyState(QWidget):
    def __init__(self, title: str, subtitle: str, *, action_text: str = "", action_callback=None, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(180)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 42, 24, 42)
        layout.setSpacing(10)
        title_label = QLabel(title)
        title_label.setObjectName("LibraryEmptyTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("LibraryEmptySubtitle")
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        if action_text and callable(action_callback):
            button_row = QHBoxLayout()
            button_row.setContentsMargins(0, 8, 0, 0)
            button_row.addStretch(1)
            button = AnimatedLibraryButton(action_text)
            button.setObjectName("LibrarySecondaryButton")
            button.clicked.connect(action_callback)
            button_row.addWidget(button)
            button_row.addStretch(1)
            layout.addLayout(button_row)


class AtlasRecordCard(AnimatedGlassCard):
    def __init__(
        self,
        entity: LibraryEntity,
        catalog: LibraryCatalog | None,
        *,
        variant: str = "compact",
        compact: bool = False,
        navigable: bool = True,
        interactive_effects: bool = True,
        badge_label: str = "",
        thumbnail_context: str = "",
        parent=None,
    ):
        if compact:
            variant = "search"
        if variant not in {"compact", "list", "relationship", "node", "center_node", "search", "related", "hero"}:
            variant = "compact"
        super().__init__(parent, radius=8 if variant in {"compact", "list", "relationship", "search", "related"} else 90)
        self.entity = entity
        self.catalog = catalog
        self.variant = "relationship" if variant == "related" else variant
        self.navigable = navigable
        self.interactive_effects = interactive_effects
        self.badge_label = badge_label
        self.metrics = atlas_card_metrics(entity, catalog, variant=variant)
        self._thumbnail: QPixmap | None = None
        self._thumbnail_opacity = 1.0
        self._thumbnail_context = thumbnail_context or f"library:{entity.entity_type}:{entity.key}"
        self._thumbnail_photo_id = ""
        self._thumbnail_animation: QPropertyAnimation | None = None
        self._load_thumbnail()
        self._action_pressed = False
        self.setObjectName("AtlasRecordCard")
        self.setToolTip(f"{entity.title}\n{entity.subtitle}")
        if self.variant == "compact":
            self.setMinimumSize(300, BROWSE_CARD_HEIGHT)
            self.setMaximumHeight(BROWSE_CARD_HEIGHT)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        elif self.variant == "list":
            self.setMinimumSize(560, LIST_CARD_HEIGHT)
            self.setMaximumHeight(LIST_CARD_HEIGHT)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        elif self.variant == "relationship":
            self.setMinimumSize(160, 60)
            self.setMaximumSize(190, 60)
            self.resize(190, 60)
        elif self.variant == "node":
            self.setFixedSize(158, 158)
        elif self.variant == "center_node":
            self.setFixedSize(186, 186)
        else:
            self.setMinimumSize(320, 160)
        if not self.navigable:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def get_thumbnail_opacity(self) -> float:
        return self._thumbnail_opacity

    def set_thumbnail_opacity(self, value: float) -> None:
        self._thumbnail_opacity = max(0.0, min(1.0, float(value)))
        self.update()

    thumbnailOpacity = Property(float, get_thumbnail_opacity, set_thumbnail_opacity)

    def sizeHint(self) -> QSize:
        if self.variant == "compact":
            return QSize(BROWSE_CARD_WIDTH, BROWSE_CARD_HEIGHT)
        if self.variant == "list":
            return QSize(980, LIST_CARD_HEIGHT)
        if self.variant == "relationship":
            return QSize(190, 60)
        if self.variant == "node":
            return QSize(158, 158)
        if self.variant == "center_node":
            return QSize(186, 186)
        return QSize(360, 160)

    def enterEvent(self, event) -> None:
        if self.interactive_effects:
            super().enterEvent(event)
        else:
            QWidget.enterEvent(self, event)

    def leaveEvent(self, event) -> None:
        if self.interactive_effects:
            super().leaveEvent(event)
        else:
            QWidget.leaveEvent(self, event)

    def mousePressEvent(self, event) -> None:
        if not self.navigable:
            event.ignore()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._action_pressed = True
            self.update()
            QTimer.singleShot(animation_duration(120), self._clear_action_press)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if not self.navigable:
            event.ignore()
            return
        super().mouseDoubleClickEvent(event)

    def _clear_action_press(self) -> None:
        self._action_pressed = False
        try:
            self.update()
        except RuntimeError:
            return

    def paintEvent(self, event) -> None:
        if self.variant in {"node", "center_node"}:
            self._paint_node()
            return
        if self.variant == "relationship":
            self._paint_relationship_card()
            return
        if self.variant == "list":
            self._paint_list_card()
            return
        self._paint_catalog_card()

    def _paint_catalog_card(self) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.8, 0.8, -0.8, -0.8)
        hover = self._hover_progress if self.interactive_effects else 0.0
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
        fill.setColorAt(0.0, QColor(7, 20, 42, 218))
        fill.setColorAt(0.55, QColor(5, 18, 38, 220))
        fill.setColorAt(1.0, QColor(4, 14, 31, 232))
        painter.fillPath(path, fill)
        painter.save()
        painter.setClipPath(path)
        glow = QRadialGradient(rect.right() - rect.width() * 0.22, rect.top() + rect.height() * 0.30, rect.width() * 0.60)
        glow.setColorAt(0.0, QColor(0, 122, 255, 38 + round(26 * hover)))
        glow.setColorAt(0.58, QColor(0, 70, 160, 12))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(rect, glow)
        painter.restore()
        border = QColor(76, 116, 157, 138 + round(70 * hover))
        if hover:
            painter.setPen(QPen(QColor(28, 142, 255, round(62 * hover)), 4.0))
            painter.drawPath(path)
        painter.setPen(QPen(border, 1.1))
        painter.drawPath(path)

        image_rect = QRectF(rect.left() + 24, rect.top() + 36, 112, 70)
        self._draw_thumbnail(painter, image_rect, circular=False)
        status, tone = card_status_display(self.entity, self.catalog)
        self._draw_status(painter, QRectF(rect.left() + 150, rect.top() + 32, rect.width() - 172, 24), status, tone)
        self._draw_text_fit(painter, self.entity.title, QRectF(rect.left() + 150, rect.top() + 70, rect.width() - 186, 34), QColor("#ffffff"), 19, 820, min_point_size=13)
        self._draw_text(painter, clipped_text(self.entity.subtitle, 46), QRectF(rect.left() + 150, rect.top() + 105, rect.width() - 184, 28), QColor("#c9d4e4"), 12, 520)
        divider_y = rect.top() + 148
        painter.setPen(QPen(QColor(117, 151, 190, 76), 1))
        painter.drawLine(QPointF(rect.left() + 22, divider_y), QPointF(rect.right() - 22, divider_y))

        condition, condition_tone = entity_condition_line(self.entity, self.catalog)
        self._draw_info_row(painter, "machine", condition, QRectF(rect.left() + 24, divider_y + 17, rect.width() - 98, 22), condition_tone)
        self._draw_info_row(painter, "target", entity_location_line(self.entity, self.catalog), QRectF(rect.left() + 24, divider_y + 48, rect.width() - 98, 22), "normal")
        self._draw_arrow_button(painter, QRectF(rect.right() - 66, rect.bottom() - 70, 42, 42), hover)

    def _paint_list_card(self) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.8, 0.8, -0.8, -0.8)
        hover = self._hover_progress
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        painter.fillPath(path, QColor(6, 18, 38, 220))
        painter.setPen(QPen(QColor(72, 112, 154, 132 + round(60 * hover)), 1.1))
        painter.drawPath(path)
        image_rect = QRectF(rect.left() + 18, rect.top() + 18, 82, 82)
        self._draw_thumbnail(painter, image_rect, circular=False)
        status, tone = card_status_display(self.entity, self.catalog)
        self._draw_status(painter, QRectF(rect.right() - 168, rect.top() + 22, 140, 22), status, tone)
        self._draw_text_fit(painter, self.entity.title, QRectF(rect.left() + 122, rect.top() + 22, rect.width() - 320, 34), QColor("#ffffff"), 18, 820, min_point_size=12)
        self._draw_text(painter, clipped_text(self.entity.subtitle, 90), QRectF(rect.left() + 122, rect.top() + 58, rect.width() - 320, 24), QColor("#c9d4e4"), 12, 520)
        condition, condition_tone = entity_condition_line(self.entity, self.catalog)
        self._draw_info_row(painter, "machine", condition, QRectF(rect.left() + 122, rect.top() + 84, 240, 22), condition_tone)
        self._draw_info_row(painter, "target", entity_location_line(self.entity, self.catalog), QRectF(rect.left() + 365, rect.top() + 84, 210, 22), "normal")
        self._draw_arrow_button(painter, QRectF(rect.right() - 64, rect.center().y() - 21, 42, 42), hover)

    def _paint_relationship_card(self) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.7, 0.7, -0.7, -0.7)
        hover = self._hover_progress if self.interactive_effects else 0.0
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        painter.fillPath(path, QColor(7, 22, 45, 210))
        painter.setPen(QPen(QColor(75, 116, 157, 128 + round(54 * hover)), 1.0))
        painter.drawPath(path)
        self._draw_thumbnail(painter, QRectF(rect.left() + 10, rect.top() + 11, 38, 38), circular=False)
        right_reserve = 58 if self.badge_label else 20
        title_rect = QRectF(rect.left() + 60, rect.top() + 9, rect.width() - 60 - right_reserve, 21)
        self._draw_text_fit(painter, self.entity.title, title_rect, QColor("#ffffff"), 9.8, 760, min_point_size=7.8)
        self._draw_text(painter, clipped_text(self.entity.subtitle, 26), QRectF(rect.left() + 60, rect.top() + 32, rect.width() - 76, 19), QColor("#b9c5d7"), 8.2, 500)
        if self.badge_label:
            badge_rect = QRectF(rect.right() - 58, rect.top() + 7, 48, 17)
            badge_path = QPainterPath()
            badge_path.addRoundedRect(badge_rect, 7, 7)
            painter.fillPath(badge_path, QColor(0, 126, 255, 76))
            self._draw_text(painter, self.badge_label, badge_rect, QColor("#9be4ff"), 6.2, 760, align=Qt.AlignmentFlag.AlignCenter)
        if self.navigable:
            chevron_x = rect.right() - 17 + hover * 2
            chevron_y = rect.center().y()
            painter.setPen(QPen(QColor(20, 145, 255, 135 + round(60 * hover)), 1.5))
            painter.drawLine(QPointF(chevron_x - 4, chevron_y - 6), QPointF(chevron_x + 2, chevron_y))
            painter.drawLine(QPointF(chevron_x + 2, chevron_y), QPointF(chevron_x - 4, chevron_y + 6))

    def _paint_node(self) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        hover = self._hover_progress if self.interactive_effects else 0.0
        center = rect.center()
        radius = min(rect.width(), rect.height()) / 2
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        halo = QRadialGradient(center, radius * 1.25)
        halo.setColorAt(0.0, QColor(0, 126, 255, 42 + round(28 * hover)))
        halo.setColorAt(0.62, QColor(0, 82, 190, 12))
        halo.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(rect.adjusted(-20, -20, 20, 20), halo)
        painter.restore()
        painter.setBrush(QColor(6, 19, 40, 212))
        border_color = QColor("#04b76f") if self.variant == "center_node" else QColor("#247be8")
        painter.setPen(QPen(border_color, 1.6))
        painter.drawEllipse(rect)
        self._draw_thumbnail(painter, QRectF(center.x() - 35, rect.top() + 33, 70, 54), circular=False)
        title_size = 12 if self.variant == "node" else 13.5
        self._draw_text_fit(painter, self.entity.title, QRectF(rect.left() + 14, rect.top() + 88, rect.width() - 28, 26), QColor("#ffffff"), title_size, 820, min_point_size=8, align=Qt.AlignmentFlag.AlignCenter)
        self._draw_text(painter, clipped_text(self.entity.subtitle, 28), QRectF(rect.left() + 12, rect.top() + 113, rect.width() - 24, 22), QColor("#c2ccdc"), 8.8, 500, align=Qt.AlignmentFlag.AlignCenter)
        if self.variant == "center_node":
            status, tone = record_status_display(self.entity)
            self._draw_status(painter, QRectF(rect.left() + 44, rect.bottom() - 34, rect.width() - 88, 20), status, tone, compact=True)
        elif self.badge_label:
            self._draw_text(painter, self.badge_label, QRectF(rect.left() + 20, rect.bottom() - 30, rect.width() - 40, 18), QColor("#8bdcff"), 7.5, 760, align=Qt.AlignmentFlag.AlignCenter)

    def _load_thumbnail(self) -> None:
        if self.catalog is None:
            return
        if self.entity.entity_type == ENTITY_MACHINE:
            return
        try:
            service = getattr(self.catalog, "photo_service", None)
            if service is None:
                return
            candidates = self.catalog.photo_candidates(self.entity, limit=1)
            if not candidates:
                return
            photo_id, paths = candidates[0]
            self._thumbnail_photo_id = photo_id
            cached = service.get_cached_thumbnail(photo_id, (220, 140))
            if cached is not None and not cached.isNull():
                log_perf_marker(
                    _catalog_project_root(self.catalog),
                    "photo_service.memory_cache_hit",
                    details={"photo_id": photo_id, "context_id": self._thumbnail_context, "kind": "thumbnail", "surface": "library_card"},
                    source="photo_service",
                    page_tool="photos",
                )
                self._thumbnail = QPixmap.fromImage(cached)
                self._thumbnail_opacity = 1.0
                return
            service.thumbnail_ready.connect(self._thumbnail_ready)
            service.photo_load_failed.connect(self._thumbnail_failed)
            service.request_thumbnail(photo_id, paths, (220, 140), 60, self._thumbnail_context)
        except Exception:
            LOGGER.exception("Card thumbnail request failed for %s %s", self.entity.entity_type, self.entity.key)

    @Slot(str, object, str, str)
    def _thumbnail_ready(self, photo_id: str, image: QImage, _resolved_path: str, context_id: str) -> None:
        if context_id != self._thumbnail_context or photo_id != self._thumbnail_photo_id:
            return
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            return
        self._thumbnail = pixmap
        self._start_thumbnail_fade()

    @Slot(str, str, str)
    def _thumbnail_failed(self, photo_id: str, _reason: str, context_id: str) -> None:
        if context_id == self._thumbnail_context and photo_id == self._thumbnail_photo_id:
            self.update()

    def _start_thumbnail_fade(self) -> None:
        _log_ui_marker(
            _catalog_project_root(self.catalog),
            "ui.thumbnail.fade_in",
            details={
                "surface": "library_card",
                "record_type": self.entity.entity_type,
                "record_id": self.entity.key,
                "photo_id": self._thumbnail_photo_id,
                "duration_ms": 0 if prefers_reduced_motion() else 150,
            },
            page_tool="library",
        )
        self._thumbnail_opacity = 0.0 if not prefers_reduced_motion() else 1.0
        if prefers_reduced_motion():
            self.update()
            return
        if self._thumbnail_animation is not None:
            self._thumbnail_animation.stop()
            self._thumbnail_animation.deleteLater()
        animation = QPropertyAnimation(self, b"thumbnailOpacity", self)
        animation.setDuration(150)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._thumbnail_animation = animation
        animation.finished.connect(lambda: setattr(self, "_thumbnail_animation", None))
        animation.start()

    def _draw_thumbnail(self, painter: QPainter, rect: QRectF, *, circular: bool) -> None:
        painter.save()
        if circular:
            path = QPainterPath()
            path.addEllipse(rect)
            painter.setClipPath(path)
        if self._thumbnail is not None and not self._thumbnail.isNull():
            scaled = self._thumbnail.scaled(rect.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter.setOpacity(self._thumbnail_opacity)
            painter.drawPixmap(round(rect.center().x() - scaled.width() / 2), round(rect.center().y() - scaled.height() / 2), scaled)
        else:
            glyph = self._main_glyph()
            painter.setPen(QPen(QColor(94, 146, 204, 105), 1.0))
            painter.setBrush(QColor(8, 28, 58, 88))
            painter.drawRoundedRect(rect, 8, 8)
            icon_side = round(min(rect.width(), rect.height()) * 0.58)
            pix = glyph_icon(glyph, QColor("#d7e8ff"), icon_side).pixmap(icon_side, icon_side)
            painter.drawPixmap(round(rect.center().x() - pix.width() / 2), round(rect.center().y() - pix.height() / 2), pix)
        painter.restore()

    def _draw_status(self, painter: QPainter, rect: QRectF, text: str, tone: str, *, compact: bool = False) -> None:
        color = self._tone_color(tone)
        dot_side = 8 if not compact else 6
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(rect.left(), rect.center().y() - dot_side / 2, dot_side, dot_side))
        self._draw_text(painter, text, rect.adjusted(dot_side + 7, -1, 0, 1), color, 9.2 if not compact else 7.8, 680)

    def _draw_info_row(self, painter: QPainter, glyph: str, text: str, rect: QRectF, tone: str) -> None:
        color = self._tone_color(tone) if tone in {"warning", "muted"} else QColor("#d7dfec")
        icon = glyph_icon(glyph, color, 18).pixmap(18, 18)
        painter.drawPixmap(round(rect.left()), round(rect.center().y() - 9), icon)
        self._draw_text_fit(painter, text, rect.adjusted(30, -1, 0, 1), color, 10.5, 500, min_point_size=8.5)

    def _draw_arrow_button(self, painter: QPainter, rect: QRectF, hover: float) -> None:
        if not self.navigable:
            return
        pressed = bool(getattr(self, "_action_pressed", False))
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        if hover and not pressed:
            painter.save()
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            glow = QRadialGradient(rect.center(), rect.width() * 0.86)
            glow.setColorAt(0.0, QColor(43, 168, 232, round(24 + 28 * hover)))
            glow.setColorAt(0.58, QColor(29, 141, 206, round(10 + 14 * hover)))
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.fillRect(rect.adjusted(-9, -9, 9, 9), glow)
            painter.restore()
        fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
        start = "#0D2B4B" if pressed else ("#16507F" if hover >= 0.55 else "#123A63")
        end = "#123F64" if pressed else ("#1D8DCE" if hover >= 0.55 else "#176C9A")
        fill.setColorAt(0.0, QColor(start))
        fill.setColorAt(1.0, QColor(end))
        painter.fillPath(path, fill)
        border_alpha = 86 if pressed else 90 + round(78 * hover)
        painter.setPen(QPen(QColor(90, 190, 255, border_alpha), 1.0))
        painter.drawPath(path)
        color = QColor("#D8F4FF" if pressed else "#7EDCFF")
        color.setAlpha(226 if pressed else 220 + round(25 * hover))
        painter.setPen(QPen(color, 2.0))
        center = rect.center()
        painter.drawLine(QPointF(center.x() - 9, center.y()), QPointF(center.x() + 9, center.y()))
        painter.drawLine(QPointF(center.x() + 2, center.y() - 8), QPointF(center.x() + 10, center.y()))
        painter.drawLine(QPointF(center.x() + 2, center.y() + 8), QPointF(center.x() + 10, center.y()))

    def _draw_text(self, painter: QPainter, text: str, rect: QRectF, color: QColor, point_size: float, weight: int, *, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter) -> None:
        painter.setFont(_font(point_size, weight))
        painter.setPen(color)
        painter.drawText(rect, align, text)

    def _draw_text_fit(
        self,
        painter: QPainter,
        text: str,
        rect: QRectF,
        color: QColor,
        point_size: float,
        weight: int,
        *,
        min_point_size: float = 8,
        align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    ) -> None:
        raw = str(text or "")
        size = point_size
        while size >= min_point_size:
            font = _font(size, weight)
            if QFontMetrics(font).horizontalAdvance(raw) <= rect.width():
                painter.setFont(font)
                painter.setPen(color)
                painter.drawText(rect, align, raw)
                return
            size -= 0.75
        elided = QFontMetrics(_font(min_point_size, weight)).elidedText(raw, Qt.TextElideMode.ElideRight, round(rect.width()))
        self._draw_text(painter, elided, rect, color, min_point_size, weight, align=align)

    def _main_glyph(self) -> str:
        return {ENTITY_MACHINE: "machine", ENTITY_EOAT: "eoat", ENTITY_TOOL: "grid"}.get(self.entity.entity_type, "library")

    def _tone_color(self, tone: str) -> QColor:
        if tone in {"good", "normal"}:
            return QColor("#20df72")
        if tone == "warning" or tone == "warn":
            return QColor("#ffb145")
        if tone == "muted":
            return QColor("#9aa9be")
        return QColor("#6ea7ff")


LibraryBrowseCard = AtlasRecordCard


class LibraryRecordStateView(QWidget):
    pdf_export_complete = Signal(str)
    pdf_export_failed = Signal(str)

    def __init__(self, catalog: LibraryCatalog, entity: LibraryEntity, back_callback, record_callback, parent=None):
        super().__init__(parent)
        self.catalog = catalog
        self.entity = entity
        self.detail_data: RecordDetailData | None = None
        self.back_callback = back_callback
        self.record_callback = record_callback
        self.hero: RecordHeroPanel | None = None
        self.tabs: RecordTabBar | None = None
        self.stack: RecordTabStack | None = None
        self.overview: RecordOverviewTab | None = None
        self.details: RecordDetailsTab | None = None
        self.docs: RecordDocsTab | None = None
        self.history: RecordHistoryTab | None = None
        self._tab_placeholders: dict[int, QWidget] = {}
        self._tab_widgets: dict[int, QWidget] = {}
        self._pdf_export_running = False
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 84, 0, 12)
        self._layout.setSpacing(14)
        self.setObjectName("LibraryRecordStateView")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.pdf_export_complete.connect(self._pdf_export_finished)
        self.pdf_export_failed.connect(self._pdf_export_failed)
        self.bind_record(catalog, entity)

    def bind_record(self, catalog: LibraryCatalog, entity: LibraryEntity) -> None:
        self.catalog = catalog
        self.entity = entity
        service_ready = catalog.data_service is not None and catalog.data_service.is_index_ready()
        if catalog.bundle is None and not service_ready:
            raise ValueError("Record detail view requires an Atlas data bundle.")
        self.setUpdatesEnabled(False)
        try:
            with perf_timer(
                _catalog_project_root(catalog),
                "record.open.start_to_shell_visible",
                details={"record_type": entity.entity_type, "record_id": entity.key},
                source="minimalist_library",
                page_tool="library_record",
            ):
                with perf_timer(
                    _catalog_project_root(catalog),
                    "record.detail_data_load",
                    details={"record_type": entity.entity_type, "record_id": entity.key},
                    source="minimalist_library",
                    page_tool="library_record",
                ):
                    if service_ready:
                        self.detail_data = catalog.data_service.get_record_detail_data(entity.entity_type, entity.key)
                    else:
                        self.detail_data = build_record_detail_data(catalog.bundle, entity.entity_type, entity.key)
                self._build_record_shell()
        finally:
            self.setUpdatesEnabled(True)
            self.update()

    def _build_record_shell(self) -> None:
        if self.detail_data is None:
            return
        clear_layout(self._layout)
        self.hero = None
        self.tabs = None
        self.stack = None
        self.overview = None
        self.details = None
        self.docs = None
        self.history = None
        self._tab_placeholders = {}
        self._tab_widgets = {}

        with perf_timer(
            _catalog_project_root(self.catalog),
            "record.render_page_widgets",
            details={
                "record_type": self.entity.entity_type,
                "record_id": self.entity.key,
                "photo_count": self.detail_data.photo_count,
                "detail_sections": len(self.detail_data.detail_sections),
                "inactive_tabs_deferred": True,
            },
            source="minimalist_library",
            page_tool="library_record",
        ):
            with perf_timer(
                _catalog_project_root(self.catalog),
                "record.render.hero_panel",
                details={"record_type": self.entity.entity_type, "record_id": self.entity.key},
                source="minimalist_library",
                page_tool="library_record",
            ):
                self.hero = RecordHeroPanel(self.entity, self.catalog, self.detail_data, self._export_pdf)
            self._layout.addWidget(self.hero)

            with perf_timer(
                _catalog_project_root(self.catalog),
                "record.render.tabs",
                details={"record_type": self.entity.entity_type, "record_id": self.entity.key},
                source="minimalist_library",
                page_tool="library_record",
            ):
                self.tabs = RecordTabBar()
                self.tabs.tab_changed.connect(self._set_tab)
                self.tabs.set_current(0)
            self._layout.addWidget(self.tabs)

            self.stack = RecordTabStack()
            self.stack.setObjectName("LibraryRecordStack")
            with perf_timer(
                _catalog_project_root(self.catalog),
                "record.render.overview_tab",
                details={"record_type": self.entity.entity_type, "record_id": self.entity.key},
                source="minimalist_library",
                page_tool="library_record",
            ):
                self.overview = RecordOverviewTab(self.entity, self.catalog, self.record_callback, self.detail_data)
            self.stack.addWidget(self.overview)
            self._tab_widgets[0] = self.overview
            for index in (1, 2, 3):
                placeholder = QWidget()
                placeholder.setObjectName("RecordLazyTabPlaceholder")
                self._tab_placeholders[index] = placeholder
                self.stack.addWidget(placeholder)
            self.stack.setCurrentIndex(0)
            self._layout.addWidget(self.stack, 1)
            widget_count = len(self.findChildren(QWidget))
            log_perf_marker(
                _catalog_project_root(self.catalog),
                "record.widget_count_created",
                details={
                    "record_type": self.entity.entity_type,
                    "record_id": self.entity.key,
                    "widget_count": widget_count,
                    "inactive_tabs_built_immediately": False,
                },
                source="minimalist_library",
                page_tool="library_record",
            )
            log_perf_marker(
                _catalog_project_root(self.catalog),
                "record.layout_pass_count",
                details={"record_type": self.entity.entity_type, "record_id": self.entity.key, "estimated_passes": 1},
                source="minimalist_library",
                page_tool="library_record",
            )

    def _set_tab(self, index: int) -> None:
        if self.stack is None:
            return
        self._ensure_tab(index)
        self.stack.setCurrentIndex(index)

    def _ensure_tab(self, index: int) -> QWidget | None:
        if self.detail_data is None or self.stack is None:
            return None
        existing = self._tab_widgets.get(index)
        if existing is not None:
            return existing
        operation = {
            1: "record.render.details_tab_lazy",
            2: "record.render.photos_tab_lazy",
            3: "record.render.history_tab_lazy",
        }.get(index, "record.render.tab_lazy")
        with perf_timer(
            _catalog_project_root(self.catalog),
            operation,
            details={"record_type": self.entity.entity_type, "record_id": self.entity.key, "tab_index": index},
            source="minimalist_library",
            page_tool="library_record",
        ):
            if index == 1:
                widget = RecordDetailsTab(self.detail_data)
                self.details = widget
            elif index == 2:
                context_id = f"photos:{self.entity.entity_type}:{self.entity.key}"
                widget = RecordDocsTab(
                    self.detail_data,
                    project_root=_catalog_project_root(self.catalog),
                    photo_service=getattr(self.catalog, "photo_service", None),
                    context_id=context_id,
                )
                self.docs = widget
            elif index == 3:
                widget = RecordHistoryTab(self.detail_data)
                self.history = widget
            else:
                return None
            placeholder = self._tab_placeholders.get(index)
            if placeholder is not None:
                self.stack.removeWidget(placeholder)
                placeholder.deleteLater()
            self.stack.insertWidget(index, widget)
            self._tab_widgets[index] = widget
            return widget

    def _export_pdf(self) -> None:
        if self.detail_data is None:
            return
        if self._pdf_export_running:
            return
        detail_data = self.detail_data
        project_root = _catalog_project_root(self.catalog)
        self._pdf_export_running = True
        self._set_pdf_export_busy(True)
        _log_ui_marker(
            project_root,
            "ui.pdf_export.start",
            details={
                "record_type": detail_data.record_type,
                "record_id": detail_data.record_id,
                "photo_count": detail_data.photo_count,
            },
            page_tool="library_record",
        )
        self._notify("Exporting PDF...")

        worker = threading.Thread(
            target=self._run_pdf_export_worker,
            args=(detail_data, project_root),
            name=f"RecordPdfExport-{detail_data.record_type}-{detail_data.record_id}",
            daemon=True,
        )
        worker.start()

    def _run_pdf_export_worker(self, detail_data: RecordDetailData, project_root: str) -> None:
        try:
            from core.reporting.pdf_record_report import export_record_pdf

            with perf_timer(
                project_root,
                "record.pdf_export",
                details={
                    "record_type": detail_data.record_type,
                    "record_id": detail_data.record_id,
                    "photo_count": detail_data.photo_count,
                    "background": True,
                },
                source="minimalist_library",
                page_tool="library_record",
            ):
                path = export_record_pdf(detail_data, project_root=project_root)
        except Exception as exc:
            LOGGER.exception("PDF export failed for %s %s", detail_data.record_type, detail_data.record_id)
            try:
                self.pdf_export_failed.emit(f"{type(exc).__name__}: {exc}")
            except RuntimeError:
                LOGGER.debug("Record view was destroyed before PDF export failure could be reported.")
            return
        try:
            self.pdf_export_complete.emit(str(path))
        except RuntimeError:
            LOGGER.debug("Record view was destroyed before PDF export completion could be reported.")

    @Slot(str)
    def _pdf_export_finished(self, path: str) -> None:
        self._pdf_export_running = False
        self._set_pdf_export_busy(False)
        _log_ui_marker(
            _catalog_project_root(self.catalog),
            "ui.pdf_export.complete",
            details={"record_type": self.entity.entity_type, "record_id": self.entity.key, "output_path": path},
            page_tool="library_record",
        )
        self._notify("PDF report exported.")
        notifier = getattr(self.catalog.controller, "show_status", None)
        if callable(notifier):
            notifier(f"PDF report exported: {path}")

    @Slot(str)
    def _pdf_export_failed(self, message: str) -> None:
        self._pdf_export_running = False
        self._set_pdf_export_busy(False)
        _log_ui_marker(
            _catalog_project_root(self.catalog),
            "ui.pdf_export.fail",
            details={"record_type": self.entity.entity_type, "record_id": self.entity.key, "error": message},
            page_tool="library_record",
        )
        _log_ui_marker(
            _catalog_project_root(self.catalog),
            "ui.error_state.show",
            details={"surface": "pdf_export", "record_type": self.entity.entity_type, "record_id": self.entity.key, "error": message},
            page_tool="library_record",
        )
        self._notify("PDF export failed.")
        notifier = getattr(self.catalog.controller, "show_status", None)
        if callable(notifier):
            notifier(f"PDF export failed: {message}")

    def _set_pdf_export_busy(self, busy: bool) -> None:
        hero = self.hero
        button = getattr(hero, "export_button", None)
        if button is None:
            return
        button.setEnabled(not busy)
        button.setText("Exporting..." if busy else "Export PDF")

    def _notify(self, message: str) -> None:
        widget = self.parentWidget()
        while widget is not None:
            notifier = getattr(widget, "show_toast", None)
            if callable(notifier):
                notifier(message)
                return
            widget = widget.parentWidget()
        notifier = getattr(self.catalog.controller, "show_status", None)
        if callable(notifier):
            notifier(message)


class RecordHeroPanel(GlassPanel):
    def __init__(self, entity: LibraryEntity, catalog: LibraryCatalog, detail_data: RecordDetailData, export_callback, parent=None):
        super().__init__(parent, radius=14, streaks=True)
        self.entity = entity
        self.catalog = catalog
        self.detail_data = detail_data
        self.export_button: AnimatedLibraryButton | None = None
        self.setObjectName("RecordHeroPanel")
        self.set_glass(alpha=88, border_alpha=78, border_color=QColor("#496f9d"), fill_color=QColor("#061226"))
        self.setMinimumHeight(240)
        self.setMaximumHeight(260)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(28)

        portrait = EntityPortrait(entity, catalog)
        portrait.setFixedSize(180, 180)
        layout.addWidget(portrait)

        identity = QVBoxLayout()
        identity.setContentsMargins(0, 8, 0, 0)
        identity.setSpacing(7)
        status, tone = record_status_display(entity)
        identity.addWidget(StatusLineLabel(status, tone))
        label = QLabel(entity.type_label.upper())
        label.setObjectName("RecordHeroType")
        title = QLabel(entity.title)
        title.setObjectName("RecordHeroTitle")
        subtitle = QLabel(entity.subtitle)
        subtitle.setObjectName("RecordHeroSubtitle")
        subtitle.setWordWrap(True)
        identity.addWidget(label)
        identity.addWidget(title)
        identity.addWidget(subtitle)
        rule = QFrame()
        rule.setObjectName("RecordHeroRule")
        rule.setFixedHeight(1)
        identity.addWidget(rule)
        location_row = QHBoxLayout()
        location_row.setContentsMargins(0, 4, 0, 0)
        location_row.setSpacing(18)
        location_row.addWidget(InfoPill("target", entity_location_line(entity, catalog)))
        condition, _condition_tone = entity_condition_line(entity, catalog)
        location_row.addWidget(InfoPill("machine", condition))
        location_row.addStretch(1)
        identity.addLayout(location_row)
        identity.addStretch(1)
        layout.addLayout(identity, 2)

        divider = QFrame()
        divider.setObjectName("RecordHeroVerticalRule")
        divider.setFixedWidth(1)
        layout.addWidget(divider)

        metadata = QGridLayout()
        metadata.setContentsMargins(0, 12, 0, 0)
        metadata.setHorizontalSpacing(28)
        metadata.setVerticalSpacing(16)
        for index, field in enumerate(detail_data.hero_fields):
            item = MetadataBlock(field.label, _field_text(field.value))
            metadata.addWidget(item, index % 3, index // 3)
        layout.addLayout(metadata, 3)

        actions = QVBoxLayout()
        actions.setContentsMargins(0, 12, 0, 10)
        actions.setSpacing(12)
        for index, action in enumerate(hero_actions(entity)):
            button = AnimatedLibraryButton(action)
            button.setObjectName("RecordPrimaryAction" if index == 0 else "RecordSecondaryAction")
            button.setIcon(glyph_icon("doc" if "PDF" in action else "status", QColor("#ffffff"), 18))
            if "PDF" in action:
                self.export_button = button
                button.clicked.connect(export_callback)
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)


class EntityPortrait(QWidget):
    def __init__(self, entity: LibraryEntity, catalog: LibraryCatalog, parent=None):
        super().__init__(parent)
        self.entity = entity
        self.catalog = catalog
        self.pixmap = None

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        halo = QRadialGradient(rect.center(), rect.width() * 0.62)
        halo.setColorAt(0.0, QColor(0, 150, 255, 48))
        halo.setColorAt(0.62, QColor(0, 110, 255, 12))
        halo.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(QRectF(self.rect()), halo)
        painter.restore()
        painter.setBrush(QColor(6, 24, 48, 116))
        painter.setPen(QPen(QColor("#04b76f"), 1.1))
        painter.drawEllipse(rect)
        image_rect = rect.adjusted(24, 42, -24, -42)
        if self.pixmap is not None and not self.pixmap.isNull():
            scaled = self.pixmap.scaled(image_rect.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(round(image_rect.center().x() - scaled.width() / 2), round(image_rect.center().y() - scaled.height() / 2), scaled)
        else:
            glyph = {ENTITY_MACHINE: "machine", ENTITY_EOAT: "eoat", ENTITY_TOOL: "grid"}.get(self.entity.entity_type, "library")
            icon = glyph_icon(glyph, QColor("#d7e8ff"), 72).pixmap(72, 72)
            painter.drawPixmap(round(rect.center().x() - icon.width() / 2), round(rect.center().y() - icon.height() / 2), icon)
        painter.setBrush(QColor("#20df72"))
        painter.setPen(QPen(QColor("#061226"), 1))
        painter.drawEllipse(QRectF(rect.right() - 34, rect.top() + 20, 8, 8))


class StatusLineLabel(QWidget):
    def __init__(self, text: str, tone: str, parent=None):
        super().__init__(parent)
        self.text = text
        self.tone = tone
        self.setFixedHeight(24)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor("#20df72") if self.tone == "good" else QColor("#ffb145")
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(0, 8, 8, 8))
        painter.setFont(_font(9.5, 700))
        painter.setPen(color)
        painter.drawText(QRectF(16, 0, self.width() - 16, 24), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text)


class InfoPill(QWidget):
    def __init__(self, glyph: str, text: str, parent=None):
        super().__init__(parent)
        self.glyph = glyph
        self.text = text
        self.setMinimumWidth(120)
        self.setFixedHeight(26)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        icon = glyph_icon(self.glyph, QColor("#aebbd0"), 18).pixmap(18, 18)
        painter.drawPixmap(0, 4, icon)
        painter.setFont(_font(10, 520))
        painter.setPen(QColor("#c9d4e4"))
        painter.drawText(QRectF(28, 0, self.width() - 28, 26), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text)


class MetadataBlock(QWidget):
    def __init__(self, label: str, value: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        key = QLabel(label.upper())
        key.setObjectName("RecordMetaLabel")
        val = QLabel(value or "Not Indexed")
        val.setObjectName("RecordMetaValue")
        val.setWordWrap(True)
        layout.addWidget(key)
        layout.addWidget(val)


class RecordTabBar(QWidget):
    tab_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.buttons: list[AnimatedLibraryButton] = []
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        for index, label in enumerate(("Overview", "Details", "Docs & Photos", "History")):
            button = AnimatedLibraryButton(label)
            button.setCheckable(True)
            button.setObjectName("LibraryTabButton")
            self.group.addButton(button, index)
            self.buttons.append(button)
            layout.addWidget(button)
        layout.addStretch(1)
        self.group.idClicked.connect(self._clicked)
        self.buttons[0].setChecked(True)
        self._sync()

    def set_current(self, index: int) -> None:
        if 0 <= index < len(self.buttons):
            self.buttons[index].setChecked(True)
            self._sync()

    def _clicked(self, index: int) -> None:
        self._sync()
        self.tab_changed.emit(index)

    def _sync(self) -> None:
        for button in self.buttons:
            button.setProperty("active", button.isChecked())
            button._apply_modern_style()


class RecordTabStack(QStackedWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentChanged.connect(lambda _index: self.updateGeometry())

    def sizeHint(self) -> QSize:
        widget = self.currentWidget()
        if widget is not None:
            return widget.sizeHint()
        return super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        widget = self.currentWidget()
        if widget is not None:
            return widget.minimumSizeHint()
        return super().minimumSizeHint()


class RecordOverviewTab(QWidget):
    def __init__(self, entity: LibraryEntity, catalog: LibraryCatalog, record_callback, detail_data: RecordDetailData, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        self.relationship_panel = RelationshipOverviewPanel(entity, catalog, record_callback)
        with perf_timer(
            _catalog_project_root(catalog),
            "record.render.summary_strip",
            details={"record_type": entity.entity_type, "record_id": entity.key, "summary_fields": len(detail_data.summary_fields)},
            source="minimalist_library",
            page_tool="library_record",
        ):
            self.summary_panel = SummaryMetricsPanel(detail_data)
        layout.addWidget(self.relationship_panel, 1)
        layout.addWidget(self.summary_panel, 0)
        layout.setStretch(0, 1)
        layout.setStretch(1, 0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_relationship_height()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_relationship_height)

    def _sync_relationship_height(self) -> None:
        summary_height = max(118, self.summary_panel.sizeHint().height())
        spacing = max(12, self.layout().spacing() if self.layout() is not None else 14)
        local_target = self.height() - summary_height - spacing
        window = self.window()
        if window is not None:
            try:
                top_in_window = self.mapTo(window, QPoint(0, 0)).y()
                local_target = min(local_target, window.height() - top_in_window - summary_height - spacing - 58)
            except RuntimeError:
                pass
        target = max(340, min(420, local_target))
        if abs(self.relationship_panel.height() - target) > 2:
            self.relationship_panel.setFixedHeight(round(target))


@dataclass
class RelationshipCanvasZone:
    rect: QRect
    side: str
    entity: LibraryEntity | None = None
    badge: str = ""
    more_count: int = 0

    def isVisible(self) -> bool:
        return not self.rect.isNull()

    def geometry(self) -> QRect:
        return QRect(self.rect)


class RelationshipOverviewPanel(GlassPanel):
    RELATIONSHIP_CONNECTOR_COLOR = QColor("#168dff")
    RELATIONSHIP_BADGE_COLOR = QColor("#00c9ff")
    RELATED_CARD_WIDTH = 190
    RELATED_CARD_MIN_WIDTH = 160
    RELATED_CARD_HEIGHT = 60
    RELATED_CARD_GAP = 14
    RELATED_COLUMN_GAP = 16
    CENTER_CONNECTOR_GAP = 46
    SIDE_MARGIN = 8
    DIAGRAM_TOP_PADDING = 108
    DIAGRAM_BOTTOM_PADDING = 24
    MAX_ROWS_PER_COLUMN = 3
    MAX_COLUMNS_PER_SIDE = 3
    MAX_VISIBLE_SIDE_ITEMS = MAX_ROWS_PER_COLUMN * MAX_COLUMNS_PER_SIDE

    def __init__(self, entity: LibraryEntity, catalog: LibraryCatalog, record_callback, parent=None):
        super().__init__(parent, radius=14, streaks=False)
        self.entity = entity
        self.catalog = catalog
        self.record_callback = record_callback
        self.setObjectName("RelationshipOverviewPanel")
        self.set_glass(alpha=68, border_alpha=58, border_color=QColor("#375e8d"), fill_color=QColor("#041024"))
        self.setMinimumHeight(340)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.left_title = ""
        self.right_title = ""
        self.left_entities: list[LibraryEntity] = []
        self.right_entities: list[LibraryEntity] = []
        self.badges: dict[tuple[str, str], str] = {}
        self.center_rect = QRect()
        self.left_zones: list[RelationshipCanvasZone] = []
        self.right_zones: list[RelationshipCanvasZone] = []
        self.hit_zones: list[RelationshipCanvasZone] = []
        self.hover_zone: RelationshipCanvasZone | None = None
        self.relationships_loaded = False
        self._first_paint_logged = False
        QTimer.singleShot(0, self._populate)

    @property
    def left_visible_zones(self) -> list[RelationshipCanvasZone]:
        return [zone for zone in self.left_zones if zone.entity is not None]

    @property
    def right_visible_zones(self) -> list[RelationshipCanvasZone]:
        return [zone for zone in self.right_zones if zone.entity is not None]

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.relationships_loaded:
            self._calculate_layout()

    def mouseMoveEvent(self, event) -> None:
        point = event.position().toPoint()
        zone = next((item for item in self.hit_zones if item.entity is not None and item.rect.contains(point)), None)
        if zone is not self.hover_zone:
            self.hover_zone = zone
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self.hover_zone = None
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            point = event.position().toPoint()
            zone = next((item for item in self.hit_zones if item.entity is not None and item.rect.contains(point)), None)
            if zone is not None and zone.entity is not None:
                self.record_callback(zone.entity)
                event.accept()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        timer = (
            perf_timer(
                _catalog_project_root(self.catalog),
                "record.render.relationship_widgets_or_paint",
                details={
                    "record_type": self.entity.entity_type,
                    "record_id": self.entity.key,
                    "approach": "custom_painted_canvas",
                    "hit_zones": len(self.hit_zones),
                },
                source="minimalist_library",
                page_tool="library_record",
            )
            if not self._first_paint_logged
            else nullcontext()
        )
        with timer:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self._paint_content(painter)
            self._first_paint_logged = True

    def _paint_content(self, painter: QPainter) -> None:
        painter.setFont(_font(15, 800))
        painter.setPen(QColor("#ffffff"))
        painter.drawText(QRectF(24, 24, 310, 30), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Relationship Overview")
        painter.setFont(_font(9.5, 520))
        painter.setPen(QColor("#b9c8dc"))
        painter.drawText(QRectF(24, 54, 430, 25), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, relationship_subtitle(self.entity))
        if not self.relationships_loaded:
            painter.setFont(_font(11, 560))
            painter.setPen(QColor("#9fb0c7"))
            painter.drawText(QRectF(30, self.height() / 2 - 24, self.width() - 60, 48), Qt.AlignmentFlag.AlignCenter, "Loading relationships...")
            return
        if not self.left_zones and not self.right_zones:
            painter.setFont(_font(11, 560))
            painter.setPen(QColor("#9fb0c7"))
            painter.drawText(QRectF(30, self.height() / 2 - 36, self.width() - 60, 72), Qt.AlignmentFlag.AlignCenter, "No linked records are indexed for this record yet.")
            self._draw_center_node(painter)
            return
        label_y = max(78, self.center_rect.top() - 28)
        if self.left_title:
            left_bounds = self._bounds_for(self.left_zones)
            painter.setFont(_font(10, 800))
            painter.setPen(QColor("#7edcff"))
            painter.drawText(QRectF(left_bounds.left() if not left_bounds.isNull() else 24, label_y, 220, 24), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.left_title.upper())
        if self.right_title:
            right_bounds = self._bounds_for(self.right_zones)
            painter.setFont(_font(10, 800))
            painter.setPen(QColor("#7edcff"))
            painter.drawText(QRectF(right_bounds.left() if not right_bounds.isNull() else self.center_rect.right() + self.CENTER_CONNECTOR_GAP, label_y, 220, 24), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.right_title.upper())
        self._draw_connectors(painter)
        for zone in [*self.left_zones, *self.right_zones]:
            if zone.more_count:
                self._draw_more_card(painter, zone)
            elif zone.entity is not None:
                self._draw_entity_card(painter, zone)
        self._draw_center_node(painter)

    def _populate(self) -> None:
        with perf_timer(
            _catalog_project_root(self.catalog),
            "record.render.relationship_panel",
            details={"record_type": self.entity.entity_type, "record_id": self.entity.key},
            source="minimalist_library",
            page_tool="library_record",
        ):
            with perf_timer(
                _catalog_project_root(self.catalog),
                "record.relationship_render",
                details={"record_type": self.entity.entity_type, "record_id": self.entity.key, "approach": "custom_painted_canvas"},
                source="minimalist_library",
                page_tool="library_record",
            ):
                self.left_title, left_entities, self.right_title, right_entities, self.badges = relationship_groups(self.entity, self.catalog)
                self.left_entities = list(left_entities)
                self.right_entities = list(right_entities)
                self.relationships_loaded = True
                self._calculate_layout()
                log_perf_marker(
                    _catalog_project_root(self.catalog),
                    "record.relationship_widget_count",
                    details={
                        "record_type": self.entity.entity_type,
                        "record_id": self.entity.key,
                        "left_count": len(left_entities),
                        "right_count": len(right_entities),
                        "rendered_left_cards": len(self.left_visible_zones),
                        "rendered_right_cards": len(self.right_visible_zones),
                        "qwidgets_created": 0,
                        "approach": "custom_painted_canvas",
                    },
                    source="minimalist_library",
                    page_tool="library_record",
                )
        self.update()

    def _calculate_layout(self) -> None:
        with perf_timer(
            _catalog_project_root(self.catalog),
            "record.render.relationship_layout_calc",
            details={
                "record_type": self.entity.entity_type,
                "record_id": self.entity.key,
                "left_count": len(self.left_entities),
                "right_count": len(self.right_entities),
            },
            source="minimalist_library",
            page_tool="library_record",
        ):
            width = max(1, self.width())
            height = max(1, self.height())
            diagram_top = min(max(self.DIAGRAM_TOP_PADDING, 104), max(104, height - 232))
            diagram_bottom = max(diagram_top + 180, height - self.DIAGRAM_BOTTOM_PADDING)
            center_x = width / 2
            center_y = (diagram_top + diagram_bottom) / 2
            self.center_rect = QRect(round(center_x - 93), round(center_y - 93), 186, 186)
            self.left_zones = self._layout_side_zones(self.left_entities, "left", self.center_rect, diagram_top, diagram_bottom)
            self.right_zones = self._layout_side_zones(self.right_entities, "right", self.center_rect, diagram_top, diagram_bottom)
            self.hit_zones = [zone for zone in [*self.left_zones, *self.right_zones] if zone.entity is not None]

    def _layout_side_zones(self, entities: list[LibraryEntity], side: str, center_rect: QRect, top: int, bottom: int) -> list[RelationshipCanvasZone]:
        if not entities:
            return []
        if len(entities) > self.MAX_VISIBLE_SIDE_ITEMS:
            visible_entities = entities[: self.MAX_VISIBLE_SIDE_ITEMS - 1]
            hidden_count = len(entities) - len(visible_entities)
        else:
            visible_entities = list(entities)
            hidden_count = 0
        layout_items: list[RelationshipCanvasZone] = [
            RelationshipCanvasZone(QRect(), side, entity, self.badges.get((entity.entity_type, entity.key), ""))
            for entity in visible_entities
        ]
        if hidden_count:
            layout_items.append(RelationshipCanvasZone(QRect(), side, None, more_count=hidden_count))
        column_counts = self._column_counts(len(layout_items))
        column_count = max(1, len(column_counts))
        side_width = (center_rect.left() if side == "left" else self.width() - center_rect.right()) - self.SIDE_MARGIN - self.CENTER_CONNECTOR_GAP
        max_card_w = int((side_width - max(0, column_count - 1) * self.RELATED_COLUMN_GAP) // column_count)
        card_w = max(self.RELATED_CARD_MIN_WIDTH, min(self.RELATED_CARD_WIDTH, max_card_w))
        card_h = self.RELATED_CARD_HEIGHT
        cursor = 0
        columns: list[list[RelationshipCanvasZone]] = []
        for count in column_counts:
            columns.append(layout_items[cursor : cursor + count])
            cursor += count
        center_y = center_rect.center().y()
        if side == "left":
            near_x = center_rect.left() - self.CENTER_CONNECTOR_GAP - card_w
            x_for_column = lambda column: near_x - column * (card_w + self.RELATED_COLUMN_GAP)
        else:
            near_x = center_rect.right() + self.CENTER_CONNECTOR_GAP
            x_for_column = lambda column: near_x + column * (card_w + self.RELATED_COLUMN_GAP)
        for column_index, column_items in enumerate(columns):
            total_height = len(column_items) * card_h + max(0, len(column_items) - 1) * self.RELATED_CARD_GAP
            y = round(center_y - total_height / 2)
            y = max(top, min(y, bottom - total_height))
            x = round(x_for_column(column_index))
            for row_index, zone in enumerate(column_items):
                zone.rect = QRect(x, y + row_index * (card_h + self.RELATED_CARD_GAP), card_w, card_h)
        return layout_items

    def _draw_connectors(self, painter: QPainter) -> None:
        related = [zone for zone in [*self.left_zones, *self.right_zones] if zone.entity is not None]
        connector_alpha = 64 if len(related) > 6 else 92
        base = self.RELATIONSHIP_CONNECTOR_COLOR
        pen = QPen(QColor(base.red(), base.green(), base.blue(), connector_alpha), 1.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        center_y = self.center_rect.center().y()
        for zone in related:
            if zone.side == "left":
                start = QPointF(self.center_rect.left(), center_y)
                end = QPointF(zone.rect.right(), zone.rect.center().y())
            else:
                start = QPointF(self.center_rect.right(), center_y)
                end = QPointF(zone.rect.left(), zone.rect.center().y())
            self._draw_connector(painter, start, end)
            self._draw_count_badge(painter, _point_between(start, end, 0.62), "1", self.RELATIONSHIP_BADGE_COLOR, compact=len(related) > 6)

    def _draw_connector(self, painter: QPainter, start: QPointF, end: QPointF) -> None:
        path = QPainterPath(start)
        midpoint_x = (start.x() + end.x()) / 2
        path.cubicTo(QPointF(midpoint_x, start.y()), QPointF(midpoint_x, end.y()), end)
        painter.drawPath(path)

    def _draw_count_badge(self, painter: QPainter, center: QPointF, text: str, color: QColor, *, compact: bool = False) -> None:
        side = 20 if compact else 24
        rect = QRectF(center.x() - side / 2, center.y() - side / 2, side, side)
        painter.setBrush(QColor(color.red(), color.green(), color.blue(), 106 if compact else 138))
        painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 206 if compact else 230), 1.0 if compact else 1.2))
        painter.drawEllipse(rect)
        painter.setFont(_font(7.8 if compact else 8.5, 760))
        painter.setPen(QColor("#ffffff"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_center_node(self, painter: QPainter) -> None:
        rect = QRectF(self.center_rect)
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        halo = QRadialGradient(rect.center(), rect.width() * 0.72)
        halo.setColorAt(0.0, QColor(0, 126, 255, 44))
        halo.setColorAt(0.62, QColor(0, 82, 190, 12))
        halo.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(rect.adjusted(-22, -22, 22, 22), halo)
        painter.restore()
        painter.setBrush(QColor(6, 19, 40, 212))
        painter.setPen(QPen(QColor("#04b76f"), 1.6))
        painter.drawEllipse(rect)
        icon_side = 50
        icon = glyph_icon({ENTITY_MACHINE: "machine", ENTITY_EOAT: "eoat", ENTITY_TOOL: "grid"}.get(self.entity.entity_type, "library"), QColor("#d7e8ff"), icon_side).pixmap(icon_side, icon_side)
        painter.drawPixmap(round(rect.center().x() - icon.width() / 2), round(rect.top() + 36), icon)
        self._draw_text_fit(painter, self.entity.title, rect.adjusted(14, 88, -14, -72), QColor("#ffffff"), 13.5, 820, align=Qt.AlignmentFlag.AlignCenter)
        painter.setFont(_font(8.8, 500))
        painter.setPen(QColor("#c2ccdc"))
        painter.drawText(rect.adjusted(12, 116, -12, -42), Qt.AlignmentFlag.AlignCenter, clipped_text(self.entity.subtitle, 28))
        status, tone = record_status_display(self.entity)
        color = QColor("#20df72") if tone == "good" else QColor("#ffb145")
        painter.setPen(color)
        painter.setFont(_font(7.8, 680))
        painter.drawText(rect.adjusted(44, rect.height() - 35, -44, -12), Qt.AlignmentFlag.AlignCenter, status)

    def _draw_entity_card(self, painter: QPainter, zone: RelationshipCanvasZone) -> None:
        if zone.entity is None:
            return
        rect = QRectF(zone.rect).adjusted(0.5, 0.5, -0.5, -0.5)
        hover = zone is self.hover_zone
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        painter.fillPath(path, QColor(7, 22, 45, 226 if hover else 210))
        painter.setPen(QPen(QColor(75, 116, 157, 182 if hover else 128), 1.0))
        painter.drawPath(path)
        icon_rect = QRectF(rect.left() + 10, rect.top() + 11, 38, 38)
        painter.setBrush(QColor(8, 28, 58, 100))
        painter.setPen(QPen(QColor(94, 146, 204, 105), 1.0))
        painter.drawRoundedRect(icon_rect, 7, 7)
        glyph = {ENTITY_MACHINE: "machine", ENTITY_EOAT: "eoat", ENTITY_TOOL: "grid"}.get(zone.entity.entity_type, "library")
        pix = glyph_icon(glyph, QColor("#d7e8ff"), 23).pixmap(23, 23)
        painter.drawPixmap(round(icon_rect.center().x() - pix.width() / 2), round(icon_rect.center().y() - pix.height() / 2), pix)
        right_reserve = 58 if zone.badge else 20
        self._draw_text_fit(painter, zone.entity.title, QRectF(rect.left() + 60, rect.top() + 9, rect.width() - 60 - right_reserve, 21), QColor("#ffffff"), 9.8, 760, min_point_size=7.8)
        painter.setFont(_font(8.2, 500))
        painter.setPen(QColor("#b9c5d7"))
        painter.drawText(QRectF(rect.left() + 60, rect.top() + 32, rect.width() - 76, 19), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, clipped_text(zone.entity.subtitle, 26))
        if zone.badge:
            badge_rect = QRectF(rect.right() - 58, rect.top() + 7, 48, 17)
            badge_path = QPainterPath()
            badge_path.addRoundedRect(badge_rect, 7, 7)
            painter.fillPath(badge_path, QColor(0, 126, 255, 76))
            painter.setFont(_font(6.2, 760))
            painter.setPen(QColor("#9be4ff"))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, zone.badge)

    def _draw_more_card(self, painter: QPainter, zone: RelationshipCanvasZone) -> None:
        rect = QRectF(zone.rect).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        painter.fillPath(path, QColor(7, 22, 45, 184))
        painter.setPen(QPen(QColor(75, 116, 157, 116), 1.0))
        painter.drawPath(path)
        painter.setFont(_font(12, 800))
        painter.setPen(QColor("#9be4ff"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"+{zone.more_count} more")

    def _draw_text_fit(
        self,
        painter: QPainter,
        text: str,
        rect: QRectF,
        color: QColor,
        point_size: float,
        weight: int,
        *,
        min_point_size: float = 8,
        align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    ) -> None:
        raw = str(text or "")
        size = point_size
        while size >= min_point_size:
            font = _font(size, weight)
            if QFontMetrics(font).horizontalAdvance(raw) <= rect.width():
                painter.setFont(font)
                painter.setPen(color)
                painter.drawText(rect, align, raw)
                return
            size -= 0.75
        elided = QFontMetrics(_font(min_point_size, weight)).elidedText(raw, Qt.TextElideMode.ElideRight, round(rect.width()))
        painter.setFont(_font(min_point_size, weight))
        painter.setPen(color)
        painter.drawText(rect, align, elided)

    def _bounds_for(self, zones: list[RelationshipCanvasZone]) -> QRect:
        if not zones:
            return QRect()
        bounds = QRect(zones[0].rect)
        for zone in zones[1:]:
            bounds = bounds.united(zone.rect)
        return bounds

    def _column_counts(self, item_count: int) -> list[int]:
        if item_count <= 0:
            return []
        item_count = min(item_count, self.MAX_VISIBLE_SIDE_ITEMS)
        columns = min(self.MAX_COLUMNS_PER_SIDE, math.ceil(item_count / self.MAX_ROWS_PER_COLUMN))
        base = item_count // columns
        remainder = item_count % columns
        return [base + (1 if index < remainder else 0) for index in range(columns)]


class SummaryMetricsPanel(GlassPanel):
    def __init__(self, detail_data: RecordDetailData, parent=None):
        super().__init__(parent, radius=14, streaks=True)
        self.setObjectName("SummaryMetricsPanel")
        self.set_glass(alpha=78, border_alpha=62, border_color=QColor("#496f9d"), fill_color=QColor("#061226"))
        self.setFixedHeight(118)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(34, 18, 34, 18)
        layout.setSpacing(34)
        for field in detail_data.summary_fields:
            layout.addWidget(MetricBlock(AtlasCardMetric(_metric_icon_for(field.label), _field_text(field.value), field.label)))
        layout.addStretch(1)


class RelationshipMoreLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RelationshipMoreLabel")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class MetricBlock(QWidget):
    def __init__(self, metric: AtlasCardMetric, parent=None):
        super().__init__(parent)
        self._metric = metric
        self.setMinimumWidth(230)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        icon_rect = QRectF(2, 20, 52, 52)
        painter.setBrush(QColor(6, 22, 48, 118))
        painter.setPen(QPen(QColor(88, 130, 178, 92), 1))
        painter.drawEllipse(icon_rect)
        pix = glyph_icon(self._metric.icon, QColor("#dbeaff"), 25).pixmap(25, 25)
        painter.drawPixmap(round(icon_rect.center().x() - pix.width() / 2), round(icon_rect.center().y() - pix.height() / 2), pix)
        painter.setFont(_font(11, 520))
        painter.setPen(QColor("#c7d1df"))
        painter.drawText(QRectF(72, 12, self.width() - 72, 24), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._metric.label)
        painter.setFont(_font(24, 820))
        painter.setPen(QColor("#ffffff"))
        painter.drawText(QRectF(72, 40, self.width() - 72, 38), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._metric.value)
        painter.setFont(_font(9, 500))
        painter.setPen(QColor("#9fb0c7"))
        painter.drawText(QRectF(72, 76, self.width() - 72, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, metric_caption(self._metric))


class RecordDetailsTab(QWidget):
    def __init__(self, detail_data: RecordDetailData, parent=None):
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(14)
        for index, section in enumerate(detail_data.detail_sections):
            layout.addWidget(InfoSectionCard(section), index // 2, index % 2)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)


class RecordDocsTab(QWidget):
    def __init__(
        self,
        detail_data: RecordDetailData,
        *,
        project_root: str = "",
        photo_service: PhotoService | None = None,
        context_id: str = "",
        parent=None,
    ):
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(14)
        layout.addWidget(
            PhotoGalleryCard(
                detail_data,
                project_root=project_root,
                photo_service=photo_service,
                context_id=context_id,
            ),
            0,
            0,
        )
        layout.addWidget(InfoSectionCard(RecordSection("Documentation Checklist", detail_data.documentation_fields)), 0, 1)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)


class RecordHistoryTab(QWidget):
    def __init__(self, detail_data: RecordDetailData, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(InfoSectionCard(RecordSection("Recent History", detail_data.history_fields)))
        layout.addStretch(1)


class InfoSectionCard(GlassPanel):
    def __init__(self, section: RecordSection, parent=None):
        super().__init__(parent, radius=12, streaks=False)
        self.setObjectName("InfoSectionCard")
        self.set_glass(alpha=72, border_alpha=56, border_color=QColor("#426c9d"), fill_color=QColor("#061226"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 20)
        layout.setSpacing(11)
        label = QLabel(section.title)
        label.setObjectName("InfoSectionTitle")
        layout.addWidget(label)
        accent = QFrame()
        accent.setObjectName("InfoSectionAccent")
        accent.setFixedSize(64, 2)
        layout.addWidget(accent)
        if len(section.fields) > 6:
            grid = QGridLayout()
            grid.setContentsMargins(0, 2, 0, 0)
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(10)
            for index, field in enumerate(section.fields):
                grid.addWidget(KeyValueRow(field), index // 2, index % 2)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            layout.addLayout(grid)
        else:
            for field in section.fields:
                layout.addWidget(KeyValueRow(field))
        layout.addStretch(1)


class KeyValueRow(QWidget):
    def __init__(self, field: RecordField, parent=None):
        super().__init__(parent)
        self.setObjectName("KeyValueRow")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        key_label = QLabel(field.label.upper())
        key_label.setObjectName("RecordMetaLabel")
        layout.addWidget(key_label)
        if isinstance(field.value, tuple):
            layout.addWidget(ChipGrid(field.value, max_items=6))
        else:
            text = _field_text(field.value)
            if _field_should_render_as_chip(field.label, text):
                layout.addWidget(ChipLabel(text, tone=_chip_tone_for(text)))
            else:
                val = QLabel(text)
                val.setObjectName("RecordMetaValue")
                val.setProperty("tone", "muted" if _is_missing_value(text) else field.tone)
                if _is_important_field(field.label):
                    val.setProperty("importance", "high")
                val.setWordWrap(True)
                layout.addWidget(val)


class ChipGrid(QWidget):
    def __init__(self, values: tuple[str, ...], *, max_items: int = 6, parent=None):
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(6)
        visible = tuple(str(value) for value in values if str(value or "").strip())[:max_items]
        for index, value in enumerate(visible):
            layout.addWidget(ChipLabel(value), index // 3, index % 3)
        remaining = max(0, len(values) - len(visible))
        if remaining:
            layout.addWidget(ChipLabel(f"+{remaining} more", tone="info"), len(visible) // 3, len(visible) % 3)


class ChipLabel(QLabel):
    def __init__(self, text: str, *, tone: str = "normal", parent=None):
        super().__init__(clipped_text(text, 24), parent)
        self.setObjectName("RecordChip")
        self.setProperty("tone", tone)
        self.setToolTip(text)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class PhotoGroupSection(QWidget):
    TILE_WIDTH = 170
    TILE_HEIGHT = 142
    TILE_GAP = 14

    def __init__(
        self,
        group: RecordPhotoGroup,
        *,
        record_type: str,
        record_id: str,
        project_root: str = "",
        photo_service: PhotoService | None = None,
        context_id: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.group = group
        self.record_type = record_type
        self.record_id = record_id
        self.project_root = project_root
        self.photo_service = photo_service
        self.context_id = context_id
        self._columns = 0
        self.tiles: list[PhotoTile] = []
        self.setObjectName("PhotoGroupSection")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        group_label = QLabel(group.title)
        group_label.setObjectName("PhotoGroupTitle")
        layout.addWidget(group_label)
        self.grid_host = QWidget()
        self.grid_host.setObjectName("PhotoGroupGridHost")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(self.TILE_GAP)
        self.grid.setVerticalSpacing(self.TILE_GAP)
        layout.addWidget(self.grid_host)
        for photo in group.photos:
            self.tiles.append(
                PhotoTile(
                    photo,
                    record_type=record_type,
                    record_id=record_id,
                    project_root=project_root,
                    photo_service=photo_service,
                    context_id=context_id,
                )
            )
        self._apply_columns(3)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_columns(self._columns_for_width(max(1, self.width())))

    def _columns_for_width(self, width: int) -> int:
        return max(1, min(4, (width + self.TILE_GAP) // (self.TILE_WIDTH + self.TILE_GAP)))

    def _apply_columns(self, columns: int) -> None:
        columns = max(1, int(columns or 1))
        if columns == self._columns and self.grid.count() == len(self.tiles):
            return
        while self.grid.count():
            self.grid.takeAt(0)
        self._columns = columns
        for index, tile in enumerate(self.tiles):
            self.grid.addWidget(tile, index // columns, index % columns)
        rows = math.ceil(len(self.tiles) / columns) if self.tiles else 0
        self.grid_host.setMinimumHeight(rows * self.TILE_HEIGHT + max(0, rows - 1) * self.TILE_GAP)
        self.grid.activate()


class PhotoGalleryCard(GlassPanel):
    def __init__(
        self,
        detail_data: RecordDetailData,
        *,
        project_root: str = "",
        photo_service: PhotoService | None = None,
        context_id: str = "",
        parent=None,
    ):
        super().__init__(parent, radius=12, streaks=False)
        self.detail_data = detail_data
        self.project_root = project_root
        self.photo_service = photo_service
        self.context_id = context_id or f"photos:{detail_data.record_type}:{detail_data.record_id}"
        self.setObjectName("InfoSectionCard")
        self.set_glass(alpha=72, border_alpha=56, border_color=QColor("#426c9d"), fill_color=QColor("#061226"))
        self.setMinimumHeight(320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 20)
        layout.setSpacing(12)
        title_text = f"Photos ({detail_data.photo_count} unique)" if detail_data.photo_count else "Photos"
        title = QLabel(title_text)
        title.setObjectName("InfoSectionTitle")
        layout.addWidget(title)
        if not detail_data.photo_groups:
            _log_ui_marker(
                self.project_root,
                "ui.empty_state.show",
                details={
                    "surface": "docs_photos",
                    "title": "No photos indexed for this record.",
                    "record_type": detail_data.record_type,
                    "record_id": detail_data.record_id,
                },
                page_tool="library_record",
            )
            empty = LibraryEmptyState(
                "No photos indexed for this record.",
                "Linked photos will appear here after the photo index is refreshed.",
            )
            layout.addWidget(empty)
            layout.addStretch(1)
            return
        scroll = QScrollArea()
        scroll.setObjectName("PhotoGalleryScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        content.setObjectName("PhotoGalleryContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 6, 0)
        content_layout.setSpacing(22)
        with perf_timer(
            self.project_root,
            "record.photo_gallery.render",
            details={
                "record_type": detail_data.record_type,
                "record_id": detail_data.record_id,
                "photo_count": detail_data.photo_count,
                "group_count": len(detail_data.photo_groups),
            },
            source="minimalist_library",
            page_tool="library_record",
        ):
            rendered_tiles = 0
            for group in detail_data.photo_groups:
                section = PhotoGroupSection(
                    group,
                    record_type=detail_data.record_type,
                    record_id=detail_data.record_id,
                    project_root=self.project_root,
                    photo_service=self.photo_service,
                    context_id=self.context_id,
                )
                content_layout.addWidget(section)
                rendered_tiles += len(section.tiles)
            log_perf_marker(
                self.project_root,
                "record.photo_gallery.tile_count",
                details={
                    "record_type": detail_data.record_type,
                    "record_id": detail_data.record_id,
                    "rendered_tiles": rendered_tiles,
                    "total_photos": detail_data.photo_count,
                    "sync_thumbnail_decode": False,
                },
                source="minimalist_library",
                page_tool="library_record",
            )
        content_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)


def _record_photo_id(photo: RecordPhoto, record_type: str = "", record_id: str = "") -> str:
    return (
        _truthy_text(photo.photo_id)
        or _truthy_text(photo.filename)
        or _truthy_text(photo.path)
        or f"{record_type}:{record_id}:photo"
    )


def _record_photo_candidates(photo: RecordPhoto) -> list[str]:
    return list(dict.fromkeys(path for path in [*(photo.path_candidates or ()), photo.path] if str(path or "").strip()))


def _record_photo_with_path(photo: RecordPhoto, path: str) -> RecordPhoto:
    return RecordPhoto(
        path=str(path),
        filename=photo.filename,
        category=photo.category,
        photo_id=photo.photo_id,
        date_taken=photo.date_taken,
        association=photo.association,
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
        path_candidates=photo.path_candidates,
    )


class PhotoTile(QWidget):
    def __init__(
        self,
        photo: RecordPhoto,
        *,
        record_type: str = "",
        record_id: str = "",
        project_root: str = "",
        load_image: bool = False,
        photo_service: PhotoService | None = None,
        context_id: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.photo = photo
        self.record_type = record_type
        self.record_id = record_id
        self.project_root = project_root
        self.load_image = load_image
        self.photo_service = photo_service
        self.context_id = context_id or f"photos:{record_type}:{record_id}"
        self.photo_id = _record_photo_id(photo, record_type, record_id)
        self.path_candidates = _record_photo_candidates(photo)
        self._display_logged = False
        self._thumbnail_opacity = 1.0
        self._thumbnail_animation: QPropertyAnimation | None = None
        self.setObjectName("PhotoTile")
        self.setMouseTracking(True)
        self.load_error = ""
        self.pixmap = QPixmap()
        self.setFixedSize(170, 142)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._request_thumbnail(priority=90 if load_image else 80)

    def get_thumbnail_opacity(self) -> float:
        return self._thumbnail_opacity

    def set_thumbnail_opacity(self, value: float) -> None:
        self._thumbnail_opacity = max(0.0, min(1.0, float(value)))
        self.update()

    thumbnailOpacity = Property(float, get_thumbnail_opacity, set_thumbnail_opacity)

    def _request_thumbnail(self, *, priority: int) -> None:
        if self.photo_service is None or not self.path_candidates:
            if not self.path_candidates:
                self.load_error = "No photo path candidates"
            return
        try:
            cached = self.photo_service.get_cached_thumbnail(self.photo_id, (320, 180))
            if cached is not None and not cached.isNull():
                log_perf_marker(
                    self.project_root,
                    "photo_service.memory_cache_hit",
                    details={"photo_id": self.photo_id, "context_id": self.context_id, "kind": "thumbnail", "surface": "photo_tile"},
                    source="photo_service",
                    page_tool="photos",
                )
                self._apply_thumbnail(cached, self.photo.path)
                return
            self.photo_service.thumbnail_ready.connect(self._thumbnail_ready)
            self.photo_service.photo_load_failed.connect(self._photo_load_failed)
            self.photo_service.request_thumbnail(self.photo_id, self.path_candidates, (320, 180), priority, self.context_id)
        except Exception as exc:
            self.load_error = f"Thumbnail request failed: {exc}"
            LOGGER.exception("Photo tile thumbnail request failed for %s %s photo=%s", self.record_type, self.record_id, self.photo_id)
            self.update()

    @Slot(str, object, str, str)
    def _thumbnail_ready(self, photo_id: str, image: QImage, resolved_path: str, context_id: str) -> None:
        if photo_id != self.photo_id or context_id != self.context_id:
            return
        self._apply_thumbnail(image, resolved_path)

    @Slot(str, str, str)
    def _photo_load_failed(self, photo_id: str, reason: str, context_id: str) -> None:
        if photo_id != self.photo_id or context_id != self.context_id:
            return
        self.load_error = reason
        self.update()

    def _apply_thumbnail(self, image: QImage, resolved_path: str) -> None:
        if image.isNull():
            return
        with _maybe_perf_timer(
            self.project_root,
            "photo_tile.apply_thumbnail",
            details={"record_type": self.record_type, "record_id": self.record_id, "photo_id": self.photo_id},
        ):
            pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            self.load_error = "Unable to convert thumbnail"
            return
        self.pixmap = pixmap
        if resolved_path:
            self.photo = _record_photo_with_path(self.photo, resolved_path)
        self._start_thumbnail_fade()

    def _start_thumbnail_fade(self) -> None:
        _log_ui_marker(
            self.project_root,
            "ui.thumbnail.fade_in",
            details={
                "surface": "photo_tile",
                "record_type": self.record_type,
                "record_id": self.record_id,
                "photo_id": self.photo_id,
                "duration_ms": 0 if prefers_reduced_motion() else 150,
            },
            page_tool="library_record",
        )
        self._thumbnail_opacity = 0.0 if not prefers_reduced_motion() else 1.0
        if prefers_reduced_motion():
            self.update()
            return
        if self._thumbnail_animation is not None:
            self._thumbnail_animation.stop()
            self._thumbnail_animation.deleteLater()
        animation = QPropertyAnimation(self, b"thumbnailOpacity", self)
        animation.setDuration(150)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._thumbnail_animation = animation
        animation.finished.connect(lambda: setattr(self, "_thumbnail_animation", None))
        animation.start()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            LOGGER.debug(
                "Photo tile clicked: record=%s photo_id=%s path=%s load_success=%s",
                f"{self.record_type.upper()} {self.record_id}".strip() or self.photo.association,
                self.photo_id,
                self.photo.path,
                not self.pixmap.isNull(),
            )
            self.open_lightbox()
            event.accept()
            return
        super().mousePressEvent(event)

    def open_lightbox(self) -> "PhotoLightboxOverlay | None":
        return PhotoLightboxOverlay.open_for(
            self,
            self.photo,
            self.pixmap,
            photo_service=self.photo_service,
            photo_id=self.photo_id,
            path_candidates=self.path_candidates,
        )

    def _show_photo_message(self, message: str) -> None:
        widget = self.parentWidget()
        while widget is not None:
            notifier = getattr(widget, "show_toast", None)
            if callable(notifier):
                notifier(message)
                return
            widget = widget.parentWidget()
        LOGGER.warning("%s Photo=%s path=%s error=%s", message, self.photo.photo_id or self.photo.filename, self.photo.path, self.load_error)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        hover = self.underMouse()
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        painter.fillPath(path, QColor(7, 22, 45, 198 if hover else 176))
        if hover and not self.pixmap.isNull():
            painter.setPen(QPen(QColor(31, 135, 255, 72), 3.2))
            painter.drawPath(path)
        painter.setClipPath(path)
        thumb_rect = QRectF(rect.left() + 8, rect.top() + 8, rect.width() - 16, 88)
        thumb_path = QPainterPath()
        thumb_path.addRoundedRect(thumb_rect, 6, 6)
        painter.fillPath(thumb_path, QColor(4, 13, 27, 185))
        painter.setClipPath(thumb_path)
        if not self.pixmap.isNull():
            scaled = self.pixmap.scaled(thumb_rect.size().toSize(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            painter.setOpacity(self._thumbnail_opacity)
            painter.drawPixmap(round(thumb_rect.center().x() - scaled.width() / 2), round(thumb_rect.center().y() - scaled.height() / 2), scaled)
            painter.setOpacity(1.0)
            if not self._display_logged:
                self._display_logged = True
                log_perf_marker(
                    self.project_root,
                    "photo.tile.thumbnail_display",
                    details={
                        "record_type": self.record_type,
                        "record_id": self.record_id,
                        "photo_id": self.photo.photo_id or self.photo.filename,
                        "path": self.photo.path,
                    },
                    source="minimalist_library",
                    page_tool="library_record",
                )
        else:
            painter.setClipping(False)
            icon = glyph_icon("image", QColor("#8fa6c2"), 30).pixmap(30, 30)
            painter.drawPixmap(round(thumb_rect.center().x() - icon.width() / 2), round(thumb_rect.center().y() - icon.height() / 2), icon)
            if self.load_error:
                painter.setFont(_font(7.4, 620))
                painter.setPen(QColor("#ffb145"))
                painter.drawText(thumb_rect.adjusted(8, 56, -8, -8), Qt.AlignmentFlag.AlignCenter, "Missing")
            painter.setClipPath(path)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(31, 135, 255, 160 if hover else 120), 1))
        painter.drawPath(path)
        painter.setFont(_font(8.8, 740))
        painter.setPen(QColor("#ffffff"))
        painter.drawText(QRectF(rect.left() + 10, rect.top() + 101, rect.width() - 20, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, clipped_text(self.photo.category or self.photo.filename, 24))
        painter.setFont(_font(7.6, 520))
        painter.setPen(QColor("#aebbd0"))
        meta = self.photo.date_taken or self.photo.association or self.photo.filename
        painter.drawText(QRectF(rect.left() + 10, rect.top() + 119, rect.width() - 20, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, clipped_text(meta, 28))


class PhotoLightboxOverlay(QWidget):
    def __init__(
        self,
        photo: RecordPhoto,
        pixmap: QPixmap,
        source_rect: QRect,
        *,
        photo_service: PhotoService | None = None,
        photo_id: str = "",
        path_candidates: list[str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.photo = photo
        self.pixmap = pixmap
        self.photo_service = photo_service
        self.photo_id = photo_id or _record_photo_id(photo)
        self.path_candidates = list(path_candidates or _record_photo_candidates(photo))
        self.context_id = f"lightbox:photo:{self.photo_id}:{id(self)}"
        self._status_message = "Loading full image..." if self.photo_service is not None and self.path_candidates else ""
        if self.photo_service is not None and not self.path_candidates:
            self._status_message = "No image path is indexed."
        self._source_rect = QRect(source_rect)
        self._dim_opacity = 0.0
        self._closing = False
        self._animation_group: QParallelAnimationGroup | None = None
        self.setObjectName("PhotoLightboxOverlay")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.preview = PhotoPreviewSurface(pixmap, self)
        self.preview.setObjectName("PhotoLightboxPreview")
        self.close_button = PhotoLightboxCloseButton(self)
        self.close_button.clicked.connect(self.close_lightbox)
        self.close_button.hide()

    @classmethod
    def open_for(
        cls,
        source_widget: QWidget,
        photo: RecordPhoto,
        pixmap: QPixmap,
        *,
        photo_service: PhotoService | None = None,
        photo_id: str = "",
        path_candidates: list[str] | None = None,
    ) -> "PhotoLightboxOverlay":
        root = source_widget.window()
        overlay = cls(
            photo,
            pixmap,
            QRect(),
            photo_service=photo_service,
            photo_id=photo_id,
            path_candidates=path_candidates,
            parent=root,
        )
        overlay.setGeometry(root.rect())
        top_left = overlay.mapFromGlobal(source_widget.mapToGlobal(QPoint(0, 0)))
        overlay._source_rect = QRect(top_left, source_widget.size())
        overlay.show()
        overlay.raise_()
        overlay.open_lightbox()
        return overlay

    def get_dim_opacity(self) -> float:
        return self._dim_opacity

    def set_dim_opacity(self, value: float) -> None:
        self._dim_opacity = max(0.0, min(1.0, float(value)))
        self.update()

    dimOpacity = Property(float, get_dim_opacity, set_dim_opacity)

    def open_lightbox(self) -> None:
        self.setFocus(Qt.FocusReason.PopupFocusReason)
        self.preview.setGeometry(self._source_rect)
        self.preview.show()
        self.close_button.show()
        self._position_close_button()
        self._animate(self._source_rect, self._target_rect(), 0.0, 1.0, QEasingCurve.Type.OutCubic, closing=False)
        self._request_full_image()

    def close_lightbox(self) -> None:
        if self._closing:
            return
        if self.photo_service is not None:
            self.photo_service.cancel_context(self.context_id)
        self.preview.reset_view()
        self._animate(self.preview.geometry(), self._source_rect, self._dim_opacity, 0.0, QEasingCurve.Type.InOutCubic, closing=True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.isVisible() and not self._closing and self._animation_group is None:
            self.preview.setGeometry(self._target_rect())
        self._position_close_button()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 4, 12, round(206 * self._dim_opacity)))
        if self._status_message and self._dim_opacity > 0.55:
            painter.setFont(_font(9.5, 600))
            painter.setPen(QColor("#d7e8ff"))
            painter.drawText(QRectF(80, self.height() - 58, self.width() - 160, 28), Qt.AlignmentFlag.AlignCenter, self._status_message)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close_lightbox()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        point = event.position().toPoint() if hasattr(event, "position") else event.pos()
        if event.button() == Qt.MouseButton.LeftButton and not self.preview.geometry().contains(point):
            self.close_lightbox()
            event.accept()
            return
        super().mousePressEvent(event)

    def _target_rect(self) -> QRect:
        bounds = QRectF(self.rect()).adjusted(84, 76, -84, -76)
        if bounds.width() <= 20 or bounds.height() <= 20 or self.pixmap.isNull():
            return QRect(80, 80, max(80, self.width() - 160), max(80, self.height() - 160))
        scale = min(bounds.width() / self.pixmap.width(), bounds.height() / self.pixmap.height())
        width = max(180, self.pixmap.width() * scale)
        height = max(140, self.pixmap.height() * scale)
        rect = QRectF(0, 0, width, height)
        rect.moveCenter(bounds.center())
        return rect.toAlignedRect()

    def _animate(self, start_rect: QRect, end_rect: QRect, start_dim: float, end_dim: float, easing: QEasingCurve.Type, *, closing: bool) -> None:
        self._closing = closing
        if self._animation_group is not None:
            self._animation_group.stop()
            self._animation_group.deleteLater()
            self._animation_group = None
        if prefers_reduced_motion():
            self.set_dim_opacity(end_dim)
            self.preview.setGeometry(end_rect)
            self._position_close_button()
            if closing:
                self._finish_close()
            return
        group = QParallelAnimationGroup(self)
        geometry_animation = QPropertyAnimation(self.preview, b"geometry", group)
        geometry_animation.setDuration(230 if not closing else 190)
        geometry_animation.setEasingCurve(easing)
        geometry_animation.setStartValue(start_rect)
        geometry_animation.setEndValue(end_rect)
        geometry_animation.valueChanged.connect(lambda _value: self._position_close_button())
        dim_animation = QPropertyAnimation(self, b"dimOpacity", group)
        dim_animation.setDuration(210 if not closing else 180)
        dim_animation.setEasingCurve(easing)
        dim_animation.setStartValue(start_dim)
        dim_animation.setEndValue(end_dim)
        group.addAnimation(geometry_animation)
        group.addAnimation(dim_animation)
        group.finished.connect(self._finish_close if closing else self._finish_open)
        self._animation_group = group
        group.start()

    def _finish_open(self) -> None:
        if self._animation_group is not None:
            self._animation_group.deleteLater()
            self._animation_group = None
        self.preview.setGeometry(self._target_rect())
        self.preview.reset_view()
        self._position_close_button()

    def _finish_close(self) -> None:
        if self._animation_group is not None:
            self._animation_group.deleteLater()
            self._animation_group = None
        self.hide()
        self.deleteLater()

    def _position_close_button(self) -> None:
        rect = self.preview.geometry()
        side = self.close_button.width()
        x = max(rect.left() + 10, rect.right() - side - 10)
        y = rect.top() + 10
        self.close_button.move(x, y)
        self.close_button.raise_()

    def _request_full_image(self) -> None:
        if self.photo_service is None or not self.path_candidates:
            return
        self.photo_service.full_image_ready.connect(self._full_image_ready)
        self.photo_service.photo_load_failed.connect(self._full_image_failed)
        self.photo_service.request_full_image(self.photo_id, self.path_candidates, 100, self.context_id)

    @Slot(str, object, str, str)
    def _full_image_ready(self, photo_id: str, image: QImage, resolved_path: str, context_id: str) -> None:
        if photo_id != self.photo_id or context_id != self.context_id or self._closing:
            return
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            self._status_message = "Unable to load full image."
            self.update()
            return
        self.pixmap = pixmap
        self.photo = _record_photo_with_path(self.photo, resolved_path) if resolved_path else self.photo
        self.preview.set_pixmap(pixmap)
        self._status_message = ""
        if self._animation_group is None:
            self.preview.setGeometry(self._target_rect())
            self.preview.reset_view()
            self._position_close_button()
        self.update()

    @Slot(str, str, str)
    def _full_image_failed(self, photo_id: str, reason: str, context_id: str) -> None:
        if photo_id != self.photo_id or context_id != self.context_id or self._closing:
            return
        self._status_message = "Unable to load full image."
        _log_ui_marker(
            _widget_project_root(self),
            "ui.error_state.show",
            details={"surface": "lightbox", "photo_id": photo_id, "reason": reason},
            page_tool="library_record",
        )
        LOGGER.warning("Photo lightbox full image failed: photo_id=%s reason=%s", photo_id, reason)
        self.update()


class PhotoPreviewSurface(QWidget):
    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.pixmap = pixmap
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._dragging = False
        self._last_drag_pos = QPointF(0, 0)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self.pixmap = pixmap
        self._constrain_pan()
        self.update()

    def reset_view(self) -> None:
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.update()

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if not delta:
            event.ignore()
            return
        old_zoom = self._zoom
        factor = 1.15 if delta > 0 else 1 / 1.15
        new_zoom = max(1.0, min(5.0, old_zoom * factor))
        if abs(new_zoom - old_zoom) < 0.001:
            event.accept()
            return
        point = event.position() if hasattr(event, "position") else QPointF(event.pos())
        rect = QRectF(self.rect())
        old_center = rect.center() + self._pan
        new_center = old_center + (point - old_center) * (1 - new_zoom / old_zoom)
        self._zoom = new_zoom
        self._pan = new_center - rect.center()
        self._constrain_pan()
        self.update()
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._zoom > 1.001:
            self._dragging = True
            self._last_drag_pos = event.position() if hasattr(event, "position") else QPointF(event.pos())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            point = event.position() if hasattr(event, "position") else QPointF(event.pos())
            self._pan += point - self._last_drag_pos
            self._last_drag_pos = point
            self._constrain_pan()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_view()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.6, 0.6, -0.6, -0.6)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        painter.fillPath(path, QColor(3, 10, 22, 240))
        painter.setClipPath(path)
        if not self.pixmap.isNull():
            scaled_size = QSize(round(rect.width() * self._zoom), round(rect.height() * self._zoom))
            top_left = rect.center() + self._pan - QPointF(scaled_size.width() / 2, scaled_size.height() / 2)
            painter.drawPixmap(QRectF(top_left.x(), top_left.y(), scaled_size.width(), scaled_size.height()), self.pixmap, QRectF(self.pixmap.rect()))
        painter.setClipping(False)
        painter.setPen(QPen(QColor(127, 177, 255, 166), 1.2))
        painter.drawPath(path)

    def _constrain_pan(self) -> None:
        rect = QRectF(self.rect())
        max_x = max(0.0, (rect.width() * self._zoom - rect.width()) / 2)
        max_y = max(0.0, (rect.height() * self._zoom - rect.height()) / 2)
        self._pan.setX(max(-max_x, min(max_x, self._pan.x())))
        self._pan.setY(max(-max_y, min(max_y, self._pan.y())))


class PhotoLightboxCloseButton(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("Close photo preview")

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        hover = self.underMouse()
        painter.setBrush(QColor(5, 18, 36, 226 if hover else 198))
        painter.setPen(QPen(QColor(73, 172, 255, 210 if hover else 150), 1.1))
        painter.drawEllipse(rect)
        if hover:
            painter.setPen(QPen(QColor(31, 135, 255, 82), 3.2))
            painter.drawEllipse(rect)
        painter.setPen(QPen(QColor("#f4fbff"), 2.0))
        pad = 11
        painter.drawLine(QPointF(pad, pad), QPointF(self.width() - pad, self.height() - pad))
        painter.drawLine(QPointF(self.width() - pad, pad), QPointF(pad, self.height() - pad))


def hero_actions(entity: LibraryEntity) -> tuple[str, str]:
    noun = entity.type_label
    return (f"Edit {noun}", "Export PDF")


def relationship_groups(entity: LibraryEntity, catalog: LibraryCatalog) -> tuple[str, list[LibraryEntity], str, list[LibraryEntity], dict[tuple[str, str], str]]:
    with perf_timer(
        _catalog_project_root(catalog),
        "record.relationship_lookup",
        details={"record_type": entity.entity_type, "record_id": entity.key},
        source="minimalist_library",
        page_tool="library_record",
    ):
        badges: dict[tuple[str, str], str] = {}
        if catalog.data_service is not None and catalog.data_service.is_index_ready():
            relationships = catalog.data_service.peek_relationships(entity.entity_type, entity.key)
            if entity.entity_type == ENTITY_EOAT:
                machines = catalog._entities_for(ENTITY_MACHINE, relationships.get("machines", ()))
                tools = catalog._entities_for(ENTITY_TOOL, relationships.get("tools", ()))
                current_ids = {str(value) for value in relationships.get("current_machines", ()) or ()}
                for machine in machines:
                    if machine.key in current_ids:
                        badges[(machine.entity_type, machine.key)] = "CURRENT"
                return "Machines", machines, "Tools", tools, badges
            if entity.entity_type == ENTITY_TOOL:
                return (
                    "EOATs",
                    catalog._entities_for(ENTITY_EOAT, relationships.get("eoats", ())),
                    "Machines",
                    catalog._entities_for(ENTITY_MACHINE, relationships.get("machines", ())),
                    badges,
                )
            current = _truthy_text(relationships.get("current_eoat", ""))
            eoats = catalog._entities_for(ENTITY_EOAT, relationships.get("eoats", ()))
            for eoat in eoats:
                if current and normalized_eoat_key(eoat.key) == normalized_eoat_key(current):
                    badges[(eoat.entity_type, eoat.key)] = "CURRENT"
            return "EOATs", eoats, "Tools", catalog._entities_for(ENTITY_TOOL, relationships.get("tools", ())), badges
        if entity.entity_type == ENTITY_EOAT:
            machines = catalog.related_machines(entity)
            tools = catalog.related_tools(entity)
            current_ids = {
                machine.machine
                for machine in getattr(catalog.bundle, "machines", ())
                if normalized_eoat_key(getattr(machine, "current_eoat", "")) == normalized_eoat_key(entity.key)
            } if catalog.bundle is not None else set()
            for machine in machines:
                if machine.key in current_ids:
                    badges[(machine.entity_type, machine.key)] = "CURRENT"
            return "Machines", machines, "Tools", tools, badges
        if entity.entity_type == ENTITY_TOOL:
            return "EOATs", catalog.related_eoats(entity), "Machines", catalog.related_machines(entity), badges
        eoats = catalog.related_eoats(entity)
        current = _truthy_text(getattr(entity.record, "current_eoat", ""))
        for eoat in eoats:
            if current and normalized_eoat_key(eoat.key) == normalized_eoat_key(current):
                badges[(eoat.entity_type, eoat.key)] = "CURRENT"
        return "EOATs", eoats, "Tools", catalog.related_tools(entity), badges


def relationship_subtitle(entity: LibraryEntity) -> str:
    if entity.entity_type == ENTITY_EOAT:
        return "Current tools and machines using this EOAT."
    if entity.entity_type == ENTITY_TOOL:
        return "EOATs and machines compatible with this tool."
    return "Current EOATs and tools associated with this machine."


def metric_caption(metric: AtlasCardMetric) -> str:
    if metric.label == "Documentation":
        return "Score"
    if metric.label == "Current EOAT":
        return "Resolved"
    return "Current / Compatible"


def _point_between(start: QPointF, end: QPointF, ratio: float) -> QPointF:
    return QPointF(start.x() + (end.x() - start.x()) * ratio, start.y() + (end.y() - start.y()) * ratio)


def _font(point_size: float, weight: int) -> QFont:
    font = QFont("Segoe UI")
    font.setPointSizeF(point_size)
    if weight >= 800:
        font.setWeight(QFont.Weight.Black)
    elif weight >= 700:
        font.setWeight(QFont.Weight.Bold)
    elif weight >= 600:
        font.setWeight(QFont.Weight.DemiBold)
    else:
        font.setWeight(QFont.Weight.Medium)
    return font


def _field_text(value: str | tuple[str, ...]) -> str:
    if isinstance(value, tuple):
        return ", ".join(str(item) for item in value if str(item or "").strip()) or "Not Indexed"
    return str(value or "Not Indexed")


def _load_photo_pixmap(path: Path, *, project_root: str = "") -> tuple[QPixmap, str]:
    with _maybe_perf_timer(
        project_root,
        "photo.thumbnail.load_decode",
        details={"ui_sensitive": "image_decode", "path": str(path), "loader": "QImageReader/QPixmap"},
    ):
        try:
            resolved = path.resolve(strict=False)
            stat = resolved.stat()
        except OSError as exc:
            return QPixmap(), f"stat failed: {exc}"
        cache_key = (str(resolved).casefold(), stat.st_mtime_ns, stat.st_size)
        cached = PHOTO_THUMBNAIL_CACHE.get(cache_key)
        if cached is not None:
            return cached, "cache"

        if resolved.suffix.casefold() not in PHOTO_PREVIEW_EXTENSIONS:
            return QPixmap(), f"unsupported extension {resolved.suffix}"

        reader = QImageReader(str(resolved))
        reader.setAutoTransform(True)
        image = reader.read()
        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
            PHOTO_THUMBNAIL_CACHE[cache_key] = pixmap
            return pixmap, "qt"

        qt_error = reader.errorString()
        if resolved.suffix.casefold() in {".heic", ".heif"}:
            try:
                import pillow_heif
                from PIL import Image, ImageOps

                pillow_heif.register_heif_opener()
                with Image.open(resolved) as pil_image:
                    pil_image = ImageOps.exif_transpose(pil_image)
                    pil_image.thumbnail((3200, 3200))
                    pil_image = pil_image.convert("RGBA")
                    data = pil_image.tobytes("raw", "RGBA")
                    qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format.Format_RGBA8888).copy()
                if not qimage.isNull():
                    pixmap = QPixmap.fromImage(qimage)
                    PHOTO_THUMBNAIL_CACHE[cache_key] = pixmap
                    return pixmap, "pillow_heif"
                return QPixmap(), f"pillow_heif returned null image after Qt error: {qt_error}"
            except Exception as exc:
                return QPixmap(), f"Qt error: {qt_error}; HEIC fallback failed: {exc}"
        return QPixmap(), f"Qt error: {qt_error}"


def _is_missing_value(value: str) -> bool:
    folded = str(value or "").strip().casefold()
    return folded in {"", "not indexed", "missing", "none indexed", "unknown", "--"} or folded.startswith("no ")


def _is_important_field(label: str) -> bool:
    folded = str(label or "").casefold()
    return any(
        token in folded
        for token in (
            "assembly id",
            "machine #",
            "tool #",
            "current eoat",
            "current machine",
            "part family",
            "connection type",
            "air architecture",
            "documentation score",
        )
    )


def _field_should_render_as_chip(label: str, value: str) -> bool:
    folded_label = str(label or "").casefold()
    folded_value = str(value or "").casefold()
    if "status" in folded_label:
        return True
    return folded_value in {"indexed", "missing", "not indexed", "needs review", "good", "complete"}


def _chip_tone_for(value: str) -> str:
    folded = str(value or "").casefold()
    if folded in {"indexed", "good", "complete"}:
        return "good"
    if folded in {"missing", "needs review"}:
        return "warn"
    if folded in {"not indexed", "none indexed", "unknown"}:
        return "muted"
    return "normal"


def _metric_icon_for(label: str) -> str:
    folded = label.casefold()
    if "machine" in folded:
        return "machine"
    if "tool" in folded or "part" in folded:
        return "grid"
    if "eoat" in folded:
        return "eoat"
    if "doc" in folded:
        return "doc"
    return "library"


LIBRARY_WIDGET_STYLES = """
QWidget#LibraryBodyWidget,
QWidget#LibraryBrowseStateView,
QWidget#LibraryRecordStateView,
QWidget#LibraryCardGridHost,
QWidget#LibraryActivePillHost,
QWidget#LibraryComposerValueArea,
QWidget#LibraryRecordStack {
    background: transparent;
}
QLabel#LibraryMainTitle {
    color: #ffffff;
    font-size: 38pt;
    font-weight: 850;
}
QLabel#LibraryMainSubtitle {
    color: #c6d0df;
    font-size: 14.5pt;
    font-weight: 420;
}
QLabel#LibraryPanelHeading {
    color: #f8fbff;
    font-size: 18pt;
    font-weight: 760;
}
QLabel#LibraryMutedText,
QLabel#LibraryEmptySubtitle,
QLabel#RelationshipSubtitle {
    color: #aebbd0;
    font-size: 10pt;
}
QLabel#LibraryEmptyTitle {
    color: #f8fbff;
    font-size: 15pt;
    font-weight: 740;
}
QLineEdit#LibrarySearchInput {
    background: transparent;
    border: 0;
    color: #eef6ff;
    font-size: 13pt;
    selection-background-color: #1f87ff;
}
QLabel#LibraryDropdownLabel,
QLabel#RecordMetaLabel {
    color: #7fb8d8;
    font-size: 8.3pt;
    font-weight: 760;
}
QComboBox#LibraryDropdownCombo {
    background: transparent;
    border: 0;
    color: #ffffff;
    font-size: 10.5pt;
    padding: 0;
}
QComboBox#LibraryDropdownCombo::drop-down {
    border: 0;
    width: 18px;
}
QComboBox QAbstractItemView {
    background: #061226;
    color: #eef6ff;
    border: 1px solid rgba(72, 135, 210, 150);
    selection-background-color: rgba(31, 135, 255, 145);
}
QPushButton#LibrarySecondaryButton {
    background: rgba(7, 20, 42, 150);
    color: #ffffff;
    border: 1px solid rgba(73, 111, 157, 150);
    border-radius: 8px;
    padding: 0 14px;
    min-height: 50px;
    font-size: 10.5pt;
    font-weight: 650;
}
QPushButton#LibrarySecondaryButton:hover,
QPushButton#LibrarySecondaryButton[active="true"] {
    background: rgba(10, 47, 102, 220);
    border-color: rgba(31, 135, 255, 220);
}
QPushButton#LibraryActiveFilterPill {
    background: rgba(20, 58, 104, 184);
    color: #e8f4ff;
    border: 1px solid rgba(104, 190, 255, 162);
    border-radius: 10px;
    padding: 5px 10px;
    font-size: 8.5pt;
    font-weight: 640;
}
QPushButton#LibraryFilterCategory {
    background: transparent;
    color: #cbd8ea;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 8px 10px;
    text-align: left;
    font-size: 9pt;
    font-weight: 650;
}
QPushButton#LibraryFilterCategory:hover,
QPushButton#LibraryFilterCategory[active="true"] {
    background: rgba(20, 70, 130, 145);
    border-color: rgba(31, 135, 255, 160);
    color: #ffffff;
}
QPushButton#LibraryFilterValue {
    background: rgba(7, 22, 45, 180);
    color: #dce8f8;
    border: 1px solid rgba(73, 111, 157, 120);
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 9pt;
    font-weight: 620;
}
QPushButton#LibraryFilterValue:hover,
QPushButton#LibraryFilterValue[active="true"] {
    background: rgba(10, 62, 140, 205);
    border-color: rgba(31, 135, 255, 210);
    color: #ffffff;
}
QLabel#LibraryPopoverTitle,
QLabel#RelationshipGroupLabel,
QLabel#LibraryGroupTitle {
    color: #1496ff;
    font-size: 9pt;
    font-weight: 780;
}
QPushButton#LibraryPaginationButton {
    background: rgba(7, 20, 42, 150);
    color: #dce8f8;
    border: 1px solid rgba(73, 111, 157, 145);
    border-radius: 8px;
    font-size: 11pt;
}
QPushButton#LibraryPaginationButton:hover,
QPushButton#LibraryPaginationButton[active="true"] {
    background: rgba(10, 57, 126, 220);
    border-color: rgba(31, 135, 255, 230);
    color: #ffffff;
}
QPushButton#LibraryPaginationButton:disabled {
    color: rgba(160, 176, 200, 90);
    border-color: rgba(73, 111, 157, 70);
}
QLabel#LibraryPaginationText {
    color: #b9c5d7;
    font-size: 10pt;
    padding-right: 24px;
}
QPushButton#LibraryBackButton {
    background: transparent;
    color: #e4edf8;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 10pt;
    font-weight: 620;
}
QPushButton#LibraryBackButton:hover {
    color: #ffffff;
    border-color: rgba(31, 135, 255, 140);
}
QLabel#RecordHeroType {
    color: #1496ff;
    font-size: 10pt;
    font-weight: 760;
}
QLabel#RecordHeroTitle {
    color: #ffffff;
    font-size: 24pt;
    font-weight: 850;
}
QLabel#RecordHeroSubtitle {
    color: #d6e0ef;
    font-size: 12pt;
}
QFrame#RecordHeroRule {
    background: rgba(120, 156, 202, 58);
}
QFrame#RecordHeroVerticalRule {
    background: rgba(120, 156, 202, 50);
}
QLabel#RecordMetaValue {
    color: #e6eef8;
    font-size: 10.8pt;
    font-weight: 540;
}
QLabel#RecordMetaValue[tone="muted"] {
    color: #8191a8;
    font-style: italic;
}
QLabel#RecordMetaValue[importance="high"] {
    color: #ffffff;
    font-weight: 680;
}
QLabel#RecordChip {
    color: #dcecff;
    background: rgba(16, 50, 92, 148);
    border: 1px solid rgba(91, 150, 218, 132);
    border-radius: 8px;
    padding: 4px 8px;
    font-size: 8.4pt;
    font-weight: 700;
}
QLabel#RecordChip[tone="info"] {
    color: #9be4ff;
    background: rgba(10, 62, 130, 140);
    border-color: rgba(31, 135, 255, 160);
}
QLabel#RecordChip[tone="good"] {
    color: #d9fff0;
    background: rgba(10, 91, 72, 142);
    border-color: rgba(54, 216, 106, 154);
}
QLabel#RecordChip[tone="warn"] {
    color: #ffe7b7;
    background: rgba(114, 69, 16, 136);
    border-color: rgba(245, 177, 69, 154);
}
QLabel#RecordChip[tone="muted"] {
    color: #b6c2d2;
    background: rgba(49, 64, 88, 132);
    border-color: rgba(123, 146, 178, 112);
}
QPushButton#RecordPrimaryAction,
QPushButton#RecordSecondaryAction {
    color: #ffffff;
    border: 1px solid rgba(73, 111, 157, 150);
    border-radius: 8px;
    min-width: 160px;
    min-height: 42px;
    font-size: 10pt;
    font-weight: 660;
}
QPushButton#RecordPrimaryAction {
    background: rgba(10, 82, 185, 220);
    border-color: rgba(31, 135, 255, 230);
}
QPushButton#RecordSecondaryAction {
    background: rgba(7, 20, 42, 145);
}
QPushButton#LibraryTabButton {
    background: transparent;
    color: #bdc8d8;
    border: 0;
    border-bottom: 2px solid transparent;
    padding: 10px 0 12px 0;
    min-width: 104px;
    text-align: left;
    font-size: 10pt;
    font-weight: 600;
}
QPushButton#LibraryTabButton[active="true"] {
    color: #1496ff;
    border-bottom-color: #1496ff;
}
QLabel#RelationshipTitle,
QLabel#InfoSectionTitle {
    color: #ffffff;
    font-size: 14.2pt;
    font-weight: 820;
}
QFrame#InfoSectionAccent {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1496ff, stop:1 rgba(20, 150, 255, 0));
    border: 0;
}
QLabel#PhotoGroupTitle {
    color: #bfeaff;
    font-size: 10pt;
    font-weight: 760;
    padding-top: 2px;
}
QLabel#RelationshipMoreLabel {
    color: #9be4ff;
    background: rgba(7, 22, 45, 160);
    border: 1px solid rgba(73, 135, 210, 130);
    border-radius: 8px;
    font-size: 9pt;
    font-weight: 700;
}
QScrollArea#LibraryBodyScroll {
    background: transparent;
    border: 0;
}
QScrollArea#PhotoGalleryScroll {
    background: transparent;
    border: 0;
}
QScrollArea#LibraryBodyScroll QWidget,
QScrollArea#PhotoGalleryScroll QWidget {
    background: transparent;
}
"""


__all__ = [
    "AtlasMinimalistLibraryPage",
    "AtlasRecordCard",
    "LibraryBrowseCard",
    "LibraryCatalog",
    "LibraryEntity",
    "MinimalistLibraryContent",
    "atlas_card_metrics",
    "card_status_display",
    "machine_current_eoat_display",
    "record_status_display",
    "ENTITY_EOAT",
    "ENTITY_TOOL",
    "ENTITY_MACHINE",
]
