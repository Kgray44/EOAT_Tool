from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest

from app.atlas.minimalist.window import MinimalistAtlasWindow
from core.config import UserConfig
from core.data_freshness import FreshnessSettings, PollingState
from core.fit_check_service import FitCheckRequest
from tests.test_minimalist_dropdown_lifecycle import _dropdown_bundle


def _status(revision: int, *, modified_at: datetime) -> dict[str, object]:
    return {
        "status": "available",
        "data_revision": revision,
        "data_last_modified_at": modified_at.isoformat(),
        "last_import_at": "",
        "last_import_source": "acceptance-test",
        "server_time": modified_at.isoformat(),
        "source": "mysql",
        "environment": "test",
    }


def _window(qapp, tmp_path: Path, monkeypatch, *, bundle=None) -> MinimalistAtlasWindow:
    monkeypatch.setenv("EOAT_ATLAS_DATA_BACKEND", "mysql_api")
    monkeypatch.setenv("EOAT_ATLAS_USER_DATA_DIR", str(tmp_path / "user-data"))
    window = MinimalistAtlasWindow(UserConfig(project_root=str(tmp_path)), auto_refresh=False)
    window.page_transition.reduced_motion = True
    window.resize(1400, 900)
    base = bundle or _dropdown_bundle(tmp_path)
    window._data_loaded(replace(base, metrics={**base.metrics, "data_revision": 1}))
    window.show()
    qapp.processEvents()
    _establish_current_status(window)
    return window


def _establish_current_status(window: MinimalistAtlasWindow, revision: int = 1) -> None:
    now = datetime.now(timezone.utc)
    service = window.data_freshness
    service.configure(FreshnessSettings(automatic_polling_enabled=True, refresh_when_data_changes="notify"))
    assert service.begin_check(manual=True)
    transition = service.receive_status(_status(revision, modified_at=now - timedelta(minutes=4)), received_at=now)
    window._freshness_transitioned(service, transition)
    assert service.state == PollingState.CURRENT


def _advance(window: MinimalistAtlasWindow, revision: int) -> None:
    service = window.data_freshness
    now = datetime.now(timezone.utc)
    assert service.begin_check(manual=True)
    transition = service.receive_status(_status(revision, modified_at=now), received_at=now)
    assert transition.kind == "advanced"
    window._freshness_transitioned(service, transition)


def _unlock(settings_content) -> None:
    settings_content._start_admin_session(
        {
            "provider": "development",
            "identity": {"username": "dev.admin", "display_name": "Development Administrator"},
        }
    )
    settings_content.authentication_gateway.authorize = lambda *_args, **_kwargs: {"authorized": True}  # type: ignore[method-assign]
    settings_content.authentication_gateway.audit_settings_action = lambda *_args, **_kwargs: {"recorded": True}  # type: ignore[method-assign]


@pytest.mark.parametrize("resolution", ("save", "discard"))
def test_unsaved_settings_refresh_deferral_resolves_once_without_replacing_the_page(
    qapp, tmp_path: Path, monkeypatch, resolution: str
) -> None:
    """A revision is held while Settings is dirty and resumes exactly once when resolved."""
    window = _window(qapp, tmp_path, monkeypatch)
    next_bundle = replace(window.bundle, metrics={**window.bundle.metrics, "data_revision": 2})
    try:
        assert window.show_page("settings")
        settings_page = window.settings_page
        assert settings_page is not None
        content = settings_page.settings_content
        _unlock(content)
        content._set_setting("data_loading.polling_interval_seconds", 30)
        assert content.dirty_keys == {"data_loading.polling_interval_seconds"}

        window.data_freshness.configure(
            FreshnessSettings(
                automatic_polling_enabled=True,
                refresh_when_data_changes="automatic",
                pause_refresh_while_editing=True,
            )
        )
        refreshes: list[dict[str, object]] = []

        def apply_deferred_refresh(**kwargs) -> None:
            refreshes.append(dict(kwargs))
            window._data_loaded(next_bundle)

        monkeypatch.setattr(window, "refresh_data", apply_deferred_refresh)
        _advance(window, 2)

        assert window.data_freshness.state == PollingState.PAUSED_FOR_EDIT
        assert window.data_freshness.pages["settings"].displayed_revision == 1
        assert window.data_freshness.pages["settings"].stale
        assert window.current_page_key == "settings"
        assert window.stack.currentWidget() is settings_page
        assert content.dirty_keys
        assert refreshes == []
        assert content.toast.isVisible()
        assert "refresh is deferred" in content.toast.label.text().casefold()

        if resolution == "save":
            assert content.save_current_settings()
        else:
            original_interval = content.saved_settings["data_loading"]["polling_interval_seconds"]
            content._discard_unsaved_changes()
            assert content.draft_settings["data_loading"]["polling_interval_seconds"] == original_interval

        QTest.qWait(25)
        qapp.processEvents()
        assert len(refreshes) == 1
        assert refreshes[0] == {"background": True, "freshness_refresh": True}
        assert not content.dirty_keys
        assert window.data_freshness.state == PollingState.CURRENT
        assert window.data_freshness.pages["settings"].displayed_revision == 2
        assert not window.data_freshness.pages["settings"].stale
        assert window.current_page_key == "settings"
        assert window.stack.currentWidget() is settings_page
    finally:
        _cleanup(qapp, window)


def test_fit_check_stale_result_is_never_presented_as_current_and_recalculates_after_apply(
    qapp, tmp_path: Path, monkeypatch
) -> None:
    """A compatibility change visibly stales the prior result before the new bundle is applied."""
    base = _dropdown_bundle(tmp_path)
    window = _window(qapp, tmp_path, monkeypatch, bundle=base)
    try:
        assert window.show_page("fit_check")
        content = window.fit_check_page.fit_content
        request = FitCheckRequest(tool_id="6201510010", machine_id="52", eoat_id="P4-EOAT-0052", eoat_mode="manual")
        content.input_card.apply_request(request)
        content._sync_selector_options()
        content._refresh_result(animate=False)
        assert content.current_result is not None
        assert content.current_result.status in {"compatible", "warning"}

        window.data_freshness.configure(FreshnessSettings(automatic_polling_enabled=True, refresh_when_data_changes="notify"))
        _advance(window, 2)

        assert window.data_freshness.state == PollingState.UPDATE_AVAILABLE
        assert window.data_freshness.pages["fit_check"].stale
        assert content.current_result is not None
        assert content.result_card.headline.text() == "Result needs refresh"
        assert "stale" in content.result_card.message.text().casefold()
        assert content.input_card.selected_key("tool") == request.tool_id
        assert content.input_card.selected_key("machine") == request.machine_id
        assert content.input_card.selected_key("eoat") == request.eoat_id

        assert window.show_page("home")
        assert window.show_page("fit_check")
        assert content.result_card.headline.text() == "Result needs refresh"
        assert "stale" in content.result_card.message.text().casefold()

        incompatible_tool = replace(base.tools[0], compatible_eoats=("P4-EOAT-0099",))
        incompatible_eoat = replace(base.eoats[0], tools=())
        incompatible = replace(
            base,
            tools=(incompatible_tool, *base.tools[1:]),
            eoats=(incompatible_eoat, *base.eoats[1:]),
            metrics={**base.metrics, "data_revision": 2},
        )
        window._data_loaded(incompatible)

        assert content.current_result is not None
        assert content.current_result.status == "not_compatible"
        assert content.result_card.headline.text() == "Not Compatible"
        assert window.data_freshness.pages["fit_check"].displayed_revision == 2
        assert not window.data_freshness.pages["fit_check"].stale
    finally:
        _cleanup(qapp, window)


def test_fit_check_invalidated_selection_is_explained_without_substitution_or_history_duplication(
    qapp, tmp_path: Path, monkeypatch
) -> None:
    base = _dropdown_bundle(tmp_path)
    window = _window(qapp, tmp_path, monkeypatch, bundle=base)
    try:
        assert window.show_page("fit_check")
        content = window.fit_check_page.fit_content
        request = FitCheckRequest(tool_id="6201510010", machine_id="52", eoat_id="P4-EOAT-0052", eoat_mode="manual")
        content.input_card.apply_request(request)
        content._sync_selector_options()
        content._refresh_result(animate=False)
        before_history = deepcopy(content.recent_checks)

        removed = replace(
            base,
            eoats=tuple(record for record in base.eoats if record.eoat_id != request.eoat_id),
            metrics={**base.metrics, "data_revision": 2},
        )
        window.data_freshness.current_revision = 2
        window._data_loaded(removed)

        assert content.input_card.selected_key("tool") == request.tool_id
        assert content.input_card.selected_key("machine") == request.machine_id
        # Retain the user's unavailable identifier so the invalid selection is
        # explained; never choose a different EOAT on the user's behalf.
        assert content.input_card.selected_key("eoat") == request.eoat_id
        assert content.current_result is not None
        assert content.current_result.status == "invalid_input"
        assert request.eoat_id in content.current_result.message
        assert content.recent_checks == before_history
        assert window.data_freshness.pages["fit_check"].displayed_revision == 2
        assert not window.data_freshness.pages["fit_check"].stale
    finally:
        _cleanup(qapp, window)


def test_snapshot_apply_preserves_search_fit_library_and_settings_context(qapp, tmp_path: Path, monkeypatch) -> None:
    """A revised snapshot updates data without resetting the user's logical place."""
    window = _window(qapp, tmp_path, monkeypatch)
    try:
        home_card = window.home_page.home_content.card
        home_card.search_bar.input.setText("620")

        assert window.show_page("fit_check")
        fit = window.fit_check_page.fit_content
        request = FitCheckRequest(tool_id="6201510010", machine_id="52", eoat_id="P4-EOAT-0052", eoat_mode="manual")
        fit.input_card.apply_request(request)
        fit._sync_selector_options()
        fit._refresh_result(animate=False)

        assert window.show_page("library")
        library = window.library_page.library_content
        library.open_filtered_view(query="620", record_type="eoat")
        qapp.processEvents()

        assert window.show_page("settings")
        settings = window.settings_page.settings_content
        settings.select_section("refresh_cache")
        next_bundle = replace(window.bundle, metrics={**window.bundle.metrics, "data_revision": 2})
        window.data_freshness.current_revision = 2
        window._data_loaded(next_bundle)
        qapp.processEvents()

        assert window.current_page_key == "settings"
        assert settings.selected_key == "refresh_cache"
        assert home_card.search_bar.input.text() == "620"
        assert fit.input_card.selected_key("tool") == request.tool_id
        assert fit.input_card.selected_key("machine") == request.machine_id
        assert fit.input_card.selected_key("eoat") == request.eoat_id
        assert library.browse_query == "620"
        assert library.scope_type == "eoat"
    finally:
        _cleanup(qapp, window)


def test_navigation_and_page_construction_never_rewrite_authoritative_update_time(qapp, tmp_path: Path, monkeypatch) -> None:
    window = _window(qapp, tmp_path, monkeypatch)
    try:
        original = window.data_freshness.data_last_modified_at
        assert original is not None
        for key in ("library", "fit_check", "settings", "diagnostics", "data_health", "home", "library", "home"):
            assert window.show_page(key)
            qapp.processEvents()
            assert window.data_freshness.data_last_modified_at == original

        service = window.data_freshness
        assert service.begin_check(manual=True)
        transition = service.receive_status(_status(1, modified_at=original + timedelta(days=1)))
        window._freshness_transitioned(service, transition)
        assert transition.kind == "unchanged"
        assert service.data_last_modified_at == original
    finally:
        _cleanup(qapp, window)


def _cleanup(qapp, widget) -> None:
    widget.close()
    widget.deleteLater()
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
