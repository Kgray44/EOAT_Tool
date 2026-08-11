from __future__ import annotations

from server.eoat_api.authentication.routes import read_settings_catalog


def test_settings_catalog_uses_the_headless_shared_registry() -> None:
    """The API must not import the GUI package to describe Settings."""
    catalog = read_settings_catalog()

    assert [section.key for section in catalog.sections] == [
        "data_sources",
        "refresh_cache",
        "read_only_safety",
        "search_navigation",
        "fit_check",
        "library",
        "display_accessibility",
        "setup_packet_pdf",
        "validation_health",
        "reference_documents",
        "diagnostics_support",
        "about",
    ]
    assert len(catalog.items) == 118
