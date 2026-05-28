from __future__ import annotations

from app.pages.home import collect_home_quick_status_snapshot
from core.dashboard_cache import save_dashboard_cache


def test_home_quick_refresh_uses_cached_snapshot_without_deep_collectors(fake_project, monkeypatch):
    import app.pages.home as home

    save_dashboard_cache(
        fake_project,
        {
            "cards": {"EOATs Audited": "9"},
            "recommendations": ["Cached recommendation"],
            "activity_text": "Cached activity",
        },
    )
    activity_log = fake_project / "00_Project_Admin" / "Activity_Logs" / "activity_log.jsonl"
    activity_log.write_text('{"tool_name":"changed"}\n', encoding="utf-8")

    def fail_if_fallback_project_validation_runs(*_args, **_kwargs):
        raise AssertionError("quick refresh should use the cache snapshot instead of fallback project validation")

    monkeypatch.setattr(home, "validate_looks_like_eoat_project_root", fail_if_fallback_project_validation_runs)

    snapshot = collect_home_quick_status_snapshot(str(fake_project), git_executable="git")

    assert snapshot["cards"]["EOATs Audited"] == "9"
    assert snapshot["cards"]["Dashboard Cache"].startswith("Stale")
    assert "Dashboard cache stale because" in snapshot["activity_text"]
