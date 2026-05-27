from __future__ import annotations

from core.dashboard_cache import cached_snapshot, dashboard_cache_path, load_dashboard_cache, save_dashboard_cache


def test_dashboard_cache_round_trip(fake_project):
    snapshot = {"cards": {"EOATs Audited": "2"}, "recommendations": ["Keep going"], "activity_text": "ok"}

    path = save_dashboard_cache(fake_project, snapshot)
    payload, warning = load_dashboard_cache(fake_project)
    loaded, stale, cached_warning = cached_snapshot(fake_project)

    assert path == dashboard_cache_path(fake_project)
    assert warning is None
    assert payload is not None
    assert loaded == snapshot
    assert stale is False
    assert cached_warning is None


def test_dashboard_cache_marks_source_changes_stale(fake_project):
    save_dashboard_cache(fake_project, {"cards": {}, "recommendations": [], "activity_text": ""})

    activity_log = fake_project / "00_Project_Admin" / "Activity_Logs" / "activity_log.jsonl"
    activity_log.write_text('{"tool_name":"test"}\n', encoding="utf-8")
    _snapshot, stale, warning = cached_snapshot(fake_project)

    assert warning is None
    assert stale is True


def test_dashboard_cache_bad_json_recovers_gracefully(fake_project):
    path = dashboard_cache_path(fake_project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")

    snapshot, stale, warning = cached_snapshot(fake_project)

    assert snapshot is None
    assert stale is True
    assert "Could not load dashboard cache" in warning
