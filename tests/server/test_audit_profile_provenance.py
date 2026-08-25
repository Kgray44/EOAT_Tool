from datetime import datetime

import pytest

from server.eoat_api.audit_profiles import configuration_from_details, latest_physical_audit
from server.eoat_api.contracts import CurrentEOATLocation, EOATProfile, EOATSummary
from tools.migration.audit_profile_backfill import execute_backfill
from tools.migration.import_pipeline import _latest_physical_profile_row


def _p4_details(**overrides):
    values = {
        "Audit ID": "AUD-20260521-012",
        "Audit Date": "2026-05-21",
        "Entry Type": "Audited",
        "Press/Machine #": "9",
        "Tool #": "7130080010",
        "Part Name/Description": "TOP CAP",
        "EOAT Type": "Hybrid",
        "Connection Type": "DoveTail",
        "Cleanroom/Non-Cleanroom": "Whiteroom",
        "Number of Parts Picked": "4",
        "# of Grippers": "1",
        "Gripper Type": "Single Pressure",
        "# of Cups": "4",
        "Cup Type/Material": "Silicone",
        "Cup Diameter/Size": "15",
        "Vacuum Generator Type": "Venturi",
        "EOAT Vacuum Circuits": "2",
        "EOAT Pressure Circuits": "0",
        "Sensors Present?": "No",
        "Part-Present Detection Present?": "N/A",
        "Vacuum Confirmation Present?": "N/A",
        "Quick Disconnects Present?": "Yes",
        "Pneumatic Quick Disconnect Type": "PTC",
        "Electrical/Wiring Present?": "No",
        "Physical Audit Verified": "Yes",
    }
    values.update(overrides)
    return values


def test_physical_audit_projection_preserves_zero_false_and_provenance():
    projection = latest_physical_audit(
        [
            {
                "audit_identifier": "AUD-20260521-012",
                "audit_date": datetime(2026, 5, 21),
                "source_row_number": 15,
                "details_json": _p4_details(),
            }
        ]
    )

    assert projection is not None
    assert projection.audit_identifier == "AUD-20260521-012"
    assert projection.observed_machine == "9"
    assert projection.observed_tool == "7130080010"
    assert projection.verified is True
    assert projection.configuration == {
        "description": "TOP CAP",
        "eoat_type": "Hybrid",
        "connection_type": "DoveTail",
        "cleanroom_classification": "Whiteroom",
        "parts_picked": 4,
        "vacuum_cup_count": 4,
        "gripper_count": 1,
        "cup_material": "Silicone",
        "cup_size": "15",
        "vacuum_generator": "Venturi",
        "vacuum_circuits": 2,
        "pressure_circuits": 0,
        "gripper_type": "Single Pressure",
        "gripper_model": None,
        "sensors_present": False,
        "part_present_sensor_present": None,
        "vacuum_confirmation_sensor_present": None,
        "quick_disconnect_present": True,
        "pneumatic_disconnect_type": "PTC",
        "electrical_disconnect_type": None,
        "electrical_wiring_present": False,
    }


def test_projection_uses_latest_physical_audit_and_ignores_derived_rows():
    derived = _p4_details(
        **{"Audit ID": "AUD-DERIVED", "Entry Type": "Compatible", "Source Audit ID": "AUD-20260521-012"}
    )
    older = _p4_details(**{"Audit ID": "AUD-OLD", "# of Cups": "2"})
    newer = _p4_details(**{"Audit ID": "AUD-NEW", "# of Cups": "5"})
    projection = latest_physical_audit(
        [
            {
                "audit_identifier": "AUD-DERIVED",
                "audit_date": datetime(2027, 1, 1),
                "source_row_number": 99,
                "details_json": derived,
            },
            {
                "audit_identifier": "AUD-OLD",
                "audit_date": datetime(2026, 5, 1),
                "source_row_number": 2,
                "details_json": older,
            },
            {
                "audit_identifier": "AUD-NEW",
                "audit_date": datetime(2026, 6, 1),
                "source_row_number": 3,
                "details_json": newer,
            },
        ]
    )

    assert projection is not None
    assert projection.audit_identifier == "AUD-NEW"
    assert projection.configuration["vacuum_cup_count"] == 5


def test_initial_import_uses_latest_physical_row_not_spreadsheet_order():
    older = _p4_details(**{"Audit Date": "2026-05-01", "# of Cups": "2"})
    newer = _p4_details(**{"Audit Date": "2026-06-01", "# of Cups": "5"})
    selected = _latest_physical_profile_row([(2, older), (3, newer)])

    assert selected["# of Cups"] == "5"


def test_unknown_source_values_remain_null_not_false_or_zero():
    values = configuration_from_details(
        _p4_details(
            **{
                "# of Cups": "N/A",
                "EOAT Pressure Circuits": "Unknown",
                "Sensors Present?": "N/A",
                "Physical Audit Verified": "N/A",
            }
        )
    )

    assert values["vacuum_cup_count"] is None
    assert values["pressure_circuits"] is None
    assert values["sensors_present"] is None


def test_backfill_execute_fails_closed_for_production_or_unknown_targets(monkeypatch):
    monkeypatch.setenv("EOAT_API_ENVIRONMENT", "production")
    monkeypatch.setenv("EOAT_DB_NAME", "eoat_atlas_prod")

    with pytest.raises(RuntimeError, match="explicit non-production"):
        execute_backfill("unused.xlsx", dry_run=False)

    monkeypatch.setenv("EOAT_API_ENVIRONMENT", "staging")

    with pytest.raises(RuntimeError, match="approved development or staging database"):
        execute_backfill("unused.xlsx", dry_run=False)


def test_profile_can_replace_summary_location_with_authoritative_current_location():
    summary = EOATSummary(
        business_identifier="P4-EOAT-0006",
        is_active=True,
        row_version=1,
        current_location="UNKNOWN_NOT_VERIFIED",
    )
    location = CurrentEOATLocation(state="INSTALLED", source="LIFECYCLE_EVENT", machine_number="9")
    profile_summary = summary.model_dump()
    profile_summary.update(current_location=location.state, current_location_detail=location)

    profile = EOATProfile(**profile_summary)

    assert profile.current_location == "INSTALLED"
    assert profile.current_location_detail == location
