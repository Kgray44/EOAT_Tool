from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field

from core.tool_registry import ToolRegistry

from .page_registry import PAGE_BY_KEY, PAGE_SPECS


@dataclass(frozen=True)
class FeatureSpec:
    id: str
    label: str
    page_key: str
    section: str
    description: str = ""
    commands: tuple[str, ...] = field(default_factory=tuple)
    search_sources: tuple[str, ...] = field(default_factory=tuple)
    report_generators: tuple[str, ...] = field(default_factory=tuple)
    event_listeners: tuple[str, ...] = field(default_factory=tuple)
    help_topics: tuple[str, ...] = field(default_factory=tuple)
    data_dependencies: tuple[str, ...] = field(default_factory=tuple)
    modifies_files: bool = False
    search_terms: tuple[str, ...] = ()
    requires_config: bool = True
    tool_ids: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return self.id

    @property
    def route(self) -> str:
        return f"page:{self.page_key}"

    def searchable_text(self) -> str:
        return " ".join(
            [
                self.id,
                self.label,
                self.page_key,
                self.section,
                self.description,
                *self.commands,
                *self.search_sources,
                *self.report_generators,
                *self.help_topics,
                *self.data_dependencies,
                *self.search_terms,
                *self.tool_ids,
            ]
        ).casefold()

    def to_dict(self) -> dict:
        data = asdict(self)
        data["key"] = self.key
        data["route"] = self.route
        return data


class FeatureRegistry:
    def __init__(self, features: Iterable[FeatureSpec]):
        self._features = tuple(features)
        self._by_key = {feature.id: feature for feature in self._features}

    def list_features(self) -> tuple[FeatureSpec, ...]:
        return self._features

    def get(self, key: str) -> FeatureSpec | None:
        return self._by_key.get(key)

    def search(self, query: str = "", *, section: str = "") -> list[FeatureSpec]:
        needle = query.casefold().strip()
        rows = []
        for feature in self._features:
            if section and section != "All" and feature.section != section:
                continue
            if needle and needle not in feature.searchable_text():
                continue
            rows.append(feature)
        return sorted(rows, key=lambda feature: (feature.section, feature.label.casefold()))

    def validate(self, *, command_ids: Iterable[str] = ()) -> list[str]:
        warnings: list[str] = []
        keys = [feature.id for feature in self._features]
        routes = [feature.route for feature in self._features]
        if len(keys) != len(set(keys)):
            warnings.append("Duplicate feature keys detected.")
        if len(routes) != len(set(routes)):
            warnings.append("Duplicate feature routes detected.")
        for feature in self._features:
            if feature.page_key not in PAGE_BY_KEY:
                warnings.append(f"Feature maps to unknown page: {feature.id} -> {feature.page_key}")
        command_id_set = set(command_ids)
        if command_id_set:
            for feature in self._features:
                if f"nav.{feature.page_key}" not in command_id_set:
                    warnings.append(f"Missing navigation command for feature: {feature.id}")
                for command_id in feature.commands:
                    if command_id.startswith(("nav.", "tool.")):
                        continue
                    if command_id not in command_id_set:
                        warnings.append(f"Missing feature command for {feature.id}: {command_id}")
        return warnings


def build_feature_registry(tool_registry: ToolRegistry | None = None) -> FeatureRegistry:
    tools_by_page = _tool_ids_by_page(tool_registry or _safe_tool_registry())
    features = []
    for spec in PAGE_SPECS:
        tool_ids = tuple(sorted(tools_by_page.get(_normalize(spec.label), ())))
        command_ids = (f"nav.{spec.key}", *tuple(f"tool.{tool_id}" for tool_id in tool_ids))
        features.append(
            FeatureSpec(
                id=spec.key,
                label=spec.label,
                page_key=spec.key,
                section=spec.section,
                description=spec.description,
                commands=command_ids,
                search_sources=_search_sources_for_page(spec.key),
                report_generators=_report_generators_for_page(spec.key),
                event_listeners=tuple(spec.listens_to),
                help_topics=(spec.label, spec.key.replace("_", " ")),
                data_dependencies=_data_dependencies_for_page(spec.key),
                modifies_files=spec.key in _FILE_MODIFYING_PAGES,
                search_terms=(spec.key.replace("_", " "), spec.label),
                requires_config=spec.requires_config,
                tool_ids=tool_ids,
            )
        )
    return FeatureRegistry(features)


def _safe_tool_registry() -> ToolRegistry | None:
    try:
        return ToolRegistry.load()
    except Exception:
        return None


def _tool_ids_by_page(registry: ToolRegistry | None) -> dict[str, list[str]]:
    if registry is None:
        return {}
    by_page: dict[str, list[str]] = {}
    page_lookup = {_normalize(spec.label): _normalize(spec.label) for spec in PAGE_SPECS}
    page_lookup.update({_normalize(spec.key): _normalize(spec.label) for spec in PAGE_SPECS})
    for tool in registry.list_tools():
        page_key = page_lookup.get(_normalize(tool.dashboard_page))
        if page_key:
            by_page.setdefault(page_key, []).append(tool.id)
    return by_page


def _normalize(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


_FILE_MODIFYING_PAGES = {
    "audit",
    "photos",
    "data_import",
    "pm_checklists",
    "reports",
    "scheduled_reports",
    "qr_labels",
    "handoff",
    "workbook_health",
    "backup_manager",
    "release_readiness",
    "settings",
}


def _search_sources_for_page(page_key: str) -> tuple[str, ...]:
    mapping = {
        "audit": ("EOAT Inventory", "Audit History"),
        "press_view": ("EOAT Inventory", "Open Items"),
        "machine_360": ("EOAT Inventory", "Robot_Info", "Photos", "Open Items"),
        "notes": ("Annotations",),
        "tags": ("Annotations",),
        "open_items": ("Annotations", "Action Items", "Validation Findings"),
        "photos": ("Photo Index",),
        "reports": ("Report Folders",),
        "workbook_health": ("Validation Reports", "EOAT Inventory"),
        "performance": ("Performance Logs",),
        "app_health": ("Runtime", "Project Root", "Logs"),
    }
    return mapping.get(page_key, ())


def _report_generators_for_page(page_key: str) -> tuple[str, ...]:
    mapping = {
        "audit_progress": ("audit_progress_report",),
        "compatibility_matrix": ("compatibility_matrix_export",),
        "fmea": ("fmea_evidence_report",),
        "pilot_candidates": ("pilot_ranking_report", "pilot_roi_report"),
        "kpi_dashboard": ("kpi_dashboard_report",),
        "standards_docs": ("documentation_gap_report",),
        "pm_checklists": ("pm_checklist_export",),
        "bom_spares": ("standardization_opportunities_report",),
        "reports": ("daily_summary", "weekly_summary"),
        "handoff": ("final_handoff_package",),
        "qr_labels": ("qr_label_sheet",),
    }
    return mapping.get(page_key, ())


def _data_dependencies_for_page(page_key: str) -> tuple[str, ...]:
    if page_key in {"tool_registry", "settings", "app_health", "performance", "release_readiness"}:
        return ("local_config",)
    if page_key in {"notes", "tags", "open_items"}:
        return ("annotation_db", "EOAT_Master_Tracker.xlsx")
    if page_key in {"photos", "machine_360"}:
        return ("EOAT_Master_Tracker.xlsx", "Photo Index")
    if page_key in {"reports", "scheduled_reports", "handoff"}:
        return ("report_folders", "activity_logs")
    return ("EOAT_Master_Tracker.xlsx",)


__all__ = ["FeatureRegistry", "FeatureSpec", "build_feature_registry"]
