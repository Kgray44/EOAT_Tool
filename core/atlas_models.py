from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AtlasSourceStatus:
    label: str
    path: str
    exists: bool
    available: bool
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WarningItem:
    severity: str
    title: str
    message: str
    source: str = ""
    why_it_matters: str = ""
    suggested_fix: str = ""
    related_eoat_id: str = ""
    machine: str = ""
    tool: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentationStatus:
    score: int = 0
    status_label: str = "Unknown"
    present_fields: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    critical_missing_fields: tuple[str, ...] = ()
    checklist: tuple[tuple[str, str], ...] = ()

    @property
    def missing_count(self) -> int:
        return len(self.missing_fields)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PhotoItem:
    path: str
    filename: str
    category: str = ""
    eoat_id: str = ""
    tool: str = ""
    machine: str = ""
    related_audit_id: str = ""
    source: str = "folder"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PhotoSet:
    eoat_id: str = ""
    folder_path: str = ""
    folder_exists: bool = False
    photos: tuple[PhotoItem, ...] = ()
    indexed_photos: tuple[PhotoItem, ...] = ()
    missing_categories: tuple[str, ...] = ()

    @property
    def photo_count(self) -> int:
        return len(self.photos)

    @property
    def total_count(self) -> int:
        return len({photo.path for photo in (*self.photos, *self.indexed_photos) if photo.path})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StandardReference:
    title: str
    path: str
    category: str = ""
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EOATRecord:
    eoat_id: str
    display_id: str
    audit_ids: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    molds: tuple[str, ...] = ()
    parts: tuple[str, ...] = ()
    machines: tuple[str, ...] = ()
    part_family: str = ""
    part_description: str = ""
    eoat_type: str = ""
    status: str = ""
    robot_types: tuple[str, ...] = ()
    robot_models: tuple[str, ...] = ()
    connection_type: str = ""
    vacuum_info: str = ""
    pressure_info: str = ""
    gripper_info: str = ""
    sensor_info: str = ""
    tubing_notes: str = ""
    install_notes: str = ""
    known_issues: str = ""
    documentation: DocumentationStatus = field(default_factory=DocumentationStatus)
    photos: PhotoSet = field(default_factory=PhotoSet)
    warnings: tuple[WarningItem, ...] = ()
    standards: tuple[StandardReference, ...] = ()
    source_rows: tuple[dict[str, Any], ...] = field(default_factory=tuple, repr=False, compare=False)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    @property
    def photo_count(self) -> int:
        return self.photos.total_count

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("source_rows", None)
        return data


@dataclass(frozen=True)
class MachineRecord:
    machine: str
    label: str
    robot_type: str = ""
    robot_model: str = ""
    controller: str = ""
    compatible_eoats: tuple[str, ...] = ()
    compatible_tools: tuple[str, ...] = ()
    compatible_parts: tuple[str, ...] = ()
    current_eoat: str = ""
    documentation_score: int = 0
    warnings: tuple[WarningItem, ...] = ()
    source_rows: tuple[dict[str, Any], ...] = field(default_factory=tuple, repr=False, compare=False)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("source_rows", None)
        return data


@dataclass(frozen=True)
class ToolRecord:
    tool: str
    label: str
    molds: tuple[str, ...] = ()
    parts: tuple[str, ...] = ()
    part_family: str = ""
    part_description: str = ""
    compatible_eoats: tuple[str, ...] = ()
    compatible_machines: tuple[str, ...] = ()
    source: str = ""
    warnings: tuple[WarningItem, ...] = ()
    source_rows: tuple[dict[str, Any], ...] = field(default_factory=tuple, repr=False, compare=False)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("source_rows", None)
        return data


@dataclass(frozen=True)
class CompatibilityLink:
    eoat_id: str = ""
    machine: str = ""
    tool: str = ""
    part: str = ""
    status: str = "Possible"
    source: str = ""
    reasons: tuple[str, ...] = ()
    warnings: tuple[WarningItem, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SearchMatch:
    result_type: str
    key: str
    title: str
    subtitle: str = ""
    score: float = 0.0
    matched_fields: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecommendationFactor:
    factor_id: str
    label: str
    points: int
    polarity: str
    evidence: str = ""
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecommendationCandidate:
    eoat_id: str
    rank: int
    score: int
    summary: str
    machines: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    warnings: tuple[WarningItem, ...] = ()
    documentation_score: int = 0
    photo_count: int = 0
    factors: tuple[RecommendationFactor, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecommendationResult:
    query: str
    interpreted_as: str
    summary: str
    best: RecommendationCandidate | None = None
    candidates: tuple[RecommendationCandidate, ...] = ()
    matches: tuple[SearchMatch, ...] = ()
    compatible_machines: tuple[str, ...] = ()
    install_checklist: tuple[str, ...] = ()
    warnings: tuple[WarningItem, ...] = ()
    photos: tuple[PhotoItem, ...] = ()
    standards: tuple[StandardReference, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AtlasDataBundle:
    project_root: str
    loaded_at: str
    source_statuses: tuple[AtlasSourceStatus, ...] = ()
    eoats: tuple[EOATRecord, ...] = ()
    machines: tuple[MachineRecord, ...] = ()
    tools: tuple[ToolRecord, ...] = ()
    standards: tuple[StandardReference, ...] = ()
    warnings: tuple[WarningItem, ...] = ()
    indexes: AtlasIndexes = field(default_factory=lambda: AtlasIndexes())
    metrics: dict[str, Any] = field(default_factory=dict)

    def eoat_by_id(self) -> dict[str, EOATRecord]:
        return {record.eoat_id.casefold(): record for record in self.eoats}

    def machine_by_id(self) -> dict[str, MachineRecord]:
        return {record.machine.casefold(): record for record in self.machines}

    def tool_by_id(self) -> dict[str, ToolRecord]:
        return {record.tool.casefold(): record for record in self.tools}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AtlasIndexes:
    eoat_by_id: dict[str, str] = field(default_factory=dict)
    eoats_by_tool: dict[str, tuple[str, ...]] = field(default_factory=dict)
    eoats_by_machine: dict[str, tuple[str, ...]] = field(default_factory=dict)
    machines_by_tool: dict[str, tuple[str, ...]] = field(default_factory=dict)
    machines_by_eoat: dict[str, tuple[str, ...]] = field(default_factory=dict)
    tools_by_machine: dict[str, tuple[str, ...]] = field(default_factory=dict)
    photos_by_eoat: dict[str, tuple[str, ...]] = field(default_factory=dict)
    photos_by_tool: dict[str, tuple[str, ...]] = field(default_factory=dict)
    robot_info_by_machine: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings_by_eoat: dict[str, tuple[WarningItem, ...]] = field(default_factory=dict)
    warnings_by_machine: dict[str, tuple[WarningItem, ...]] = field(default_factory=dict)
    documentation_status_by_eoat: dict[str, DocumentationStatus] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
