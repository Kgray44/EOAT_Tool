from datetime import datetime
from types import SimpleNamespace

from server.eoat_api.audit_profiles import latest_physical_audit


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
