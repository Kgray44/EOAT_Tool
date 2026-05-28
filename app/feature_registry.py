from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from core.tool_registry import ToolRegistry

from .page_registry import PAGE_SPECS


@dataclass(frozen=True)
class FeatureSpec:
    key: str
    label: str
    section: str
    route: str
    description: str = ""
    search_terms: tuple[str, ...] = ()
    requires_config: bool = True
    tool_ids: tuple[str, ...] = ()

    def searchable_text(self) -> str:
        return " ".join([self.key, self.label, self.section, self.description, *self.search_terms, *self.tool_ids]).casefold()

    def to_dict(self) -> dict:
        return asdict(self)


class FeatureRegistry:
    def __init__(self, features: Iterable[FeatureSpec]):
        self._features = tuple(features)
        self._by_key = {feature.key: feature for feature in self._features}

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
        keys = [feature.key for feature in self._features]
        routes = [feature.route for feature in self._features]
        if len(keys) != len(set(keys)):
            warnings.append("Duplicate feature keys detected.")
        if len(routes) != len(set(routes)):
            warnings.append("Duplicate feature routes detected.")
        command_id_set = set(command_ids)
        if command_id_set:
            for feature in self._features:
                if feature.route.startswith("page:") and f"nav.{feature.key}" not in command_id_set:
                    warnings.append(f"Missing navigation command for feature: {feature.key}")
        return warnings


def build_feature_registry(tool_registry: ToolRegistry | None = None) -> FeatureRegistry:
    tools_by_page = _tool_ids_by_page(tool_registry or _safe_tool_registry())
    features = []
    for spec in PAGE_SPECS:
        tool_ids = tuple(sorted(tools_by_page.get(_normalize(spec.label), ())))
        features.append(
            FeatureSpec(
                key=spec.key,
                label=spec.label,
                section=spec.section,
                route=f"page:{spec.key}",
                description=spec.description,
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


__all__ = ["FeatureRegistry", "FeatureSpec", "build_feature_registry"]
