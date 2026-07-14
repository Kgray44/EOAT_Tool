from __future__ import annotations

from dataclasses import dataclass, field
import re
import time
from typing import Any

from .atlas_models import AtlasDataBundle, SearchMatch
from .atlas_utils import display_value, normalized_eoat_key, normalized_lookup_key, normalized_machine_key, normalized_tool_key
from .eoat_ids import format_eoat_id


ENTITY_RESULT_TYPES = {"eoat", "tool", "machine"}


@dataclass(frozen=True)
class SearchResolution:
    raw_query: str = ""
    normalized_query: str = ""
    found: bool = False
    entity_type: str = "unknown"
    entity_id: str = ""
    display_label: str = ""
    route_target: dict[str, str] = field(default_factory=dict)
    confidence: str = "partial"
    matches: tuple[SearchMatch, ...] = ()
    recommendation: Any = None


def normalize_search_term(value: Any) -> str:
    text = " ".join(display_value(value).strip().casefold().split())
    if not text:
        return ""
    text = re.sub(r"^(?:open\s+)?(?:tool|mold|part|machine|press|eoat)\s*(?:number|no\.?|#)?\s*[:#-]*\s*", "", text)
    compact_machine = re.fullmatch(r"(?:machine|press|m|p)\s*[-#]?\s*([1-9]\d*)", text)
    if compact_machine:
        return compact_machine.group(1)
    return text


def resolve_search_query(bundle: AtlasDataBundle | None, query: str, *, limit: int = 8) -> SearchResolution:
    raw_query = display_value(query).strip()
    normalized_query = normalize_search_term(raw_query)
    if bundle is None or not raw_query:
        return SearchResolution(raw_query=raw_query, normalized_query=normalized_query)

    for candidates in (
        _exact_eoat_resolution_matches(bundle, raw_query),
        _exact_tool_resolution_matches(bundle, raw_query),
        _exact_machine_resolution_matches(bundle, raw_query),
        _normalized_eoat_resolution_matches(bundle, raw_query),
        _normalized_tool_resolution_matches(bundle, raw_query),
        _normalized_machine_resolution_matches(bundle, raw_query),
    ):
        resolution = _resolution_from_candidates(raw_query, normalized_query, candidates)
        if resolution is not None:
            return resolution

    partial_matches = tuple(
        _match_with_route(match, confidence="partial")
        for match in search_atlas(bundle, raw_query, limit=limit)
        if match.result_type in ENTITY_RESULT_TYPES
    )
    if len(partial_matches) == 1 and partial_matches[0].score >= 430:
        match = partial_matches[0]
        return SearchResolution(
            raw_query=raw_query,
            normalized_query=normalized_query,
            found=True,
            entity_type=match.result_type,
            entity_id=match.key,
            display_label=match.title,
            route_target=_route_target(match.result_type, match.key),
            confidence="partial",
            matches=partial_matches,
        )
    if len(partial_matches) > 1:
        return SearchResolution(
            raw_query=raw_query,
            normalized_query=normalized_query,
            found=True,
            entity_type="ambiguous",
            display_label=f"{len(partial_matches)} matching records",
            confidence="partial",
            matches=partial_matches,
        )
    return SearchResolution(raw_query=raw_query, normalized_query=normalized_query, matches=partial_matches)


def interpret_query(query: str) -> tuple[str, str]:
    text = query.strip()
    folded = text.casefold()
    if re.search(r"\b(?:P4|CL)[-\s]?EOAT[-\s]?\d{1,4}\b", text, flags=re.IGNORECASE):
        return "eoat", _normalize_possible_eoat(text)
    if folded.startswith("eoat"):
        value = re.sub(r"^eoat\s*[-#:]*\s*", "", text, flags=re.IGNORECASE).strip()
        return "eoat", _normalize_possible_eoat(value)
    if folded.startswith(("tool", "mold")):
        return "tool", re.sub(r"^(tool|mold)\s*[-#:]*\s*", "", text, flags=re.IGNORECASE).strip()
    if folded.startswith(("machine", "press")) or re.fullmatch(r"[mp]\s*[-#]?\s*\d+", text, flags=re.IGNORECASE):
        return "machine", re.sub(r"^(machine|press|m|p)\s*[-#:]*\s*", "", text, flags=re.IGNORECASE).strip()
    if re.fullmatch(r"\d+", text):
        return "number", text
    return "keyword", text


def search_atlas(bundle: AtlasDataBundle, query: str = "", *, limit: int = 50) -> list[SearchMatch]:
    started = time.perf_counter()
    query = query.strip()
    query_type, value = interpret_query(query)
    exact_machine_query = _exact_machine_query_value(query_type, value, query)
    if exact_machine_query and _machine_exists(bundle, exact_machine_query):
        matches = _exact_machine_matches(bundle, exact_machine_query)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return [_with_timing(match, elapsed_ms) for match in matches[:limit]]
    matches: list[SearchMatch] = []
    matches.extend(_direct_matches(bundle, query_type, value))
    matches.extend(_eoat_matches(bundle, query))
    matches.extend(_machine_matches(bundle, query))
    matches.extend(_tool_matches(bundle, query))
    matches.extend(_standard_matches(bundle, query))
    deduped = _dedupe(matches)
    deduped.sort(key=lambda item: (-item.score, item.result_type, item.title.casefold()))
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return [_with_timing(item, elapsed_ms) for item in deduped[:limit]]


def _direct_matches(bundle: AtlasDataBundle, query_type: str, value: str) -> list[SearchMatch]:
    matches: list[SearchMatch] = []
    if not value:
        return matches
    if query_type == "eoat":
        key = normalized_eoat_key(value)
        canonical = bundle.indexes.eoat_by_id.get(key)
        if canonical:
            matches.append(_match("eoat", canonical, canonical, "Exact EOAT ID match", 500, ("EOAT ID",)))
    if query_type in {"tool", "number"}:
        tool_key = normalized_tool_key(value)
        for eoat_id in bundle.indexes.eoats_by_tool.get(tool_key, ()):
            matches.append(_match("eoat", eoat_id, eoat_id, f"Linked to Tool {value}", 420, ("Tool #",)))
        for tool in bundle.tools:
            if normalized_tool_key(tool.tool) == tool_key:
                matches.append(
                    _match("tool", tool.tool, f"Tool {tool.tool}", ", ".join(tool.compatible_eoats), 410, ("Tool #",))
                )
    if query_type in {"machine", "number"}:
        machine_key = normalized_machine_key(value)
        for machine in bundle.machines:
            if normalized_machine_key(machine.machine) == machine_key:
                matches.append(
                    _match(
                        "machine",
                        machine.machine,
                        f"Machine {machine.machine}",
                        f"{len(machine.compatible_eoats)} compatible EOAT(s)",
                        400,
                        ("Machine #",),
                    )
                )
        for eoat_id in bundle.indexes.eoats_by_machine.get(machine_key, ()):
            matches.append(_match("eoat", eoat_id, eoat_id, f"Compatible with Machine {value}", 390, ("Machine #",)))
    return matches


def _eoat_matches(bundle: AtlasDataBundle, query: str) -> list[SearchMatch]:
    matches: list[SearchMatch] = []
    query_text = query.strip()
    query_norm = normalized_lookup_key(query_text)
    suffix_query = _numeric_suffix(query_text)
    for record in bundle.eoats:
        suffix = _eoat_suffix(record.eoat_id)
        if query_norm and query_norm == normalized_eoat_key(record.eoat_id):
            matches.append(
                _match(
                    "eoat",
                    record.eoat_id,
                    record.eoat_id,
                    f"{record.eoat_type or 'EOAT'} | Exact EOAT ID",
                    500,
                    ("EOAT ID",),
                    {"documentation_score": record.documentation.score, "photo_count": record.photo_count},
                )
            )
            continue
        if suffix_query and suffix and int(suffix_query) == int(suffix):
            score = 470 if len(suffix_query) == len(suffix) else 455
            matches.append(
                _match(
                    "eoat",
                    record.eoat_id,
                    record.eoat_id,
                    f"{record.eoat_type or 'EOAT'} | EOAT suffix {suffix}",
                    score,
                    ("EOAT suffix",),
                    {"documentation_score": record.documentation.score, "photo_count": record.photo_count},
                )
            )
            continue
        score, fields = _score_query(
            query,
            {
                "EOAT ID": record.eoat_id,
                "Audit IDs": " ".join(record.audit_ids),
                "Tools": " ".join(record.tools),
                "Machines": " ".join(record.machines),
                "Parts": " ".join(record.parts),
                "Part Description": record.part_description,
                "EOAT Type": record.eoat_type,
                "Known Issues": record.known_issues,
            },
        )
        if score:
            matches.append(
                _match(
                    "eoat",
                    record.eoat_id,
                    record.eoat_id,
                    f"{record.eoat_type or 'EOAT'} | Tools: {', '.join(record.tools[:3])}",
                    score + 80,
                    tuple(fields),
                    {"documentation_score": record.documentation.score, "photo_count": record.photo_count},
                )
            )
    return matches


def _machine_matches(bundle: AtlasDataBundle, query: str) -> list[SearchMatch]:
    matches: list[SearchMatch] = []
    query_type, value = interpret_query(query)
    exact_value = _exact_machine_query_value(query_type, value, query)
    if exact_value:
        return _exact_machine_matches(bundle, exact_value)
    for machine in bundle.machines:
        score, fields = _score_query(
            query,
            {
                "Machine #": machine.machine,
                "Robot Type": machine.robot_type,
                "Robot Model": machine.robot_model,
                "Tools": " ".join(machine.compatible_tools),
                "EOATs": " ".join(machine.compatible_eoats),
            },
        )
        if score:
            matches.append(
                _match(
                    "machine",
                    machine.machine,
                    f"Machine {machine.machine}",
                    f"{len(machine.compatible_eoats)} EOAT(s) | Robot: {machine.robot_type or 'unknown'}",
                    score + 60,
                    tuple(fields),
                )
            )
    return matches


def _tool_matches(bundle: AtlasDataBundle, query: str) -> list[SearchMatch]:
    matches: list[SearchMatch] = []
    query_text = _strip_tool_prefix(query)
    query_norm = normalized_tool_key(query_text)
    if not query_norm:
        return []
    exact_or_prefix: list[SearchMatch] = []
    fallback: list[SearchMatch] = []
    numeric_short = query_text.isdigit() and len(query_text) <= 3
    for tool in bundle.tools:
        identifiers = [tool.tool, *tool.molds, *tool.parts]
        normalized_identifiers = [normalized_tool_key(value) for value in identifiers if normalized_tool_key(value)]
        score = 0.0
        fields: tuple[str, ...] = ()
        if any(query_norm == value for value in normalized_identifiers):
            score = 480
            fields = ("Tool / Mold / Part #",)
        elif any(value.startswith(query_norm) for value in normalized_identifiers):
            score = 430
            fields = ("Tool / Mold / Part prefix",)
        else:
            text_score, text_fields = _score_query(
                query,
                {
                    "Tool #": tool.tool,
                    "Molds": " ".join(tool.molds),
                    "Parts": " ".join(tool.parts),
                    "Part Description": tool.part_description,
                    "EOATs": " ".join(tool.compatible_eoats),
                    "Machines": " ".join(tool.compatible_machines),
                },
            )
            if text_score and not numeric_short:
                score = text_score + 70
                fields = tuple(text_fields)
            elif text_score:
                fallback.append(
                    _match(
                        "tool",
                        tool.tool,
                        f"Tool {tool.tool}",
                        f"{len(tool.compatible_eoats)} EOAT(s) | Machines: {', '.join(tool.compatible_machines[:4])}",
                        text_score + 30,
                        tuple(text_fields),
                    )
                )
                continue
        if score:
            match = _match(
                "tool",
                tool.tool,
                f"Tool {tool.tool}",
                f"{len(tool.compatible_eoats)} EOAT(s) | Machines: {', '.join(tool.compatible_machines[:4])}",
                score,
                fields,
            )
            if score >= 430:
                exact_or_prefix.append(match)
            else:
                matches.append(match)
    if exact_or_prefix:
        return [*exact_or_prefix, *matches]
    if fallback:
        return fallback
    return matches


def _standard_matches(bundle: AtlasDataBundle, query: str) -> list[SearchMatch]:
    if not query.strip():
        return []
    matches: list[SearchMatch] = []
    for reference in bundle.standards:
        score, fields = _score_query(
            query,
            {"Standard": reference.title, "Category": reference.category, "Snippet": reference.snippet},
        )
        if score:
            matches.append(
                _match("standard", reference.path, reference.title, reference.category, score + 20, tuple(fields))
            )
    return matches


def _score_query(query: str, fields: dict[str, str]) -> tuple[float, list[str]]:
    if not query.strip():
        return 1.0, ["all"]
    query_norm = normalized_lookup_key(query)
    terms = [normalized_lookup_key(term) for term in query.split() if normalized_lookup_key(term)]
    score = 0.0
    matched_fields: list[str] = []
    for field_name, value in fields.items():
        value_norm = normalized_lookup_key(value)
        if not value_norm:
            continue
        if query_norm and query_norm == value_norm:
            score += 100
            matched_fields.append(field_name)
        elif query_norm and query_norm in value_norm:
            score += 35
            matched_fields.append(field_name)
        else:
            hits = sum(term in value_norm for term in terms)
            if hits:
                score += hits * 12
                matched_fields.append(field_name)
    return score, matched_fields


def _match(
    result_type: str,
    key: str,
    title: str,
    subtitle: str,
    score: float,
    fields: tuple[str, ...],
    metadata: dict | None = None,
) -> SearchMatch:
    return SearchMatch(
        result_type=result_type,
        key=key,
        title=title,
        subtitle=subtitle,
        score=float(score),
        matched_fields=fields,
        metadata=dict(metadata or {}),
    )


def _dedupe(matches: list[SearchMatch]) -> list[SearchMatch]:
    by_key: dict[tuple[str, str], SearchMatch] = {}
    for match in matches:
        key = (match.result_type, match.key.casefold())
        existing = by_key.get(key)
        if existing is None or match.score > existing.score:
            by_key[key] = match
    return list(by_key.values())


def _normalize_possible_eoat(text: str) -> str:
    match = re.search(r"(P4|CL)[-\s]?EOAT[-\s]?(\d{1,4})", text, flags=re.IGNORECASE)
    if not match:
        return text
    return format_eoat_id(match.group(1), int(match.group(2)))


def _exact_machine_query_value(query_type: str, value: str, query: str) -> str:
    text = query.strip()
    if query_type == "machine" and re.fullmatch(r"\d+", value.strip()):
        return value.strip()
    if query_type == "number" and re.fullmatch(r"[1-9]\d*", text):
        return text
    return ""


def _machine_exists(bundle: AtlasDataBundle, value: str) -> bool:
    key = normalized_machine_key(value)
    return any(normalized_machine_key(machine.machine) == key for machine in bundle.machines)


def _exact_machine_matches(bundle: AtlasDataBundle, value: str) -> list[SearchMatch]:
    key = normalized_machine_key(value)
    matches: list[SearchMatch] = []
    for machine in bundle.machines:
        if normalized_machine_key(machine.machine) == key:
            matches.append(
                _match(
                    "machine",
                    machine.machine,
                    f"Machine {machine.machine}",
                    f"{len(machine.compatible_eoats)} compatible EOAT(s)",
                    500,
                    ("Machine #",),
                )
            )
    return matches


def _strip_tool_prefix(query: str) -> str:
    return re.sub(r"^(tool|mold|part)\s*[-#:]*\s*", "", query.strip(), flags=re.IGNORECASE).strip()


def _eoat_suffix(value: str) -> str:
    match = re.search(r"(\d{1,4})$", normalized_eoat_key(value))
    return f"{int(match.group(1)):04d}" if match else ""


def _numeric_suffix(value: str) -> str:
    text = re.sub(r"^eoat\s*[-#:]*\s*", "", value.strip(), flags=re.IGNORECASE).strip()
    return f"{int(text):04d}" if re.fullmatch(r"\d{1,4}", text) else ""


def _with_timing(match: SearchMatch, elapsed_ms: float) -> SearchMatch:
    return SearchMatch(
        result_type=match.result_type,
        key=match.key,
        title=match.title,
        subtitle=match.subtitle,
        score=match.score,
        matched_fields=match.matched_fields,
        metadata={**match.metadata, "search_time_ms": elapsed_ms},
    )


def _resolution_from_candidates(raw_query: str, normalized_query: str, candidates: list[SearchMatch]) -> SearchResolution | None:
    deduped = tuple(_dedupe(candidates))
    if not deduped:
        return None
    deduped = tuple(sorted(deduped, key=lambda match: (-match.score, match.result_type, match.title.casefold())))
    if len(deduped) > 1:
        return SearchResolution(
            raw_query=raw_query,
            normalized_query=normalized_query,
            found=True,
            entity_type="ambiguous",
            display_label=f"{len(deduped)} matching records",
            confidence=str(deduped[0].metadata.get("confidence") or "exact"),
            matches=deduped,
        )
    match = deduped[0]
    route_target = _route_target(match.result_type, match.key)
    return SearchResolution(
        raw_query=raw_query,
        normalized_query=normalized_query,
        found=True,
        entity_type=match.result_type,
        entity_id=match.key,
        display_label=match.title,
        route_target=route_target,
        confidence=str(match.metadata.get("confidence") or "exact"),
        matches=deduped,
    )


def _exact_eoat_resolution_matches(bundle: AtlasDataBundle, query: str) -> list[SearchMatch]:
    values = _eoat_query_values(query)
    exact_values = {value.casefold() for value in values if value}
    matches: list[SearchMatch] = []
    for record in bundle.eoats:
        if record.eoat_id.casefold() in exact_values:
            matches.append(
                _resolution_match(
                    "eoat",
                    record.eoat_id,
                    record.eoat_id,
                    f"{record.eoat_type or 'EOAT'} | Exact EOAT ID",
                    900,
                    ("EOAT ID",),
                    confidence="exact",
                )
            )
    return matches


def _normalized_eoat_resolution_matches(bundle: AtlasDataBundle, query: str) -> list[SearchMatch]:
    query_keys = {normalized_eoat_key(value) for value in _eoat_query_values(query) if normalized_eoat_key(value)}
    matches: list[SearchMatch] = []
    for record in bundle.eoats:
        key = normalized_eoat_key(record.eoat_id)
        if key in query_keys:
            matches.append(
                _resolution_match(
                    "eoat",
                    record.eoat_id,
                    record.eoat_id,
                    f"{record.eoat_type or 'EOAT'} | Normalized EOAT ID",
                    800,
                    ("EOAT ID",),
                    confidence="normalized",
                )
            )
    return matches


def _exact_tool_resolution_matches(bundle: AtlasDataBundle, query: str) -> list[SearchMatch]:
    values = _tool_query_values(query)
    exact_values = {value.casefold() for value in values if value}
    matches: list[SearchMatch] = []
    for tool in bundle.tools:
        for field_name, identifier in _tool_identifiers(tool):
            if identifier.casefold() in exact_values:
                matches.append(
                    _resolution_match(
                        "tool",
                        tool.tool,
                        f"Tool {tool.tool}",
                        f"Matched {field_name} {identifier}",
                        890,
                        (field_name,),
                        confidence="exact",
                    )
                )
                break
    return matches


def _normalized_tool_resolution_matches(bundle: AtlasDataBundle, query: str) -> list[SearchMatch]:
    query_keys = {normalized_tool_key(value) for value in _tool_query_values(query) if normalized_tool_key(value)}
    matches: list[SearchMatch] = []
    for tool in bundle.tools:
        for field_name, identifier in _tool_identifiers(tool):
            if normalized_tool_key(identifier) in query_keys:
                matches.append(
                    _resolution_match(
                        "tool",
                        tool.tool,
                        f"Tool {tool.tool}",
                        f"Matched {field_name} {identifier}",
                        790,
                        (field_name,),
                        confidence="normalized",
                    )
                )
                break
    return matches


def _exact_machine_resolution_matches(bundle: AtlasDataBundle, query: str) -> list[SearchMatch]:
    values = _machine_query_values(query)
    exact_values = {value.casefold() for value in values if value}
    matches: list[SearchMatch] = []
    for machine in bundle.machines:
        if machine.machine.casefold() in exact_values:
            matches.append(
                _resolution_match(
                    "machine",
                    machine.machine,
                    f"Machine {machine.machine}",
                    machine.robot_type or machine.robot_model or "Machine profile",
                    880,
                    ("Machine #",),
                    confidence="exact",
                )
            )
    return matches


def _normalized_machine_resolution_matches(bundle: AtlasDataBundle, query: str) -> list[SearchMatch]:
    query_keys = {normalized_machine_key(value) for value in _machine_query_values(query) if normalized_machine_key(value)}
    matches: list[SearchMatch] = []
    for machine in bundle.machines:
        if normalized_machine_key(machine.machine) in query_keys:
            matches.append(
                _resolution_match(
                    "machine",
                    machine.machine,
                    f"Machine {machine.machine}",
                    machine.robot_type or machine.robot_model or "Machine profile",
                    780,
                    ("Machine #",),
                    confidence="normalized",
                )
            )
    return matches


def _resolution_match(
    result_type: str,
    key: str,
    title: str,
    subtitle: str,
    score: float,
    fields: tuple[str, ...],
    *,
    confidence: str,
) -> SearchMatch:
    return SearchMatch(
        result_type=result_type,
        key=key,
        title=title,
        subtitle=subtitle,
        score=score,
        matched_fields=fields,
        metadata={"confidence": confidence, "route_target": _route_target(result_type, key)},
    )


def _match_with_route(match: SearchMatch, *, confidence: str) -> SearchMatch:
    return SearchMatch(
        result_type=match.result_type,
        key=match.key,
        title=match.title,
        subtitle=match.subtitle,
        score=match.score,
        matched_fields=match.matched_fields,
        metadata={**match.metadata, "confidence": confidence, "route_target": _route_target(match.result_type, match.key)},
    )


def _route_target(entity_type: str, entity_id: str) -> dict[str, str]:
    return {"page": "library", "entity_type": str(entity_type or ""), "entity_id": str(entity_id or "")}


def _eoat_query_values(query: str) -> tuple[str, ...]:
    text = display_value(query).strip()
    stripped = re.sub(r"^(?:open\s+)?eoat\s*(?:number|no\.?|#)?\s*[:#-]*\s*", "", text, flags=re.IGNORECASE).strip()
    return _unique_texts((text, stripped))


def _tool_query_values(query: str) -> tuple[str, ...]:
    text = display_value(query).strip()
    stripped = re.sub(r"^(?:open\s+)?(?:tool|mold|part)\s*(?:number|no\.?|#)?\s*[:#-]*\s*", "", text, flags=re.IGNORECASE).strip()
    return _unique_texts((text, stripped))


def _machine_query_values(query: str) -> tuple[str, ...]:
    text = display_value(query).strip()
    stripped = re.sub(r"^(?:open\s+)?(?:machine|press)\s*(?:number|no\.?|#)?\s*[:#-]*\s*", "", text, flags=re.IGNORECASE).strip()
    prefixed = re.fullmatch(r"(?:m|p)\s*[-#]?\s*([1-9]\d*)", text, flags=re.IGNORECASE)
    if prefixed:
        return _unique_texts((text, stripped, prefixed.group(1)))
    return _unique_texts((text, stripped))


def _tool_identifiers(tool) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    if display_value(getattr(tool, "tool", "")):
        rows.append(("Tool #", display_value(tool.tool)))
    rows.extend(("Mold #", display_value(value)) for value in getattr(tool, "molds", ()) if display_value(value))
    rows.extend(("Part #", display_value(value)) for value in getattr(tool, "parts", ()) if display_value(value))
    return tuple(rows)


def _unique_texts(values: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = display_value(value).strip()
        folded = text.casefold()
        if text and folded not in seen:
            seen.add(folded)
            result.append(text)
    return tuple(result)


__all__ = ["SearchResolution", "interpret_query", "normalize_search_term", "resolve_search_query", "search_atlas"]
