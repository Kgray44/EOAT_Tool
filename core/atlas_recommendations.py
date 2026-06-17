from __future__ import annotations

import time

from .atlas_models import (
    AtlasDataBundle,
    PhotoItem,
    RecommendationCandidate,
    RecommendationResult,
    SearchMatch,
    WarningItem,
)
from .atlas_search import interpret_query, search_atlas
from .atlas_utils import normalized_eoat_key, normalized_machine_key, normalized_tool_key


def recommend_for_query(bundle: AtlasDataBundle, query: str) -> RecommendationResult:
    started = time.perf_counter()
    interpreted_as, value = interpret_query(query)
    matches = tuple(search_atlas(bundle, query, limit=25))
    candidate_ids = _candidate_ids_for_query(bundle, interpreted_as, value, matches)
    candidates = tuple(_rank_candidates(bundle, candidate_ids, interpreted_as, value))
    best = candidates[0] if candidates else None
    photos = tuple(_photos_for_best(bundle, best))
    warnings = tuple(_warnings_for_result(bundle, candidates, matches))
    summary = _summary(query, interpreted_as, best, candidates)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    if matches:
        matches = tuple(
            SearchMatch(
                result_type=match.result_type,
                key=match.key,
                title=match.title,
                subtitle=match.subtitle,
                score=match.score,
                matched_fields=match.matched_fields,
                metadata={**match.metadata, "recommendation_time_ms": elapsed_ms},
            )
            for match in matches
        )
    return RecommendationResult(
        query=query,
        interpreted_as=interpreted_as,
        summary=summary,
        best=best,
        candidates=candidates,
        matches=matches,
        compatible_machines=tuple(_compatible_machines_for_candidates(bundle, candidates)),
        install_checklist=_install_checklist(bundle, best),
        warnings=warnings,
        photos=photos,
        standards=tuple(_standards_for_best(bundle, best)),
    )


def _candidate_ids_for_query(
    bundle: AtlasDataBundle, interpreted_as: str, value: str, matches: tuple[SearchMatch, ...]
) -> list[str]:
    ids: list[str] = []
    if interpreted_as == "eoat":
        canonical = bundle.indexes.eoat_by_id.get(normalized_eoat_key(value))
        if canonical:
            ids.append(canonical)
    if interpreted_as in {"tool", "number"}:
        ids.extend(bundle.indexes.eoats_by_tool.get(normalized_tool_key(value), ()))
    if interpreted_as in {"machine", "number"}:
        ids.extend(bundle.indexes.eoats_by_machine.get(normalized_machine_key(value), ()))
    if ids and interpreted_as in {"eoat", "tool", "machine"}:
        return list(dict.fromkeys(ids))
    for match in matches:
        if match.result_type == "eoat":
            ids.append(match.key)
        elif match.result_type == "tool":
            ids.extend(bundle.indexes.eoats_by_tool.get(normalized_tool_key(match.key), ()))
        elif match.result_type == "machine":
            ids.extend(bundle.indexes.eoats_by_machine.get(normalized_machine_key(match.key), ()))
    return list(dict.fromkeys(ids))


def _rank_candidates(bundle: AtlasDataBundle, candidate_ids: list[str], interpreted_as: str, value: str):
    records = []
    for eoat_id in candidate_ids:
        record = _eoat(bundle, eoat_id)
        if record is None:
            continue
        score = 0
        reasons: list[str] = []
        if normalized_eoat_key(record.eoat_id) == normalized_eoat_key(value):
            score += 100
            reasons.append("Exact EOAT ID match.")
        if interpreted_as in {"tool", "number"} and any(normalized_tool_key(tool) == normalized_tool_key(value) for tool in record.tools):
            score += 90
            reasons.append("Exact tool/mold/part compatibility match.")
        if interpreted_as in {"machine", "number"} and any(
            normalized_machine_key(machine) == normalized_machine_key(value) for machine in record.machines
        ):
            score += 70
            reasons.append("Compatible with the requested machine.")
        if record.status:
            score += _status_score(record.status)
            reasons.append(f"Status: {record.status}.")
        if record.documentation.score:
            doc_points = min(30, record.documentation.score // 4)
            score += doc_points
            reasons.append(f"Documentation score: {record.documentation.score}%.")
        if record.photo_count:
            photo_points = min(15, record.photo_count * 3)
            score += photo_points
            reasons.append(f"{record.photo_count} linked photo(s).")
        if record.connection_type:
            score += 5
            reasons.append(f"Connection: {record.connection_type}.")
        warning_penalty = min(35, len(record.warnings) * 5)
        if warning_penalty:
            score -= warning_penalty
            reasons.append(f"{len(record.warnings)} warning(s) need review.")
        records.append((score, record, tuple(reasons)))
    records.sort(key=lambda item: (-item[0], item[1].eoat_id.casefold()))
    candidates: list[RecommendationCandidate] = []
    for rank, (score, record, reasons) in enumerate(records, start=1):
        candidates.append(
            RecommendationCandidate(
                eoat_id=record.eoat_id,
                rank=rank,
                score=score,
                summary=_candidate_summary(record),
                machines=record.machines,
                tools=record.tools,
                reasons=reasons,
                warnings=record.warnings,
                documentation_score=record.documentation.score,
                photo_count=record.photo_count,
            )
        )
    return candidates


def _summary(query: str, interpreted_as: str, best: RecommendationCandidate | None, candidates) -> str:
    if best is None:
        return f"No EOAT recommendation could be made for '{query}'. Try a tool, mold, part, machine, or EOAT ID."
    if len(candidates) == 1:
        return f"For {interpreted_as} '{query}', use {best.eoat_id}."
    return f"For {interpreted_as} '{query}', best match is {best.eoat_id}; {len(candidates) - 1} backup option(s) found."


def _candidate_summary(record) -> str:
    pieces = [
        record.eoat_type or "EOAT",
        f"Tools: {', '.join(record.tools[:3])}" if record.tools else "",
        f"Machines: {', '.join(record.machines[:5])}" if record.machines else "",
        f"Docs {record.documentation.score}%",
        f"Photos {record.photo_count}",
    ]
    return " | ".join(piece for piece in pieces if piece)


def _install_checklist(bundle: AtlasDataBundle, best: RecommendationCandidate | None) -> tuple[str, ...]:
    if best is None:
        return (
            "Confirm the tool, mold, part, or machine number.",
            "Check whether the EOAT is missing from the master tracker.",
            "Use EOAT Command Center to repair missing compatibility data if needed.",
        )
    record = _eoat(bundle, best.eoat_id)
    if record is None:
        return ()
    checklist = [
        "Verify the EOAT ID on the assembly matches the recommendation.",
        "Confirm the EOAT is compatible with the selected machine and tool.",
        "Inspect mounting hardware and locking fasteners before install.",
    ]
    eoat_type = record.eoat_type.casefold()
    if "vacuum" in eoat_type or record.vacuum_info:
        checklist.extend(
            [
                "Inspect vacuum cups for wear, cuts, and missing cups.",
                "Confirm vacuum tubing is routed cleanly and not kinked near wrist rotation.",
                "Verify vacuum confirmation or part-present detection if applicable.",
            ]
        )
    if "gripper" in eoat_type or record.gripper_info:
        checklist.extend(
            [
                "Check gripper fingers/jaws for looseness, wear, or damage.",
                "Cycle grippers manually or in setup mode before production release.",
            ]
        )
    if record.connection_type:
        checklist.append(f"Confirm connection type is seated: {record.connection_type}.")
    checklist.append("Review warnings and missing documentation before running production.")
    return tuple(dict.fromkeys(checklist))


def _warnings_for_result(bundle: AtlasDataBundle, candidates, matches) -> list[WarningItem]:
    warnings: list[WarningItem] = []
    if not candidates:
        warnings.append(
            WarningItem(
                severity="warning",
                title="No recommendation",
                message="Atlas could not find a confident EOAT match from the loaded data.",
                source="Atlas Recommendations",
                suggested_fix="Search by a more specific Tool #, Machine #, EOAT ID, or part description.",
            )
        )
    elif candidates[0].warnings:
        warnings.extend(candidates[0].warnings)
    if len([match for match in matches if match.result_type in {"eoat", "tool", "machine"}]) > 5:
        warnings.append(
            WarningItem(
                severity="info",
                title="Ambiguous input",
                message="The input matched several records. Atlas ranked the candidates, but the top result should be reviewed.",
                source="Atlas Search",
            )
        )
    return warnings


def _photos_for_best(bundle: AtlasDataBundle, best: RecommendationCandidate | None) -> list[PhotoItem]:
    if best is None:
        return []
    record = _eoat(bundle, best.eoat_id)
    if record is None:
        return []
    return list((*record.photos.photos, *record.photos.indexed_photos))[:12]


def _standards_for_best(bundle: AtlasDataBundle, best: RecommendationCandidate | None):
    if best is None:
        return []
    record = _eoat(bundle, best.eoat_id)
    return list(record.standards) if record is not None else []


def _compatible_machines_for_candidates(bundle: AtlasDataBundle, candidates) -> list[str]:
    machines: list[str] = []
    for candidate in candidates:
        machines.extend(candidate.machines)
    return sorted(set(machines), key=lambda value: (0, int(value)) if value.isdigit() else (1, value.casefold()))


def _eoat(bundle: AtlasDataBundle, eoat_id: str):
    key = normalized_eoat_key(eoat_id)
    canonical = bundle.indexes.eoat_by_id.get(key, eoat_id)
    return next((record for record in bundle.eoats if normalized_eoat_key(record.eoat_id) == normalized_eoat_key(canonical)), None)


def _status_score(status: str) -> int:
    folded = status.casefold()
    if any(token in folded for token in ("inactive", "deleted", "retired", "missing")):
        return -30
    if any(token in folded for token in ("installed", "audited", "candidate", "active")):
        return 20
    if "off" in folded:
        return 5
    return 10


__all__ = ["recommend_for_query"]
