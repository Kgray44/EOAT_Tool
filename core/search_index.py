from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .audit_compatibility import machine_from_audit_row, text_value
from .open_items import list_open_items
from .paths import resolve_project_paths
from .reports import report_folders
from .search import SearchFilters, search_project
from .validation_findings import ValidationFinding
from .workbook_io import row_dicts


@dataclass(frozen=True)
class IndexedSearchResult:
    result_id: str
    result_type: str
    title: str
    matched_source: str
    matched_field: str
    snippet: str
    rank_score: float
    why_matched: str
    audit_id: str = ""
    machine: str = ""
    path: str = ""
    action: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def search_index(project_root: str | Path, query: str = "", filters: SearchFilters | None = None, *, limit: int = 100) -> list[IndexedSearchResult]:
    query_text = query.strip()
    rows: list[IndexedSearchResult] = []
    rows.extend(_wrap_existing_search(project_root, query_text, filters))
    rows.extend(_field_results(project_root, query_text))
    rows.extend(_press_group_results(project_root, query_text))
    deduped = _dedupe(rows)
    filtered = [row for row in deduped if _matches_query(row, query_text)]
    filtered.sort(key=lambda row: row.rank_score, reverse=True)
    return filtered[: max(1, int(limit))]


def _wrap_existing_search(project_root: str | Path, query: str, filters: SearchFilters | None) -> list[IndexedSearchResult]:
    results = search_project(project_root, query, filters, limit=500)
    wrapped: list[IndexedSearchResult] = []
    for result in results:
        matched_field, snippet, score, why = _score_text(query, result.title, result.subtitle, result.detail, result.audit_id, result.machine, result.path)
        wrapped.append(
            IndexedSearchResult(
                result_id=result.result_id,
                result_type=result.result_type,
                title=result.title,
                matched_source=_source_label(result.result_type),
                matched_field=matched_field,
                snippet=snippet,
                rank_score=score + _type_boost(result.result_type),
                why_matched=why,
                audit_id=result.audit_id,
                machine=result.machine,
                path=result.path,
                action=result.action,
                metadata=result.metadata,
            )
        )
    return wrapped


def _field_results(project_root: str | Path, query: str) -> list[IndexedSearchResult]:
    paths = resolve_project_paths(project_root)
    if not paths.master_workbook.exists():
        return []
    try:
        audits = row_dicts(paths.master_workbook, "EOAT Inventory")
    except Exception:
        return []
    results: list[IndexedSearchResult] = []
    for row_index, row in enumerate(audits, start=2):
        audit_id = text_value(row.get("Audit ID"))
        machine = machine_from_audit_row(row)
        for field_name, value in row.items():
            value_text = text_value(value)
            if not value_text:
                continue
            matched_field, snippet, score, why = _score_text(query, str(field_name), value_text, audit_id, machine)
            if query and score <= 0:
                continue
            results.append(
                IndexedSearchResult(
                    result_id=f"field:{audit_id}:{field_name}",
                    result_type="field",
                    title=f"{field_name}: {value_text[:60]}",
                    matched_source="EOAT Inventory",
                    matched_field=str(field_name),
                    snippet=snippet,
                    rank_score=score + 3,
                    why_matched=why,
                    audit_id=audit_id,
                    machine=machine,
                    action="open_audit",
                    metadata={"row_number": row_index},
                )
            )
    return results


def _press_group_results(project_root: str | Path, query: str) -> list[IndexedSearchResult]:
    paths = resolve_project_paths(project_root)
    if not paths.master_workbook.exists():
        return []
    try:
        audits = row_dicts(paths.master_workbook, "EOAT Inventory")
    except Exception:
        return []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in audits:
        machine = machine_from_audit_row(row)
        if machine:
            grouped.setdefault(machine, []).append(row)
    results: list[IndexedSearchResult] = []
    for machine, rows in grouped.items():
        snippet = f"{len(rows)} audit row(s); audits: {', '.join(text_value(row.get('Audit ID')) for row in rows[:5])}"
        matched_field, matched_snippet, score, why = _score_text(query, machine, snippet)
        if query and score <= 0:
            continue
        results.append(
            IndexedSearchResult(
                result_id=f"press_group:{machine}",
                result_type="press_group",
                title=f"Press group {machine}",
                matched_source="Press groups",
                matched_field=matched_field,
                snippet=matched_snippet,
                rank_score=score + 2,
                why_matched=why,
                machine=machine,
                action="open_press",
                metadata={"audit_count": len(rows)},
            )
        )
    return results


def build_search_corpus_counts(project_root: str | Path) -> dict[str, int]:
    paths = resolve_project_paths(project_root)
    counts = {
        "audits": _safe_sheet_count(paths.master_workbook, "EOAT Inventory"),
        "photos": _safe_sheet_count(paths.master_workbook, "Photo Index"),
        "reports": sum(len(folder.recent_files) for folder in report_folders(project_root, limit=100)),
    }
    try:
        counts["open_items"] = len(list_open_items(project_root, include_resolved=True))
    except Exception:
        counts["open_items"] = 0
    counts["validation_findings"] = len(_latest_validation_findings(project_root))
    return counts


def _latest_validation_findings(project_root: str | Path) -> list[ValidationFinding]:
    folder = resolve_project_paths(project_root).validation_reports
    if not folder.exists():
        return []
    for path in sorted(folder.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            import json

            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        return [ValidationFinding.from_dict(row) for row in payload.get("findings", []) if isinstance(row, dict)]
    return []


def _score_text(query: str, *parts: str) -> tuple[str, str, float, str]:
    cleaned = [str(part or "") for part in parts]
    if not query:
        snippet = _snippet(" ".join(cleaned), "")
        return "all", snippet, 1.0, "No query filter; included from indexed source."
    terms = [term for term in query.casefold().split() if term]
    best_field = "text"
    best_text = ""
    score = 0.0
    for index, text in enumerate(cleaned):
        folded = text.casefold()
        term_hits = sum(term in folded for term in terms)
        if term_hits:
            field_score = term_hits * (5 if index == 0 else 2)
            if folded == query.casefold():
                field_score += 10
            if field_score > score:
                score = float(field_score)
                best_text = text
                best_field = ["title", "subtitle", "detail", "audit_id", "machine", "path"][index] if index < 6 else "text"
    if score <= 0:
        return best_field, _snippet(" ".join(cleaned), query), 0.0, "Query terms were not found."
    return best_field, _snippet(best_text or " ".join(cleaned), query), score, f"Matched {int(score)} weighted query signal(s) in {best_field}."


def _snippet(text: str, query: str, length: int = 180) -> str:
    text = " ".join(str(text or "").split())
    if not text:
        return ""
    if not query:
        return text[:length]
    folded = text.casefold()
    first = min((folded.find(term) for term in query.casefold().split() if folded.find(term) >= 0), default=0)
    start = max(0, first - 45)
    return text[start : start + length]


def _type_boost(result_type: str) -> float:
    return {
        "audit": 8,
        "machine": 7,
        "open_item": 6,
        "validation": 5,
        "note": 4,
        "tag": 4,
        "photo": 3,
        "report": 2,
    }.get(result_type, 1)


def _source_label(result_type: str) -> str:
    return {
        "audit": "EOAT Inventory",
        "machine": "Machines",
        "note": "Notes",
        "tag": "Tags",
        "open_item": "Open Items",
        "validation": "Validation Findings",
        "report": "Reports",
        "photo": "Photo Index",
    }.get(result_type, result_type)


def _matches_query(row: IndexedSearchResult, query: str) -> bool:
    if not query:
        return True
    haystack = " ".join([row.title, row.matched_source, row.matched_field, row.snippet, row.audit_id, row.machine, row.path]).casefold()
    return all(term in haystack for term in query.casefold().split() if term)


def _dedupe(rows: list[IndexedSearchResult]) -> list[IndexedSearchResult]:
    by_id: dict[str, IndexedSearchResult] = {}
    for row in rows:
        existing = by_id.get(row.result_id)
        if existing is None or row.rank_score > existing.rank_score:
            by_id[row.result_id] = row
    return list(by_id.values())


def _safe_sheet_count(workbook: Path, sheet_name: str) -> int:
    try:
        return len(row_dicts(workbook, sheet_name))
    except Exception:
        return 0


__all__ = ["IndexedSearchResult", "build_search_corpus_counts", "search_index"]
