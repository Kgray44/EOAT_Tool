from datetime import datetime
from types import SimpleNamespace

from server.eoat_api.audit_profiles import (
    configuration_from_details,
    latest_physical_audit,
    normalize_optional_hardware_values,
)


def _audit(identifier: str, when: datetime, row: int, **values):
    details = {
        "Audit ID": identifier,
        "Entry Type": "Audited",
        "Physical Audit Verified": "Yes",
        "Press/Machine #": "43",
        "EOAT Type": "Vacuum",
        "# of Cups": "32",
        "Sensors Present?": "No",
    }
    details.update(values)
    return SimpleNamespace(audit_identifier=identifier, audit_date=when, source_row_number=row, details_json=details)


def test_latest_verified_physical_audit_preserves_false_zero_and_known_configuration():
    projection = latest_physical_audit([
        _audit("AUD-OLD", datetime(2026, 6, 1), 1, **{"# of Cups": "2"}),
        _audit("AUD-NEW", datetime(2026, 6, 23), 2, **{"# of Cups": "32", "EOAT Pressure Circuits": "0"}),
    ])

    assert projection is not None
    assert projection.audit_identifier == "AUD-NEW"
    assert projection.observed_machine == "43"
    assert projection.configuration["vacuum_cup_count"] == 32
    assert projection.configuration["pressure_circuits"] == 0
    assert projection.configuration["sensors_present"] is False


def test_derived_compatibility_evidence_never_becomes_a_physical_observation():
    physical = _audit("AUD-PHYSICAL", datetime(2026, 6, 23), 2)
    derived = _audit("AUD-DERIVED", datetime(2027, 1, 1), 3, **{"Entry Type": "Compatible", "Source Audit ID": "AUD-PHYSICAL", "Press/Machine #": "55"})

    projection = latest_physical_audit([physical, derived])

    assert projection is not None
    assert projection.audit_identifier == "AUD-PHYSICAL"
    assert projection.observed_machine == "43"


def test_source_na_is_normalized_only_when_the_audit_schema_proves_absence():
    configuration = configuration_from_details({
        "EOAT Type": "Vacuum",
        "# of Cups": "32",
        "# of Grippers": "N/A",
        "Sensors Present?": "No",
        "Part-Present Detection Present?": "N/A",
        "Vacuum Confirmation Present?": "N/A",
    })

    assert configuration["vacuum_cup_count"] == 32
    assert configuration["gripper_count"] == 0
    assert configuration["sensors_present"] is False
    assert configuration["part_present_sensor_present"] is False
    assert configuration["vacuum_confirmation_sensor_present"] is False


def test_nonexclusive_types_and_descriptive_blanks_remain_unknown():
    configuration = configuration_from_details({
        "EOAT Type": "Hybrid",
        "# of Cups": "",
        "# of Grippers": "",
        "Sensors Present?": "Unknown / Not Checked",
        "Part-Present Detection Present?": "N/A",
        "Vacuum Confirmation Present?": "N/A",
        "Part Name/Description": "",
    })

    assert configuration["vacuum_cup_count"] is None
    assert configuration["gripper_count"] is None
    assert configuration["sensors_present"] is None
    assert configuration["part_present_sensor_present"] is None
    assert configuration["vacuum_confirmation_sensor_present"] is None
    assert configuration["description"] is None


def test_canonical_sensor_parent_false_constrains_missing_child_flags():
    values = normalize_optional_hardware_values(
        eoat_type="Hybrid",
        vacuum_cup_count=None,
        gripper_count=None,
        sensors_present=False,
        part_present_sensor_present=None,
        vacuum_confirmation_sensor_present=None,
    )

    assert values["part_present_sensor_present"] is False
    assert values["vacuum_confirmation_sensor_present"] is False


def test_exclusive_mechanical_type_has_zero_vacuum_hardware_without_erasing_explicit_values():
    normalized = normalize_optional_hardware_values(
        eoat_type="Mechanical / Gripper",
        vacuum_cup_count=None,
        gripper_count=2,
        sensors_present=True,
        part_present_sensor_present=True,
        vacuum_confirmation_sensor_present=None,
    )
    explicit = normalize_optional_hardware_values(
        eoat_type="Mechanical / Gripper",
        vacuum_cup_count=1,
        gripper_count=2,
        sensors_present=True,
        part_present_sensor_present=True,
        vacuum_confirmation_sensor_present=True,
    )

    assert normalized["vacuum_cup_count"] == 0
    assert normalized["vacuum_confirmation_sensor_present"] is False
    assert explicit["vacuum_cup_count"] == 1
    assert explicit["vacuum_confirmation_sensor_present"] is True
