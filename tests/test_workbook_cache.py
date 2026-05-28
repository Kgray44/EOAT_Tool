from __future__ import annotations

from openpyxl import load_workbook

from core.audit_entries import save_audit_entry
from core.paths import resolve_project_paths
from core.workbook_cache import invalidate_workbook_cache, row_dicts_cached


def test_row_dicts_cached_hits_second_read(fake_project, monkeypatch):
    import core.workbook_cache as workbook_cache

    calls = {"count": 0}
    original = workbook_cache.row_dicts

    def counted(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(workbook_cache, "row_dicts", counted)
    workbook_path = resolve_project_paths(fake_project).master_workbook

    first = row_dicts_cached(workbook_path, "EOAT Inventory")
    second = row_dicts_cached(workbook_path, "EOAT Inventory")

    assert first == second
    assert calls["count"] == 1


def test_row_dicts_cached_misses_after_file_signature_changes(fake_project, monkeypatch):
    import core.workbook_cache as workbook_cache

    calls = {"count": 0}
    original = workbook_cache.row_dicts

    def counted(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(workbook_cache, "row_dicts", counted)
    workbook_path = resolve_project_paths(fake_project).master_workbook
    row_dicts_cached(workbook_path, "EOAT Inventory")

    workbook = load_workbook(workbook_path)
    ws = workbook["EOAT Inventory"]
    ws.append(["AUD-CACHE-SIG"])
    workbook.save(workbook_path)
    workbook.close()

    row_dicts_cached(workbook_path, "EOAT Inventory")

    assert calls["count"] == 2


def test_invalidate_workbook_cache_clears_cached_rows(fake_project, monkeypatch):
    import core.workbook_cache as workbook_cache

    calls = {"count": 0}
    original = workbook_cache.row_dicts

    def counted(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(workbook_cache, "row_dicts", counted)
    workbook_path = resolve_project_paths(fake_project).master_workbook
    row_dicts_cached(workbook_path, "EOAT Inventory")
    invalidate_workbook_cache(workbook_path)
    row_dicts_cached(workbook_path, "EOAT Inventory")

    assert calls["count"] == 2


def test_save_audit_invalidates_workbook_cache(fake_project):
    workbook_path = resolve_project_paths(fake_project).master_workbook
    assert row_dicts_cached(workbook_path, "EOAT Inventory") == []

    result = save_audit_entry(
        fake_project,
        {
            "Audit ID": "AUD-CACHE-SAVE",
            "Audit Date": "2026-05-18",
            "Auditor": "KG",
            "Plant/Area": "Plant 4",
            "Press/Machine #": "12",
            "Robot Type": "Wittmann R9",
            "EOAT Type": "Vacuum",
            "Status": "In Progress",
        },
    )

    assert result.success, result.errors
    rows = row_dicts_cached(workbook_path, "EOAT Inventory")
    assert any(row.get("Audit ID") == "AUD-CACHE-SAVE" for row in rows)
