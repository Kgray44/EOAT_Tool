from __future__ import annotations

import os
from datetime import datetime, timedelta

from core.backup_manager import BackupRetentionPolicy, cleanup_old_backups, discover_workbook_backups, summarize_backups
from core.paths import resolve_project_paths


def _write_backup(path, now: datetime, days_old: int, text: str = "backup"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    stamp = (now - timedelta(days=days_old)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def test_backup_discovery_reports_counts_by_source(fake_project, monkeypatch):
    monkeypatch.setattr("core.backup_manager._latest_validation_blockers", lambda _root: [])
    now = datetime(2026, 5, 28, 12, 0)
    paths = resolve_project_paths(fake_project)
    _write_backup(
        paths.project_admin / "Backups" / "Workbook_Backups" / "EOAT_Master_Tracker_backup_20260501_080000.xlsx",
        now,
        10,
    )
    _write_backup(paths.master_workbook.parent / "_backups" / "Robot_Info_backup_20260501_080000.xlsx", now, 9)

    records = discover_workbook_backups(fake_project, now=now)
    summary = summarize_backups(fake_project, now=now)

    assert len(records) == 2
    assert summary.backup_count == 2
    assert summary.by_source_workbook["EOAT_Master_Tracker.xlsx"] == 1
    assert summary.by_source_workbook["Robot_Info.xlsx"] == 1


def test_backup_retention_selects_old_excess_candidates(fake_project, monkeypatch):
    monkeypatch.setattr("core.backup_manager._latest_validation_blockers", lambda _root: [])
    now = datetime(2026, 5, 28, 12, 0)
    folder = resolve_project_paths(fake_project).project_admin / "Backups" / "Workbook_Backups"
    for index in range(30):
        _write_backup(folder / f"EOAT_Master_Tracker_backup_202604{index + 1:02d}_080000.xlsx", now, 10 + index)
    _write_backup(folder / "EOAT_Master_Tracker_milestone_backup_20260301_080000.xlsx", now, 80)

    summary = summarize_backups(
        fake_project, BackupRetentionPolicy(keep_recent_days=7, keep_last_per_workbook=25), now=now
    )

    assert len(summary.cleanup_candidates) == 5
    assert all("milestone" not in item.path.lower() for item in summary.cleanup_candidates)


def test_backup_cleanup_dry_run_and_confirmation(fake_project, monkeypatch):
    monkeypatch.setattr("core.backup_manager._latest_validation_blockers", lambda _root: [])
    now = datetime(2026, 5, 28, 12, 0)
    folder = resolve_project_paths(fake_project).project_admin / "Backups" / "Workbook_Backups"
    backups = [
        _write_backup(folder / f"EOAT_Master_Tracker_backup_202604{index + 1:02d}_080000.xlsx", now, 20 + index)
        for index in range(27)
    ]

    dry = cleanup_old_backups(
        fake_project, BackupRetentionPolicy(keep_recent_days=7, keep_last_per_workbook=25), dry_run=True
    )
    refused = cleanup_old_backups(
        fake_project, BackupRetentionPolicy(keep_recent_days=7, keep_last_per_workbook=25), dry_run=False, confirm=False
    )

    assert dry.success is True
    assert all(path.exists() for path in backups)
    assert refused.success is False
    assert all(path.exists() for path in backups)

    applied = cleanup_old_backups(
        fake_project, BackupRetentionPolicy(keep_recent_days=7, keep_last_per_workbook=25), dry_run=False, confirm=True
    )

    assert applied.success is True
    assert applied.metrics["deleted_count"] == 2


def test_backup_cleanup_refuses_when_validation_has_blockers(fake_project, monkeypatch):
    monkeypatch.setattr("core.backup_manager._latest_validation_blockers", lambda _root: ["Master workbook missing."])
    now = datetime(2026, 5, 28, 12, 0)
    folder = resolve_project_paths(fake_project).project_admin / "Backups" / "Workbook_Backups"
    _write_backup(folder / "EOAT_Master_Tracker_backup_20260401_080000.xlsx", now, 40)

    result = cleanup_old_backups(
        fake_project, BackupRetentionPolicy(keep_recent_days=7, keep_last_per_workbook=0), dry_run=False, confirm=True
    )

    assert result.success is False
    assert "validation has blockers" in result.summary
