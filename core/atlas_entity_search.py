from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .atlas_models import AtlasDataBundle, EOATRecord, MachineRecord, ToolRecord
from .atlas_utils import (
    display_value,
    normalized_eoat_key,
    normalized_lookup_key,
    normalized_machine_key,
    normalized_tool_key,
)


ENTITY_TYPES = ("eoat", "tool", "machine")


@dataclass(frozen=True)
class EntitySearchItem:
    entity_type: str
    entity_id: str
    display_label: str
    subtitle: str = ""
    aliases: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)
    route_target: dict[str, str] = field(default_factory=dict)

    @property
    def route(self) -> dict[str, str]:
        return self.route_target or route_target(self.entity_type, self.entity_id)


@dataclass(frozen=True)
class EntitySearchResult:
    entity_type: str
    entity_id: str
    display_label: str
    subtitle: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    route_target: dict[str, str] = field(default_factory=dict)
    score: int = 0
    exact: bool = False
    match_kind: str = ""
    source: str = "search"

    @property
    def title(self) -> str:
        return self.display_label

    @property
    def key(self) -> str:
        return self.entity_id

    @property
    def result_type(self) -> str:
        return self.entity_type

    def to_recent_dict(self) -> dict[str, Any]:
        return {
            "type": self.entity_type,
            "id": self.entity_id,
            "displayLabel": self.display_label,
            "subtitle": self.subtitle,
            "metadata": dict(self.metadata),
            "route": dict(self.route_target or route_target(self.entity_type, self.entity_id)),
        }


@dataclass(frozen=True)
class EntitySearchQueryResult:
    query: str
    results: tuple[EntitySearchResult, ...] = ()

    @property
    def exact_matches(self) -> tuple[EntitySearchResult, ...]:
        return tuple(result for result in self.results if result.exact)

    @property
    def top_exact_match(self) -> EntitySearchResult | None:
        return self.exact_matches[0] if self.exact_matches else None


class EntitySearchIndex:
    def __init__(self, items: tuple[EntitySearchItem, ...] = (), *, generation_key: str = ""):
        self.items = items
        self.generation_key = generation_key
        self._by_ref = {self._ref_key(item.entity_type, item.entity_id): item for item in items}
        self._search_rows = tuple((item, _search_aliases(item)) for item in items)

    @classmethod
    def empty(cls) -> "EntitySearchIndex":
        return cls(())

    @classmethod
    def build(cls, bundle: AtlasDataBundle | None) -> "EntitySearchIndex":
        if bundle is None:
            return cls.empty()
        current_machine_by_eoat: dict[str, str] = {}
        for machine in getattr(bundle, "machines", ()) or ():
            current = display_value(getattr(machine, "current_eoat", ""))
            if current:
                current_machine_by_eoat.setdefault(normalized_eoat_key(current), display_value(machine.machine))
        items: list[EntitySearchItem] = []
        items.extend(_eoat_item(record, current_machine_by_eoat) for record in getattr(bundle, "eoats", ()) or ())
        items.extend(_tool_item(record) for record in getattr(bundle, "tools", ()) or ())
        items.extend(_machine_item(record) for record in getattr(bundle, "machines", ()) or ())
        generation_key = "|".join(
            (
                display_value(getattr(bundle, "loaded_at", "")),
                str(len(getattr(bundle, "eoats", ()) or ())),
                str(len(getattr(bundle, "tools", ()) or ())),
                str(len(getattr(bundle, "machines", ()) or ())),
            )
        )
        return cls(tuple(items), generation_key=generation_key)

    def has(self, entity_type: str, entity_id: str) -> bool:
        return self.get(entity_type, entity_id) is not None

    def get(self, entity_type: str, entity_id: str) -> EntitySearchResult | None:
        item = self._by_ref.get(self._ref_key(entity_type, entity_id))
        if item is None:
            return None
        return _result_from_item(item, score=1000, exact=True, match_kind="recent", source="recent")

    def search(self, query: str, *, limit: int = 30) -> EntitySearchQueryResult:
        text = display_value(query)
        folded = " ".join(text.casefold().split())
        compact = normalized_lookup_key(text)
        if not folded and not compact:
            return EntitySearchQueryResult(query=text)
        terms = tuple(term for term in (normalized_lookup_key(part) for part in folded.split()) if term)
        scored: list[EntitySearchResult] = []
        for item, aliases in self._search_rows:
            score, exact, match_kind = _score_item(item, aliases, folded, compact, terms)
            if score <= 0:
                continue
            scored.append(_result_from_item(item, score=score, exact=exact, match_kind=match_kind))
        scored.sort(key=_result_sort_key)
        return EntitySearchQueryResult(query=text, results=tuple(scored[: max(0, int(limit or 0))]))

    def _ref_key(self, entity_type: str, entity_id: str) -> tuple[str, str]:
        kind = normalize_entity_type(entity_type)
        return kind, normalize_entity_id(kind, entity_id)


def normalize_entity_type(entity_type: str) -> str:
    text = display_value(entity_type).casefold()
    if text in {"eoat", "tool", "machine"}:
        return text
    if "machine" in text or "press" in text:
        return "machine"
    if "tool" in text or "mold" in text:
        return "tool"
    if "eoat" in text:
        return "eoat"
    return text


def normalize_entity_id(entity_type: str, entity_id: str) -> str:
    kind = normalize_entity_type(entity_type)
    if kind == "eoat":
        return normalized_eoat_key(entity_id)
    if kind == "machine":
        return normalized_machine_key(entity_id)
    if kind == "tool":
        return normalized_tool_key(entity_id)
    return normalized_lookup_key(entity_id)


def route_target(entity_type: str, entity_id: str) -> dict[str, str]:
    return {"page": "library", "entity_type": normalize_entity_type(entity_type), "entity_id": display_value(entity_id)}


def entity_type_label(entity_type: str) -> str:
    return {"eoat": "EOAT", "tool": "Tool", "machine": "Machine"}.get(normalize_entity_type(entity_type), "Record")


def result_from_recent_dict(raw: dict[str, Any], index: EntitySearchIndex | None = None) -> EntitySearchResult | None:
    entity_type = normalize_entity_type(str(raw.get("type") or raw.get("entity_type") or ""))
    entity_id = display_value(raw.get("id") or raw.get("entity_id") or "")
    if not entity_type or not entity_id:
        return None
    if index is not None:
        current = index.get(entity_type, entity_id)
        if current is not None:
            return current
    label = display_value(raw.get("displayLabel") or raw.get("display_label") or raw.get("label") or entity_id)
    subtitle = display_value(raw.get("subtitle") or "")
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    route = raw.get("route") if isinstance(raw.get("route"), dict) else route_target(entity_type, entity_id)
    return EntitySearchResult(
        entity_type=entity_type,
        entity_id=entity_id,
        display_label=label,
        subtitle=subtitle,
        metadata={str(key): display_value(value) for key, value in metadata.items()},
        route_target={str(key): display_value(value) for key, value in route.items()},
        score=1000,
        exact=True,
        match_kind="recent",
        source="recent",
    )


def _eoat_item(record: EOATRecord, current_machine_by_eoat: dict[str, str]) -> EntitySearchItem:
    current_machine = current_machine_by_eoat.get(normalized_eoat_key(record.eoat_id), "")
    relationship = _relationship_summary(
        ("Tools", getattr(record, "tools", ())),
        ("Machines", getattr(record, "machines", ())),
    )
    subtitle = _join_preview(record.eoat_type or "EOAT", record.status, relationship)
    metadata = {
        "id_label": "EOAT ID",
        "id_value": display_value(record.eoat_id),
        "status": display_value(record.status),
        "current_machine": f"Machine {current_machine}" if current_machine else "",
        "relationships": relationship,
    }
    aliases = _unique_texts(
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
    )
    return EntitySearchItem(
        "eoat",
        record.eoat_id,
        record.eoat_id,
        subtitle,
        aliases=aliases,
        metadata={key: value for key, value in metadata.items() if value},
        route_target=route_target("eoat", record.eoat_id),
    )


def _tool_item(record: ToolRecord) -> EntitySearchItem:
    relationship = _relationship_summary(
        ("EOATs", getattr(record, "compatible_eoats", ())),
        ("Machines", getattr(record, "compatible_machines", ())),
    )
    subtitle = _join_preview(record.part_description or record.part_family or "Tool / Mold", relationship)
    metadata = {
        "id_label": "Tool #",
        "id_value": display_value(record.tool),
        "relationships": relationship,
        "part": display_value(record.part_description or record.part_family),
    }
    aliases = _unique_texts(
        record.tool,
        record.label,
        record.molds,
        record.parts,
        record.part_family,
        record.part_description,
        record.compatible_eoats,
        record.compatible_machines,
        record.source,
    )
    return EntitySearchItem(
        "tool",
        record.tool,
        display_value(record.tool),
        subtitle,
        aliases=aliases,
        metadata={key: value for key, value in metadata.items() if value},
        route_target=route_target("tool", record.tool),
    )


def _machine_item(record: MachineRecord) -> EntitySearchItem:
    current = display_value(record.current_eoat)
    relationship = _relationship_summary(
        ("EOATs", getattr(record, "compatible_eoats", ())),
        ("Tools", getattr(record, "compatible_tools", ())),
    )
    subtitle = _join_preview(record.robot_type or record.robot_model or "Machine profile", f"Current EOAT {current}" if current else "", relationship)
    metadata = {
        "id_label": "Machine #",
        "id_value": display_value(record.machine),
        "current_eoat": current,
        "relationships": relationship,
        "robot": display_value(record.robot_type or record.robot_model),
    }
    aliases = _unique_texts(
        record.machine,
        record.label,
        f"machine {record.machine}",
        f"press {record.machine}",
        f"m{record.machine}",
        record.robot_type,
        record.robot_model,
        record.controller,
        record.compatible_eoats,
        record.compatible_tools,
        record.compatible_parts,
        record.current_eoat,
    )
    return EntitySearchItem(
        "machine",
        record.machine,
        f"Machine {record.machine}",
        subtitle,
        aliases=aliases,
        metadata={key: value for key, value in metadata.items() if value},
        route_target=route_target("machine", record.machine),
    )


def _search_aliases(item: EntitySearchItem) -> tuple[tuple[str, str], ...]:
    aliases = _unique_texts(item.entity_id, item.display_label, item.subtitle, item.aliases, tuple(item.metadata.values()))
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for alias in aliases:
        text = display_value(alias).casefold()
        compact = normalized_lookup_key(alias)
        key = f"{text}|{compact}"
        if not text and not compact:
            continue
        if key in seen:
            continue
        seen.add(key)
        rows.append((text, compact))
    return tuple(rows)


def _score_item(
    item: EntitySearchItem,
    aliases: tuple[tuple[str, str], ...],
    folded: str,
    compact: str,
    terms: tuple[str, ...],
) -> tuple[int, bool, str]:
    primary = normalize_entity_id(item.entity_type, item.entity_id)
    label_compact = normalized_lookup_key(item.display_label)
    exact_id = bool(compact and compact in {primary, label_compact})
    if exact_id:
        return 1200, True, "exact-id"
    exact_alias = bool(compact and any(compact == alias_compact for _alias_text, alias_compact in aliases))
    if exact_alias:
        return 1080, True, "exact-alias"
    if compact and (primary.startswith(compact) or label_compact.startswith(compact)):
        return 880, False, "prefix-id"
    if compact and any(alias_compact.startswith(compact) for _alias_text, alias_compact in aliases):
        return 780, False, "prefix"
    if folded and any(folded in alias_text for alias_text, _alias_compact in aliases):
        return 620, False, "contains"
    if compact and any(compact in alias_compact for _alias_text, alias_compact in aliases):
        return 560, False, "compact-contains"
    if terms and all(any(term in alias_compact for _alias_text, alias_compact in aliases) for term in terms):
        return 480, False, "token"
    return 0, False, ""


def _result_from_item(
    item: EntitySearchItem,
    *,
    score: int,
    exact: bool,
    match_kind: str,
    source: str = "search",
) -> EntitySearchResult:
    return EntitySearchResult(
        entity_type=item.entity_type,
        entity_id=item.entity_id,
        display_label=item.display_label,
        subtitle=item.subtitle,
        metadata=dict(item.metadata),
        route_target=dict(item.route),
        score=score,
        exact=exact,
        match_kind=match_kind,
        source=source,
    )


def _result_sort_key(result: EntitySearchResult) -> tuple[int, int, int, str]:
    type_order = {"eoat": 0, "tool": 1, "machine": 2}.get(result.entity_type, 9)
    return (0 if result.exact else 1, -result.score, type_order, result.display_label.casefold())


def _relationship_summary(*groups: tuple[str, Any]) -> str:
    labels = []
    for label, values in groups:
        count = len(tuple(value for value in values or () if display_value(value)))
        labels.append(f"{count} {label.lower()}" if count != 1 else f"1 {label[:-1].lower()}")
    return " | ".join(labels)


def _join_preview(*values: str) -> str:
    return " | ".join(display_value(value) for value in values if display_value(value))


def _unique_texts(*values: Any) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                add(item)
            return
        if isinstance(value, (tuple, list, set)):
            for item in value:
                add(item)
            return
        text = display_value(value)
        folded = text.casefold()
        if not text or folded in seen:
            return
        seen.add(folded)
        result.append(text)

    for value in values:
        add(value)
    return tuple(result)


__all__ = [
    "ENTITY_TYPES",
    "EntitySearchIndex",
    "EntitySearchItem",
    "EntitySearchQueryResult",
    "EntitySearchResult",
    "entity_type_label",
    "normalize_entity_id",
    "normalize_entity_type",
    "result_from_recent_dict",
    "route_target",
]
