from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .logging import log_tool_run
from .paths import resolve_project_paths
from .performance import log_performance_event
from .result import ToolResult
from .validation import validate_project_foundation
from .validation_findings import findings_from_result

TOOL_ID = "backup_manager"
TOOL_NAME = "Backup Manager"

WORKBOOK_SUFFIXES = {".xlsx", ".xlsm", ".xls", ".xlsb"}
MILESTONE_WORDS = ("milestone", "baseline", "release", "final", "approved", "handoff")


@dataclass(frozen=True)
class BackupRetentionPolicy:
    keep_recent_days: int = 7
    keep_last_per_workbook: int = 25
    keep_milestones: bool = True
    require_confirmation: bool = True


@dataclass(frozen=True)
class BackupRecord:
    path: str
    source_workbook: str
    size_bytes: int
    modified_at: str
    age_days: int
    milestone: bool
    keep_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BackupSummary:
    backup_count: int
    total_size_bytes: int
    oldest_backup: str
    newest_backup: str
    by_source_workbook: dict[str, int]
    cleanup_candidates: tuple[BackupRecord, ...]
    retained: tuple[BackupRecord, ...]
    validation_blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["cleanup_candidates"] = [item.to_dict() for item in self.cleanup_candidates]
        data["retained"] = [item.to_dict() for item in self.retained]
        return data


def discover_workbook_backups(project_root: str | Path, *, now: datetime | None = None) -> list[BackupRecord]:
    paths = resolve_project_paths(project_root)
    now = now or datetime.now()
    started = time.perf_counter()
    roots = [
        paths.project_admin / "Backups",
        paths.master_workbook.parent / "_backups",
        paths.robot_info_workbook.parent / "_backups",
        paths.project_root / "Backups",
    ]
    files: dict[Path, BackupRecord] = {}
    counts_by_folder: dict[str, int] = {}
    for root in roots:
        folder_started = time.perf_counter()
        count = 0
        if not root.exists():
            counts_by_folder[str(root)] = 0
            log_performance_event(
                paths.project_root,
                "backup_manager.scan.folder",
                time.perf_counter() - folder_started,
                source="backup_manager",
                page_tool="backup_manager",
                details={"folder": str(root), "count": 0, "exists": False},
            )
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.name.startswith("~$") or path.suffix.lower() not in WORKBOOK_SUFFIXES:
                continue
            stat = path.stat()
            modified = datetime.fromtimestamp(stat.st_mtime)
            age_days = max(0, (now.date() - modified.date()).days)
            files[path.resolve()] = BackupRecord(
                path=str(path),
                source_workbook=_source_workbook_name(path),
                size_bytes=stat.st_size,
                modified_at=modified.isoformat(timespec="seconds"),
                age_days=age_days,
                milestone=_is_milestone(path),
            )
            count += 1
        counts_by_folder[str(root)] = count
        log_performance_event(
            paths.project_root,
            "backup_manager.scan.folder",
            time.perf_counter() - folder_started,
            source="backup_manager",
            page_tool="backup_manager",
            details={"folder": str(root), "count": count, "exists": True},
        )
    log_performance_event(
        paths.project_root,
        "backup_manager.scan",
        time.perf_counter() - started,
        source="backup_manager",
        page_tool="backup_manager",
        details={"folder_counts": counts_by_folder, "backup_count": len(files)},
    )
    return sorted(files.values(), key=lambda item: item.modified_at, reverse=True)


def summarize_backups(
    project_root: str | Path,
    policy: BackupRetentionPolicy | None = None,
    *,
    now: datetime | None = None,
) -> BackupSummary:
    policy = policy or BackupRetentionPolicy()
    records = discover_workbook_backups(project_root, now=now)
    blockers = tuple(_latest_validation_blockers(project_root))
    retained, candidates = _retention_split(records, policy, blockers, now or datetime.now())
    by_source: dict[str, int] = {}
    for record in records:
        by_source[record.source_workbook] = by_source.get(record.source_workbook, 0) + 1
    warnings = []
    if blockers:
        warnings.append("Cleanup disabled because latest workbook validation has blocker/error findings.")
    return BackupSummary(
        backup_count=len(records),
        total_size_bytes=sum(record.size_bytes for record in records),
        oldest_backup=min((record.modified_at for record in records), default=""),
        newest_backup=max((record.modified_at for record in records), default=""),
        by_source_workbook=by_source,
        cleanup_candidates=tuple(candidates),
        retained=tuple(retained),
        validation_blockers=blockers,
        warnings=tuple(warnings),
    )


def preview_backup_cleanup(project_root: str | Path, policy: BackupRetentionPolicy | None = None) -> ToolResult:
    started = time.perf_counter()
    summary = summarize_backups(project_root, policy)
    result = ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        "Previewed backup cleanup candidates.",
        details=_summary_details(summary, applied=False),
        warnings=list(summary.warnings),
        metrics={
            "backup_count": summary.backup_count,
            "cleanup_candidate_count": len(summary.cleanup_candidates),
            "cleanup_candidate_bytes": sum(item.size_bytes for item in summary.cleanup_candidates),
        },
        structured_data=summary.to_dict(),
        duration_seconds=time.perf_counter() - started,
    )
    warning = log_tool_run(result, project_root)
    if warning:
        result.warnings.append(warning)
    return result


def cleanup_old_backups(
    project_root: str | Path,
    policy: BackupRetentionPolicy | None = None,
    *,
    confirm: bool = False,
    dry_run: bool = True,
) -> ToolResult:
    started = time.perf_counter()
    policy = policy or BackupRetentionPolicy()
    summary = summarize_backups(project_root, policy)
    if dry_run:
        return preview_backup_cleanup(project_root, policy)
    if policy.require_confirmation and not confirm:
        return ToolResult.fail(
            TOOL_ID,
            TOOL_NAME,
            "Backup cleanup requires explicit confirmation.",
            errors=["Pass confirm=True after reviewing the cleanup preview."],
            structured_data=summary.to_dict(),
            duration_seconds=time.perf_counter() - started,
        )
    if summary.validation_blockers:
        return ToolResult.fail(
            TOOL_ID,
            TOOL_NAME,
            "Backup cleanup refused because validation has blockers.",
            errors=list(summary.validation_blockers),
            structured_data=summary.to_dict(),
            duration_seconds=time.perf_counter() - started,
        )

    deleted: list[str] = []
    warnings: list[str] = []
    for record in summary.cleanup_candidates:
        path = Path(record.path)
        try:
            path.unlink()
            deleted.append(str(path))
        except OSError as exc:
            warnings.append(f"Could not delete backup {path}: {exc}")

    result = ToolResult.ok(
        TOOL_ID,
        TOOL_NAME,
        "Cleaned old workbook backups.",
        details=_summary_details(summary, applied=True),
        warnings=warnings,
        files_modified=deleted,
        metrics={
            "backup_count": summary.backup_count,
            "deleted_count": len(deleted),
            "deleted_bytes": sum(item.size_bytes for item in summary.cleanup_candidates if item.path in set(deleted)),
        },
        structured_data=summary.to_dict(),
        duration_seconds=time.perf_counter() - started,
    )
    warning = log_tool_run(result, project_root)
    if warning:
        result.warnings.append(warning)
    return result


def _retention_split(
    records: list[BackupRecord],
    policy: BackupRetentionPolicy,
    validation_blockers: tuple[str, ...],
    now: datetime,
) -> tuple[list[BackupRecord], list[BackupRecord]]:
    if validation_blockers:
        return [record_with_reason(record, "Kept because validation blockers are present.") for record in records], []

    recent_cutoff = now - timedelta(days=policy.keep_recent_days)
    by_source: dict[str, list[BackupRecord]] = {}
    for record in records:
        by_source.setdefault(record.source_workbook, []).append(record)
    newest_kept = {
        record.path
        for group in by_source.values()
        for record in sorted(group, key=lambda item: item.modified_at, reverse=True)[: policy.keep_last_per_workbook]
    }

    retained: list[BackupRecord] = []
    candidates: list[BackupRecord] = []
    for record in records:
        modified = _parse_dt(record.modified_at)
        if modified >= recent_cutoff:
            retained.append(record_with_reason(record, f"Kept because it is within the last {policy.keep_recent_days} days."))
        elif record.path in newest_kept:
            retained.append(record_with_reason(record, f"Kept as one of the newest {policy.keep_last_per_workbook} backups for {record.source_workbook}."))
        elif policy.keep_milestones and record.milestone:
            retained.append(record_with_reason(record, "Kept because it appears to be a milestone backup."))
        else:
            candidates.append(record_with_reason(record, "Older than retention windows and not a milestone."))
    return retained, candidates


def record_with_reason(record: BackupRecord, reason: str) -> BackupRecord:
    return BackupRecord(
        path=record.path,
        source_workbook=record.source_workbook,
        size_bytes=record.size_bytes,
        modified_at=record.modified_at,
        age_days=record.age_days,
        milestone=record.milestone,
        keep_reason=reason,
    )


def _latest_validation_blockers(project_root: str | Path) -> list[str]:
    try:
        result = validate_project_foundation(project_root)
    except Exception as exc:
        return [f"Could not validate project before cleanup: {exc}"]
    blockers = [finding.message for finding in findings_from_result(result) if str(finding.severity).upper() == "BLOCKER"]
    blockers.extend(result.errors)
    return blockers


def _source_workbook_name(path: Path) -> str:
    stem = path.stem
    lower = stem.lower()
    for marker in ("_backup_before", "_backup_", "_backup"):
        index = lower.find(marker)
        if index > 0:
            return f"{stem[:index]}{path.suffix}"
    return path.name


def _is_milestone(path: Path) -> bool:
    text = path.as_posix().lower()
    return any(word in text for word in MILESTONE_WORDS)


def _parse_dt(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.fromtimestamp(0)


def _summary_details(summary: BackupSummary, *, applied: bool) -> list[str]:
    action = "Deleted" if applied else "Would delete"
    return [
        f"Backups found: {summary.backup_count}",
        f"Total size: {_format_bytes(summary.total_size_bytes)}",
        f"Oldest backup: {summary.oldest_backup or 'None'}",
        f"Newest backup: {summary.newest_backup or 'None'}",
        f"{action}: {len(summary.cleanup_candidates)} backup(s)",
        "By source workbook: " + (", ".join(f"{key}: {value}" for key, value in sorted(summary.by_source_workbook.items())) or "None"),
    ]


def _format_bytes(value: int) -> str:
    size = float(value)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024


__all__ = [
    "BackupRecord",
    "BackupRetentionPolicy",
    "BackupSummary",
    "cleanup_old_backups",
    "discover_workbook_backups",
    "preview_backup_cleanup",
    "summarize_backups",
]
