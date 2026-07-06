from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from core.atlas_search import interpret_query
from core.resources import writable_config_path


@dataclass(frozen=True)
class MinimalistSearchEntry:
    label: str
    query: str
    kind: str
    opener: Callable[[], None] | None = None
    placeholder: bool = False


PAGE_LABELS = {
    "home": "Home",
    "minimalist_home": "Home",
    "what": "What Do I Need?",
    "setup_packet": "Changeover Builder",
    "library": "Library",
    "eoats": "EOAT Profiles",
    "machines": "Machine Profiles",
    "matrix": "Compatibility",
    "photos": "Photos",
    "standards": "Standards & WI",
    "reports": "Reports",
    "diagnostics": "Settings & Diagnostics",
}


def page_label(key: str) -> str:
    return PAGE_LABELS.get(str(key or ""), str(key or "Page"))


def recent_entries(controller, bundle, *, limit: int = 5) -> list[MinimalistSearchEntry]:
    entries = []
    for item in load_recent_searches(limit=limit):
        query = item["query"]
        kind = item.get("kind") or infer_search_kind(query, bundle)
        entries.append(
            MinimalistSearchEntry(
                label=query,
                query=query,
                kind=kind,
                opener=lambda query=query, kind=kind: controller.open_recommendation(query, kind=kind, record_search=False),
            )
        )
    return entries


def recent_searches_path():
    return writable_config_path("atlas_minimalist_recent_searches.json")


def load_recent_searches(*, limit: int = 8) -> list[dict[str, str]]:
    try:
        raw = json.loads(recent_searches_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get("items", raw) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    searches: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            query = item.strip()
            kind = ""
        elif isinstance(item, dict):
            query = str(item.get("query", "") or "").strip()
            kind = str(item.get("kind", "") or "").strip()
        else:
            continue
        folded = query.casefold()
        if not query or folded in seen:
            continue
        seen.add(folded)
        searches.append({"query": query, "kind": kind})
        if len(searches) >= limit:
            break
    return searches


def save_recent_searches(searches: list[dict[str, str]]) -> None:
    path = recent_searches_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items": searches[:10]}, indent=2), encoding="utf-8")


def record_recent_search(query: str, *, kind: str = "", bundle=None, limit: int = 10) -> list[dict[str, str]]:
    text = str(query or "").strip()
    if not text:
        return load_recent_searches(limit=limit)
    resolved_kind = kind.strip() or infer_search_kind(text, bundle)
    folded = text.casefold()
    existing = [item for item in load_recent_searches(limit=limit) if item["query"].casefold() != folded]
    searches = [{"query": text, "kind": resolved_kind}, *existing]
    save_recent_searches(searches[:limit])
    return searches[:limit]


def infer_search_kind(query: str, bundle=None, *, fallback: str = "Search") -> str:
    text = str(query or "").strip()
    if not text:
        return fallback
    folded = text.casefold()
    compact = folded.replace("-", "").replace(" ", "")
    if compact.startswith("p4eoat") and any(character.isdigit() for character in compact[6:]):
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
    "loaded_status_text",
    "load_recent_searches",
    "page_label",
    "record_recent_search",
    "recent_entries",
    "recent_searches_path",
    "with_front",
]
