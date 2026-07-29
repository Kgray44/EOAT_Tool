from tools.eoat_location_normalization import (
    identity_resolution,
    is_stored_machine_reference,
    load_policy,
    normalize_machine_reference,
    normalized_source_rows,
    physical_eoat_identifier,
    physical_eoat_uuid,
)


def test_owner_approved_machine_alias_and_na_storage_rule_are_explicit():
    assert normalize_machine_reference("26 - Xqual in 25") == "26"
    assert is_stored_machine_reference("N/A")
    assert not is_stored_machine_reference("26 - Xqual in 25")


def test_cleanroom_split_mapping_is_complete_and_deterministic():
    policy = load_policy()
    identifiers = [
        unit["eoat_identifier"] for split in policy["physical_unit_splits"] for unit in split["units"]
    ]
    assert identifiers == [
        "CL-EOAT-0050", "CL-EOAT-0057", "CL-EOAT-0058",
        "CL-EOAT-0052", "CL-EOAT-0059", "CL-EOAT-0060", "CL-EOAT-0054", "CL-EOAT-0061",
        "CL-EOAT-0062", "P4-EOAT-0057", "P4-EOAT-0059", "P4-EOAT-0060", "P4-EOAT-0061",
    ]
    normalized = normalized_source_rows({
        82: {"EOAT Assembly ID": "CL-EOAT-0050", "Entry Type": "Audited"},
        93: {"EOAT Assembly ID": "CL-EOAT-0054", "Entry Type": "Audited"},
        95: {"EOAT Assembly ID": "P4-EOAT-0057", "Entry Type": "Audited"},
    })
    assert normalized[82]["EOAT Assembly ID"] == "CL-EOAT-0057"
    assert normalized[93]["EOAT Assembly ID"] == "CL-EOAT-0062"
    assert normalized[95]["EOAT Assembly ID"] == "P4-EOAT-0059"
    assert normalized[82]["Original EOAT Assembly ID"] == "CL-EOAT-0050"


def test_identity_mapping_does_not_create_physical_units_from_compatibility_rows():
    assert physical_eoat_identifier("CL-EOAT-0050", 82, "Compatible") is None
    assert identity_resolution("CL-EOAT-0050", 82, "Compatible") == "compatibility-only evidence"
    assert physical_eoat_identifier("P4-EOAT-0018", 44, "Audited") == "P4-EOAT-0018"
    assert identity_resolution("P4-EOAT-0018", 70, "Audited") == "repeated audit of same unit"
    assert physical_eoat_uuid("P4-EOAT-0018") == physical_eoat_uuid("P4-EOAT-0018")
