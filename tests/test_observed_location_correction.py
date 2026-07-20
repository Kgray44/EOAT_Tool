from __future__ import annotations

import pytest

from scripts.database.correct_observed_location_data import _issue_resolution


@pytest.mark.parametrize(
    ("issue_code", "rows", "expected_status"),
    [
        ("POSSIBLE_PART_NOT_CONFIRMED", [], "RESOLVED"),
        ("INSTALLATION_DATE_UNKNOWN", [], "RESOLVED"),
        ("CURRENT_LOCATION_UNKNOWN", [], "RESOLVED"),
        ("MISSING_MACHINE", [], "RESOLVED"),
        ("MISSING_TOOL", [], "NOT_APPLICABLE"),
        ("AMBIGUOUS_MACHINE_VALUE", [], "RESOLVED"),
        ("CONFLICTING_EOAT_ATTRIBUTE", [85, 86, 89], "RESOLVED"),
        ("CONFLICTING_CURRENT_ASSIGNMENT", [94, 95, 96, 97], "RESOLVED"),
        ("PLACEHOLDER_PHOTO_ROW", [], "NOT_APPLICABLE"),
    ],
)
def test_owner_approved_issue_resolutions_do_not_require_fabricated_values(issue_code, rows, expected_status):
    status, rationale = _issue_resolution(issue_code, rows)
    assert status == expected_status
    assert "fabricat" not in rationale.casefold() or "no " in rationale.casefold()


def test_unknown_issue_is_not_silently_marked_resolved():
    with pytest.raises(RuntimeError, match="No owner-approved resolution"):
        _issue_resolution("UNREVIEWED", [])
