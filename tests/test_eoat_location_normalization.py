from tools.eoat_location_normalization import (
    is_stored_machine_reference,
    load_policy,
    normalize_machine_reference,
    normalized_source_rows,
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
    ]
    normalized = normalized_source_rows({82: {"EOAT Assembly ID": "CL-EOAT-0050"}, 93: {"EOAT Assembly ID": "CL-EOAT-0054"}})
    assert normalized[82]["EOAT Assembly ID"] == "CL-EOAT-0057"
    assert normalized[93]["EOAT Assembly ID"] == "CL-EOAT-0061"
    assert normalized[82]["Original EOAT Assembly ID"] == "CL-EOAT-0050"
