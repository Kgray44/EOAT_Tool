from __future__ import annotations

from core.audit_field_links import (
    build_audit_field_link,
    friendly_audit_field_label,
    parse_audit_field_link,
    serialize_audit_field_link,
)


def test_audit_field_link_serializes_and_parses_stable_fields():
    link = build_audit_field_link(
        {
            "Audit ID": "AUD-LINK-001",
            "Press/Machine #": "Press 12",
            "Tool #": "TOOL-ABC",
        },
        "Tubing Routing Notes",
        "Tubing Routing Notes",
        created_at="2026-06-02T12:00:00+00:00",
    )

    text = serialize_audit_field_link(link)
    parsed = parse_audit_field_link(text)

    assert parsed is not None
    assert parsed.audit_id == "AUD-LINK-001"
    assert parsed.machine_number == "Press 12"
    assert parsed.tool_number == "TOOL-ABC"
    assert parsed.field_key == "Tubing Routing Notes"
    assert parsed.field_label == "Tubing Routing Notes"
    assert "audit_id=AUD-LINK-001" in text
    assert "field_key=Tubing%20Routing%20Notes" in text
    assert friendly_audit_field_label(parsed) == "Press 12 / Tool TOOL-ABC / Field: Tubing Routing Notes / Audit AUD-LINK-001"


def test_legacy_plain_text_audit_field_link_is_unavailable():
    assert parse_audit_field_link("Machine 12 - Tubing Routing Notes") is None
    assert friendly_audit_field_label("Machine 12 - Tubing Routing Notes") == ""
