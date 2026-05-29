from __future__ import annotations

from app.feature_registry import build_feature_registry
from app.page_registry import PAGE_BY_KEY


def test_feature_registry_has_no_duplicate_features_and_valid_pages():
    registry = build_feature_registry()
    features = registry.list_features()
    ids = [feature.id for feature in features]

    assert ids
    assert len(ids) == len(set(ids))
    assert registry.validate() == []
    assert all(feature.page_key in PAGE_BY_KEY for feature in features)


def test_feature_registry_exposes_phase_21_metadata():
    registry = build_feature_registry()
    audit = registry.get("audit")
    workbook_health = registry.get("workbook_health")

    assert audit is not None
    assert audit.key == audit.id
    assert audit.route == "page:audit"
    assert "nav.audit" in audit.commands
    assert "EOAT Inventory" in audit.search_sources
    assert audit.data_dependencies
    assert audit.modifies_files is True

    assert workbook_health is not None
    assert workbook_health.event_listeners
    assert workbook_health.help_topics
