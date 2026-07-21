from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.atlas_entity_search import (
    EntitySearchIndex,
    EntitySearchResult,
    entity_type_label,
    normalize_entity_id,
    normalize_entity_type,
    result_from_recent_dict,
)
from core.atlas_search import interpret_query, resolve_search_query
from core.globalization.runtime_paths import ensure_runtime_layout, get_runtime_paths


@dataclass(frozen=True)
class MinimalistSearchEntry:
    label: str
    query: str
    kind: str
    opener: Callable[[], None] | None = None
    placeholder: bool = False
    entity_type: str = ""
    entity_id: str = ""
    subtitle: str = ""
    route_target: dict[str, str] | None = None
    stale: bool = False


PAGE_LABELS = {
    "home": "Home",
    "minimalist_home": "Home",
    "what": "What Do I Need?",
    "setup_packet": "Packet Builder",
    "packet_builder": "Packet Builder",
    "library": "Library",
    "eoats": "EOAT Profiles",
    "machines": "Machine Profiles",
    "fit_check": "Fit Check",
    "matrix": "Fit Check",
    "photos": "Photos",
    "standards": "Standards & WI",
    "reports": "Reports",
    "settings": "Settings",
    "diagnostics": "Settings",
    "data_health": "Data Health",
}

RECENT_SEARCH_KINDS = {"EOAT", "Machine", "Tool / Mold", "Part"}
RECENT_SEARCH_BLOCKLIST = {
    "refresh",
    "refresh data",
    "refresh view",
    "deep refresh",
    "rebuild cache",
    "refresh from workbook",
    "reload",
    "reload data",
    "reload from workbook",
    "sync from workbook",
    "queue status review",
    "mark needs review",
    "pending status update",
    "export",
    "library",
    "open library",
    "settings",
    "open settings",
    "home",
    "open home",
    "fit check",
    "open fit check",
    "packet builder",
    "open packet builder",
}


def page_label(key: str) -> str:
    return PAGE_LABELS.get(str(key or ""), str(key or "Page"))


def recent_entries(controller, bundle, *, limit: int = 5) -> list[MinimalistSearchEntry]:
    index = _controller_search_index(controller, bundle)
    entries: list[MinimalistSearchEntry] = []
    seen_refs: set[tuple[str, str]] = set()
    changed = False
    kept_items: list[dict[str, Any]] = []
    for item in _load_raw_recent_items(limit=limit * 4):
        result = _recent_result_for_item(item, index)
        if result is None:
            changed = True
            continue
        ref = (result.entity_type, normalize_entity_id(result.entity_type, result.entity_id))
        if ref in seen_refs:
            changed = True
            continue
        seen_refs.add(ref)
        kept_items.append(_recent_dict_from_result(result, query=str(item.get("query") or item.get("searchQuery") or "")))
        entries.append(_entry_from_result(controller, result))
        if len(entries) >= limit:
            break
    for result in _settings_recent_results(controller, index):
        ref = (result.entity_type, normalize_entity_id(result.entity_type, result.entity_id))
        if ref in seen_refs:
            continue
        seen_refs.add(ref)
        entries.append(_entry_from_result(controller, result))
        if len(entries) >= limit:
            break
    if changed:
        save_recent_searches(kept_items)
    return entries[:limit]


def _open_recent_search(controller, query: str, kind: str) -> None:
    runner = getattr(controller, "run_search_query", None)
    if callable(runner):
        runner(query, kind=kind, source="recent-search", record_search=False)
        return
    controller.open_recommendation(query, kind=kind, record_search=False)


def recent_searches_path():
    runtime = ensure_runtime_layout(get_runtime_paths())
    return runtime.settings_dir / "atlas_minimalist_recent_searches.json"


def load_recent_searches(*, limit: int = 8) -> list[dict[str, str]]:
    searches: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in _load_raw_recent_items(limit=limit * 3):
        if isinstance(item, str):
            query = item.strip()
            kind = ""
        elif isinstance(item, dict):
            entity_type = normalize_entity_type(str(item.get("type") or item.get("entity_type") or ""))
            entity_id = str(item.get("id") or item.get("entity_id") or "").strip()
            query = str(item.get("query") or item.get("searchQuery") or item.get("displayLabel") or entity_id or "").strip()
            kind = str(item.get("kind", "") or "").strip()
            if entity_type and entity_id and not kind:
                kind = entity_type_label(entity_type) if entity_type != "tool" else "Tool / Mold"
        else:
            continue
        ref_key = _recent_dedupe_key(item, query)
        if not query or ref_key in seen:
            continue
        if not isinstance(item, dict) or not (item.get("type") or item.get("entity_type")):
            if _is_blocked_recent_query(query):
                continue
        seen.add(ref_key)
        row = {"query": query, "kind": kind}
        if isinstance(item, dict):
            for key in ("type", "id", "displayLabel", "subtitle", "route"):
                if key in item:
                    row[key] = item[key]  # type: ignore[assignment]
        searches.append(row)
        if len(searches) >= limit:
            break
    return searches


def save_recent_searches(searches: list[dict[str, Any]]) -> None:
    path = recent_searches_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items": searches[:15]}, indent=2), encoding="utf-8")


def record_recent_search(query: str, *, kind: str = "", bundle=None, limit: int = 10) -> list[dict[str, str]]:
    text = str(query or "").strip()
    if not text:
        return load_recent_searches(limit=limit)
    resolved_kind = kind.strip() or infer_search_kind(text, bundle)
    if not is_recent_search_allowed(text, kind=resolved_kind, bundle=bundle):
        return load_recent_searches(limit=limit)
    entity_result = _resolve_query_to_recent_result(text, bundle)
    if entity_result is not None:
        record_recent_entity_result(entity_result, query=text, limit=max(limit, 15))
        return load_recent_searches(limit=limit)
    folded = text.casefold()
    existing = [item for item in load_recent_searches(limit=limit) if item["query"].casefold() != folded]
    searches = [{"query": text, "kind": resolved_kind}, *existing]
    save_recent_searches(searches[:limit])
    return searches[:limit]


def record_recent_entity_result(result: EntitySearchResult, *, query: str = "", limit: int = 15) -> list[dict[str, Any]]:
    item = _recent_dict_from_result(result, query=query)
    return record_recent_entity_item(item, limit=limit)


def record_recent_entity_item(item: dict[str, Any], *, limit: int = 15) -> list[dict[str, Any]]:
    entity_type = normalize_entity_type(str(item.get("type") or item.get("entity_type") or ""))
    entity_id = str(item.get("id") or item.get("entity_id") or "").strip()
    if not entity_type or not entity_id:
        return _load_raw_recent_items(limit=limit)
    ref = (entity_type, normalize_entity_id(entity_type, entity_id))
    existing = [
        raw
        for raw in _load_raw_recent_items(limit=limit * 2)
        if not _same_recent_ref(
            entity_type,
            entity_id,
            str(raw.get("type") or raw.get("entity_type") or ""),
            str(raw.get("id") or raw.get("entity_id") or ""),
        )
    ]
    normalized = {
        "type": entity_type,
        "id": entity_id,
        "displayLabel": str(item.get("displayLabel") or item.get("display_label") or item.get("label") or entity_id).strip(),
        "subtitle": str(item.get("subtitle") or "").strip(),
        "kind": entity_type_label(entity_type) if entity_type != "tool" else "Tool / Mold",
        "query": str(item.get("query") or item.get("searchQuery") or entity_id).strip(),
        "route": item.get("route") if isinstance(item.get("route"), dict) else {"page": "library", "entity_type": entity_type, "entity_id": entity_id},
        "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
    }
    searches = [normalized, *existing]
    save_recent_searches(searches[:limit])
    return searches[:limit]


def remove_recent_entity(entity_type: str, entity_id: str, *, limit: int = 15) -> None:
    items = [
        item
        for item in _load_raw_recent_items(limit=limit * 2)
        if not _same_recent_ref(
            entity_type,
            entity_id,
            str(item.get("type") or item.get("entity_type") or ""),
            str(item.get("id") or item.get("entity_id") or ""),
        )
    ]
    save_recent_searches(items[:limit])


def is_recent_search_allowed(query: str, *, kind: str = "", bundle=None) -> bool:
    text = str(query or "").strip()
    if not text or _is_blocked_recent_query(text):
        return False
    resolved_kind = str(kind or "").strip() or infer_search_kind(text, bundle)
    return resolved_kind in RECENT_SEARCH_KINDS


def _load_raw_recent_items(*, limit: int = 15) -> list[dict[str, Any]]:
    try:
        raw = json.loads(recent_searches_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get("items", raw) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            text = item.strip()
            if text:
                normalized.append({"query": text, "kind": ""})
        elif isinstance(item, dict):
            normalized.append(dict(item))
        if len(normalized) >= limit:
            break
    return normalized


def _controller_search_index(controller, bundle) -> EntitySearchIndex:
    getter = getattr(controller, "entity_search_index", None)
    if callable(getter):
        index = getter()
        if isinstance(index, EntitySearchIndex):
            return index
    index = getattr(controller, "_entity_search_index", None)
    if isinstance(index, EntitySearchIndex):
        return index
    return EntitySearchIndex.build(bundle)


def _recent_result_for_item(item: dict[str, Any], index: EntitySearchIndex) -> EntitySearchResult | None:
    if item.get("type") or item.get("entity_type"):
        result = result_from_recent_dict(item, index)
        if result is None:
            return None
        return result if index.has(result.entity_type, result.entity_id) or not index.items else None
    query = str(item.get("query") or "").strip()
    if not query:
        return None
    result = index.search(query, limit=4)
    if result.top_exact_match is not None:
        return result.top_exact_match
    if len(result.results) == 1 and result.results[0].score >= 780:
        return result.results[0]
    return None


def _settings_recent_results(controller, index: EntitySearchIndex) -> list[EntitySearchResult]:
    settings = getattr(controller, "settings", None)
    if settings is None:
        return []
    results: list[EntitySearchResult] = []
    for entity_type, attr in (("eoat", "recent_eoats"), ("tool", "recent_tools"), ("machine", "recent_machines")):
        for key in getattr(settings, attr, ()) or ():
            result = index.get(entity_type, key)
            if result is not None:
                results.append(result)
    return results


def _entry_from_result(controller, result: EntitySearchResult) -> MinimalistSearchEntry:
    return MinimalistSearchEntry(
        label=result.display_label,
        query=result.entity_id,
        kind=entity_type_label(result.entity_type) if result.entity_type != "tool" else "Tool / Mold",
        opener=lambda result=result: _open_recent_entity(controller, result),
        entity_type=result.entity_type,
        entity_id=result.entity_id,
        subtitle=result.subtitle,
        route_target=dict(result.route_target),
    )


def _open_recent_entity(controller, result: EntitySearchResult) -> None:
    opener = getattr(controller, "open_recent_entity", None)
    if callable(opener):
        opener(result)
        return
    navigator = getattr(controller, "navigate_to_profile", None)
    if callable(navigator):
        navigator(result, source="recent-search", raw_query=result.entity_id)
        return
    direct = {
        "eoat": getattr(controller, "open_eoat", None),
        "tool": getattr(controller, "open_tool", None),
        "machine": getattr(controller, "open_machine", None),
    }.get(result.entity_type)
    if callable(direct):
        direct(result.entity_id)


def _resolve_query_to_recent_result(query: str, bundle) -> EntitySearchResult | None:
    if bundle is None:
        return None
    resolution = resolve_search_query(bundle, query)
    if not getattr(resolution, "found", False) or resolution.entity_type not in {"eoat", "tool", "machine"}:
        return None
    index = EntitySearchIndex.build(bundle)
    return index.get(resolution.entity_type, resolution.entity_id)


def _recent_dict_from_result(result: EntitySearchResult, *, query: str = "") -> dict[str, Any]:
    item = result.to_recent_dict()
    item["kind"] = entity_type_label(result.entity_type) if result.entity_type != "tool" else "Tool / Mold"
    item["query"] = str(query or result.entity_id).strip()
    return item


def _same_recent_ref(left_type: str, left_id: str, right_type: str, right_id: str) -> bool:
    left_kind = normalize_entity_type(left_type)
    right_kind = normalize_entity_type(right_type)
    if not left_kind or left_kind != right_kind:
        return False
    return normalize_entity_id(left_kind, left_id) == normalize_entity_id(right_kind, right_id)


def _recent_dedupe_key(item: Any, query: str) -> str:
    if isinstance(item, dict):
        entity_type = normalize_entity_type(str(item.get("type") or item.get("entity_type") or ""))
        entity_id = str(item.get("id") or item.get("entity_id") or "").strip()
        if entity_type and entity_id:
            return f"{entity_type}:{normalize_entity_id(entity_type, entity_id)}"
    return f"query:{str(query or '').casefold()}"


def infer_search_kind(query: str, bundle=None, *, fallback: str = "Search") -> str:
    text = str(query or "").strip()
    if not text:
        return fallback
    folded = text.casefold()
    compact = folded.replace("-", "").replace(" ", "")
    if (
        (compact.startswith("p4eoat") and any(character.isdigit() for character in compact[6:]))
        or (compact.startswith("cleoat") and any(character.isdigit() for character in compact[6:]))
    ):
        return "EOAT"
    if _letter_identifier(folded, "p"):
        return "Part"
    if _letter_identifier(folded, "m") or folded.startswith(("machine", "press")):
        return "Machine"
    if _letter_identifier(folded, "t") or folded.startswith(("tool", "mold")):
        return "Tool / Mold"
    interpreted_as, _value = interpret_query(text)
    if interpreted_as == "eoat":
        return "EOAT"
    if interpreted_as == "machine":
        return "Machine"
    if interpreted_as == "tool":
        return "Tool / Mold"
    if bundle is not None:
        folded = text.casefold()
        if any(folded == str(tool.tool).casefold() for tool in getattr(bundle, "tools", ())):
            return "Tool / Mold"
        if any(folded == str(machine.machine).casefold() for machine in getattr(bundle, "machines", ())):
            return "Machine"
        if any(folded == str(eoat.eoat_id).casefold() or folded == str(eoat.eoat_type).casefold() for eoat in getattr(bundle, "eoats", ())):
            return "EOAT"
        if any(folded in {str(part).casefold() for part in getattr(tool, "parts", ())} for tool in getattr(bundle, "tools", ())):
            return "Part"
        if any(folded in {str(part).casefold() for part in getattr(eoat, "parts", ())} for eoat in getattr(bundle, "eoats", ())):
            return "Part"
    return fallback


def _letter_identifier(folded: str, letter: str) -> bool:
    if not folded.startswith(letter):
        return False
    suffix = folded[1:].lstrip(" -#")
    return bool(suffix and suffix[0].isalnum())


def _is_blocked_recent_query(query: str) -> bool:
    folded = " ".join(str(query or "").strip().casefold().split())
    return folded in RECENT_SEARCH_BLOCKLIST


def dedupe_entries(entries: list[MinimalistSearchEntry], *, limit: int) -> list[MinimalistSearchEntry]:
    deduped: list[MinimalistSearchEntry] = []
    seen: set[str] = set()
    for entry in entries:
        key = entry.label.casefold()
        if not entry.label or key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
        if len(deduped) >= limit:
            break
    return deduped


def loaded_status_text(bundle) -> str:
    if bundle is None:
        return "Data loading..."
    loaded_at = str(getattr(bundle, "loaded_at", "") or "").strip()
    if not loaded_at:
        return "Data loaded"
    parsed = parse_loaded_at(loaded_at)
    if parsed is None:
        return f"Data refreshed {loaded_at}"
    delta = datetime.now() - parsed
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 60:
        return "Data updated just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"Data updated {minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"Data updated {hours} hr ago"
    return f"Data refreshed {parsed.strftime('%b %d, %Y')}"


def data_source_status_text(bundle) -> str:
    """Render the actual delivery source rather than a generic load timestamp."""

    if bundle is None:
        return "Server unavailable"
    metrics = getattr(bundle, "metrics", {}) or {}
    state = str(metrics.get("state") or metrics.get("data_source_status") or "Server unavailable")
    refreshed = str(metrics.get("last_successful_server_refresh") or "").strip()
    if refreshed:
        parsed = parse_loaded_at(refreshed)
        refresh_text = parsed.strftime("%Y-%m-%d %I:%M %p") if parsed else refreshed
    else:
        refresh_text = "not yet available"
    return f"{state} · Last successful server refresh: {refresh_text}"


def parse_loaded_at(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M %p"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def short_text(value: str, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def machine_label(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.casefold()
    if lowered.startswith("machine ") or lowered.startswith("m-"):
        return text
    return f"Machine {text}"


def with_front(values: tuple[str, ...], text: str, *, limit: int) -> tuple[str, ...]:
    folded = text.casefold()
    items = [text, *[item for item in values if item.casefold() != folded]]
    return tuple(items[:limit])


__all__ = [
    "MinimalistSearchEntry",
    "infer_search_kind",
    "is_recent_search_allowed",
    "loaded_status_text",
    "load_recent_searches",
    "page_label",
    "record_recent_entity_item",
    "record_recent_entity_result",
    "record_recent_search",
    "recent_entries",
    "recent_searches_path",
    "remove_recent_entity",
    "with_front",
]
