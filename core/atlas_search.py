from __future__ import annotations

import re
import time

from .atlas_models import AtlasDataBundle, SearchMatch
from .atlas_utils import normalized_eoat_key, normalized_lookup_key, normalized_machine_key, normalized_tool_key


def interpret_query(query: str) -> tuple[str, str]:
    text = query.strip()
    folded = text.casefold()
    if re.search(r"\bP4[-\s]?EOAT[-\s]?\d{1,4}\b", text, flags=re.IGNORECASE):
        return "eoat", _normalize_possible_eoat(text)
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
    matches: list[SearchMatch] = []
    matches.extend(_direct_matches(bundle, query_type, value))
    matches.extend(_eoat_matches(bundle, query))
    matches.extend(_machine_matches(bundle, query))
    matches.extend(_tool_matches(bundle, query))
    matches.extend(_standard_matches(bundle, query))
    deduped = _dedupe(matches)
    deduped.sort(key=lambda item: (-item.score, item.result_type, item.title.casefold()))
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return [
        SearchMatch(
            result_type=item.result_type,
            key=item.key,
            title=item.title,
            subtitle=item.subtitle,
            score=item.score,
            matched_fields=item.matched_fields,
            metadata={**item.metadata, "search_time_ms": elapsed_ms},
        )
        for item in deduped[:limit]
    ]


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
    for record in bundle.eoats:
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
    for tool in bundle.tools:
        score, fields = _score_query(
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
        if score:
            matches.append(
                _match(
                    "tool",
                    tool.tool,
                    f"Tool {tool.tool}",
                    f"{len(tool.compatible_eoats)} EOAT(s) | Machines: {', '.join(tool.compatible_machines[:4])}",
                    score + 70,
                    tuple(fields),
                )
            )
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
    match = re.search(r"P4[-\s]?EOAT[-\s]?(\d{1,4})", text, flags=re.IGNORECASE)
    if not match:
        return text
    return f"P4-EOAT-{int(match.group(1)):04d}"


__all__ = ["interpret_query", "search_atlas"]
